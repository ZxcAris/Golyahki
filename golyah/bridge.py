from __future__ import annotations

import html
import json
import math
import sys
import threading
from pathlib import Path
from multiprocessing.shared_memory import SharedMemory
import numpy as np
from httpx import NetworkError, RemoteProtocolError, TimeoutException

from PySide6.QtCore import (QObject, Property, QProcess, QRunnable, QThreadPool,
                           QTimer, Signal, Slot, Qt)
from PySide6.QtGui import QGuiApplication, QCursor, QRegion
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QFileDialog

from .anki import AnkiService, preview_html
from .appearance import Appearance, load_appearance
from .card_builder import CardBuilder, BLOCKS, MODES, gap_fields, load_builder
from .dictionaries import DictionaryService
from .gemini import FALLBACK_MODEL, GeminiService, apply_result, ensure_enriched, get_key, set_key, thinking_budget
from .gemini_quota import quota_error
from .models import OCRWord, StudyRecord
from .hotkeys import HotkeyListener, OverlayKeyboardListener
from .mouse_guard import OverlayMouseGuard
from .selection import selection, highlight_layout, reading_order, word_at
from .storage import Storage
from .windows import (capture, monitors, monitor_name, overlay_geometry,
                      selected_target, screen_sources, window_sources,
                      foreground_window, window_is_ours, restore_window, fullscreen_window, focus_our_window)


class TaskSignals(QObject):
    finished = Signal(object, object, object)


class Task(QRunnable):
    def __init__(self, function, done, receiver):
        super().__init__()
        self.function = function
        self.done = done
        self.signals = TaskSignals()
        self.signals.finished.connect(receiver, Qt.ConnectionType.QueuedConnection)

    def run(self):
        try:
            result, error = self.function(), None
        except Exception as exc:
            result, error = None, exc
        try:
            self.signals.finished.emit(self, result, error)
        except RuntimeError:
            # The application may have closed while an external request finished.
            pass


class Bridge(QObject):
    builderChanged = Signal()
    ankiPreviewChanged = Signal()
    appearanceChanged = Signal()
    cardChanged = Signal()
    listsChanged = Signal()
    settingsChanged = Signal()
    stateChanged = Signal()
    overlayChanged = Signal()
    previewReady = Signal()
    resetCard = Signal()
    captureRequested = Signal()
    captureFailed = Signal()
    hotkeyTriggered = Signal()
    selectionHotkeyTriggered = Signal()
    overlayKeyTriggered = Signal(int)
    mouseFocusRequested = Signal(object)
    windowMoveStarted = Signal(object)

    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage
        self.dictionary = DictionaryService(storage)
        self.gemini = GeminiService(storage)
        self._appearance = load_appearance(storage.setting("appearance", {}))
        self._builder = load_builder(storage.setting('card_builder', {}))
        self._builder_uid, self._builder_mode, self._builder_side = '', 'forward', 'front'
        self.anki = AnkiService(appearance=self._appearance, builder=self._builder)
        self.record = StudyRecord(term="")
        self.cardChanged.connect(self.ankiPreviewChanged.emit)
        self.listsChanged.connect(self.ankiPreviewChanged.emit)
        self.appearanceChanged.connect(self.ankiPreviewChanged.emit)
        self._status = "Выберите слово или захватите экран."
        self._busy = False
        self._tasks = set()
        self._saved = []
        self._dictionaries = []
        self._query = ""
        self._drafts = False
        hotkey = storage.setting('hotkey', 'Alt+Q')
        if storage.setting('capture_overlay_version', '') != '3':
            hotkey = 'Alt+Q'
            storage.set_setting('hotkey', hotkey)
            storage.set_setting('capture_overlay_version', '3')
        self._settings = {"hotkey": hotkey,
                          "captureMode": storage.setting("capture_mode", "monitor"),
                          "windowId": storage.setting('capture_window', ''),
                          "screenId": storage.setting('capture_screen', ''),
                          "ocrEngine": storage.setting('ocr_engine','auto'),
                          "focusOnHover": storage.setting('focus_on_hover', 'false') == 'true',
                          "overlayMouseButton": storage.setting('overlay_mouse_button', 'mouse5'),
                          "windows": [], "screens": [],
                          "model": storage.setting("gemini_model", "gemini-2.5-flash"),
                          "geminiFallback": storage.setting("gemini_fallback", True),
                          "deck": storage.setting("anki_deck", ""),
                          "models": [], "decks": [], "hasKey": bool(get_key())}
        if self._settings['captureMode'] not in ('monitor', 'window'):
            self._settings['captureMode'] = 'monitor'
            storage.set_setting('capture_mode', 'monitor')
        if self._settings['overlayMouseButton'] not in ('none', 'mouse4', 'mouse5'):
            self._settings['overlayMouseButton'] = 'mouse5'
        self._generation = 0
        self._cancel = threading.Event()
        self._llm_save_uid = None
        self._llm_timer = QTimer(self)
        self._llm_timer.setSingleShot(True)
        # Each HTTP request is limited to 30 s; allow a primary and fallback
        # request, but also bound key retrieval, SDK work and the whole operation.
        self._llm_timer.setInterval(65000)
        self._llm_timer.timeout.connect(self._llm_timeout)
        self._overlay = {"visible": False, "stage": "ready", "passive": False, "multiSelect": False, "words": [], "sentenceLines": [], "selectionText": "",
                         "left": 0, "top": 0, "width": 800, "height": 600,
                         "pixelWidth": 800, "pixelHeight": 600, "selected": []}
        self._overlay.update(anchorX=0, anchorY=0)
        self._selection_anchor = None
        self._overlay_window = None
        self.overlayChanged.connect(self._update_mask)
        self._image = None
        self._capture_target = None
        self._requested_target = None
        self._capture_starting = False
        self._capture_cursor = None
        self.captureFailed.connect(self._clear_capture_request)
        self._previous_window = 0
        self._closing = False
        self._ocr_id = 0
        self._ocr_pending = {}
        self._ocr_inflight = None
        self._ocr_queued = None
        self._ocr_memory = {}
        self._ocr_buffer = b""
        self._ocr_log = b""
        self._worker = QProcess(self)
        self._worker.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._worker.readyReadStandardOutput.connect(self._read_worker)
        self._worker.readyReadStandardError.connect(self._read_worker_error)
        self._worker.errorOccurred.connect(self._worker_error)
        self._worker.finished.connect(self._worker_finished)
        self._worker.started.connect(self._warm_ocr)
        self._ocr_timer = QTimer(self)
        self._ocr_timer.setSingleShot(True)
        self._ocr_timer.timeout.connect(self._ocr_timeout)
        self._ocr_idle_timer = QTimer(self)
        self._ocr_idle_timer.setSingleShot(True)
        self._ocr_idle_timer.setInterval(180000)
        self._ocr_idle_timer.timeout.connect(self._release_idle_worker)
        self.hotkeyTriggered.connect(self.requestHotkeyCapture, Qt.ConnectionType.QueuedConnection)
        self.selectionHotkeyTriggered.connect(self.requestHotkeySelection, Qt.ConnectionType.QueuedConnection)
        self.hotkey = HotkeyListener(self.hotkeyTriggered.emit, self.selectionHotkeyTriggered.emit)
        self.overlayKeys = OverlayKeyboardListener(self.overlayKeyTriggered.emit)
        self.overlayMouse = OverlayMouseGuard(self.mouseFocusRequested.emit, self.windowMoveStarted.emit)
        self.overlayMouse.focus_on_hover = self._settings['focusOnHover']
        self.overlayMouse.interaction_button = {'none': 0, 'mouse4': 4, 'mouse5': 5}[self._settings['overlayMouseButton']]
        self.mouseFocusRequested.connect(self._focus_mouse_window, Qt.ConnectionType.QueuedConnection)
        self.windowMoveStarted.connect(self._pin_moved_window, Qt.ConnectionType.QueuedConnection)
        self.overlayKeyTriggered.connect(self.overlayKey, Qt.ConnectionType.QueuedConnection)
        self.refresh()

    @Property("QVariantMap", notify=cardChanged)
    def card(self):
        value = self.record.model_dump(exclude={"entries"})
        saved = self.storage.record_state(self.record.uid) if self.record.term else None
        value["saved"] = bool(saved and saved['status'] == "saved")
        value["saved_to_anki"] = bool(saved and saved['has_anki'])
        value["entries"] = [e.model_dump(exclude={"raw"}) for e in self.record.entries]
        value["complete"] = self.record.complete
        value["uid"] = self.record.uid
        value['gap_available'] = bool(gap_fields(self.record)['GapSentence'])
        sentence = self.record.sentence
        positions = self.record.selected_positions
        if not positions and sentence and self.record.term:
            offset = sentence.casefold().find(self.record.term.casefold())
            positions = [[offset, offset + len(self.record.term)]] if offset >= 0 else []
        cursor, highlighted = 0, []
        for start, end in sorted(positions):
            if start < cursor or end > len(sentence) or start < 0:
                continue
            highlighted.append(html.escape(sentence[cursor:start]))
            highlighted.append('<font color="' + self._appearance.cardAccent + '"><b>' + html.escape(sentence[start:end]) + '</b></font>')
            cursor = end
        highlighted.append(html.escape(sentence[cursor:]))
        value["sentence_html"] = "".join(highlighted)
        return value

    @Property(str, constant=True)
    def version(self):
        from . import __version__
        return __version__

    @Property("QVariantList", notify=listsChanged)
    def saved(self):
        return self._saved

    @Property("QVariantList", notify=listsChanged)
    def dictionaries(self):
        return self._dictionaries

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return self._settings

    @Property("QVariantMap", notify=appearanceChanged)
    def appearance(self):
        return self._appearance.model_dump()

    @Property("QVariantList", constant=True)
    def fontFamilies(self):
        from PySide6.QtGui import QFontDatabase
        preferred = ["Segoe UI", "Arial", "Verdana", "Georgia", "Consolas", "Cascadia Code"]
        installed = QFontDatabase.families()
        return [f for f in preferred if f in installed] + sorted(set(installed) - set(preferred))

    @Slot(str, result=bool)
    def setAppearance(self, payload):
        try:
            changes = json.loads(payload)
            if not isinstance(changes, dict):
                raise ValueError("Ожидается набор настроек оформления.")
            updated = Appearance.model_validate({**self.appearance, **changes})
        except (ValueError, TypeError):
            self.message("Проверьте оформление: цвет #RRGGBB, название шрифта и диапазон значений.")
            return False
        if updated == self._appearance:
            return True
        self._appearance = updated
        self.storage.set_setting("appearance", self.appearance)
        self.anki.appearance = updated
        self.appearanceChanged.emit()
        self.cardChanged.emit()
        return True

    @Slot()
    def resetAppearance(self):
        self.setAppearance(json.dumps(Appearance().model_dump()))
        self.message("Стандартное оформление Golyahki восстановлено.")

    @Slot()
    def applyAnkiAppearance(self):
        if self._busy:
            return
        self.message("Обновляю оформление карточек Anki…", True)
        generation = self._generation
        # Take a snapshot so changing sliders during the request cannot change its result.
        service = AnkiService(appearance=self._appearance.model_copy(), builder=self._builder.model_copy(deep=True))
        def work():
            service.connect()
            service.apply_layouts()
        def done(value, error):
            if generation != self._generation:
                return
            self.message(self.friendly_error(error) if error else "Оформление применено к карточкам Anki. Слова и повторения сохранены.", False)
        self.task(work, done)

    @Property('QVariantMap', notify=builderChanged)
    def cardBuilder(self):
        value = self._builder.model_dump()
        for mode in MODES:
            for side in ('front','back'):
                for block in value['layouts'][mode][side]:
                    block['required'] = block['key'] in ('prompt','answer')
                    block['label'] = ('Вопрос' if block['key'] == 'prompt' else 'Ответ') if block['required'] else BLOCKS[block['key']][0]
        return value

    def _save_builder(self, value):
        self._builder = CardBuilder.model_validate(value)
        self.storage.set_setting('card_builder', self._builder.model_dump())
        self.anki.builder = self._builder
        self.builderChanged.emit()
        self.ankiPreviewChanged.emit()

    @Slot(str, str, str, bool, result=bool)
    def setBuilderBlock(self, mode, side, key, visible):
        try:
            value = self._builder.model_dump()
            block = next(b for b in value['layouts'][mode][side] if b['key'] == key)
            block['visible'] = visible
            self._save_builder(value)
            return True
        except (ValueError, KeyError, StopIteration):
            self.message('Основной вопрос и ответ обязательны. Проверьте блок карточки.')
            return False

    @Slot(str, str, str, int)
    def moveBuilderBlock(self, mode, side, key, direction):
        if mode not in MODES or side not in ('front','back') or direction not in (-1,1):
            return
        value = self._builder.model_dump()
        blocks = value['layouts'][mode][side]
        index = next((i for i,b in enumerate(blocks) if b['key'] == key), -1)
        target = index + direction
        if index >= 0 and 0 <= target < len(blocks):
            blocks[index], blocks[target] = blocks[target], blocks[index]
            self._save_builder(value)

    @Slot()
    def resetCardBuilder(self):
        self._save_builder(CardBuilder().model_dump())
        self.message('Стандартный порядок блоков восстановлен. Для Anki нажмите «Применить конструктор».')

    def _builder_record(self):
        if self._builder_uid:
            selected = self.storage.get_record(self._builder_uid)
            if selected:
                return selected
        if self.record.term and (not self._builder_uid or self._builder_uid == self.record.uid):
            return self.record
        preferred = self.storage.preferred_record_uid()
        return self.storage.get_record(preferred) if preferred else StudyRecord(term='')

    @Property('QVariantList', notify=ankiPreviewChanged)
    def builderWords(self):
        values = self.storage.records()
        if self.record.term and not any(r['uid'] == self.record.uid for r in values):
            values.insert(0, {'uid':self.record.uid,'term':self.record.term,'sentence':self.record.sentence})
        return [{'uid':r['uid'], 'label':r['term'] + (' · ' + r['sentence'][:85] if r['sentence'] else '')} for r in values]

    @Property('QVariantMap', notify=ankiPreviewChanged)
    def builderWord(self):
        record = self._builder_record()
        return {'uid':record.uid if record.term else '', 'term':record.term, 'sentence':record.sentence,
                'learning_modes':record.learning_modes, 'gap_available':bool(gap_fields(record)['GapSentence']),
                'has_anki':bool(record.anki_note_id or record.anki_note_ids), 'complete':record.complete,
                'anki_modes_pending':record.anki_modes_pending,
                'stored':bool(record.term and self.storage.record_state(record.uid))}

    @Property(str, notify=ankiPreviewChanged)
    def ankiPreviewHtml(self):
        return preview_html(self._builder_record(), self._builder, self._appearance, self._builder_mode, self._builder_side)

    @Slot(str)
    def selectBuilderWord(self, uid):
        if uid == self.record.uid or self.storage.record_state(uid):
            self._builder_uid = uid
            self.ankiPreviewChanged.emit()

    @Slot(str, str)
    def setAnkiPreview(self, mode, side):
        if mode in MODES and side in ('front','back'):
            self._builder_mode, self._builder_side = mode, side
            self.ankiPreviewChanged.emit()

    @Slot(str, str, result=bool)
    def setRecordStudyModes(self, uid, payload):
        if self._busy:
            return False
        stored = self.storage.get_record(uid)
        record = self.record if self.record.term and self.record.uid == uid else stored
        if not record:
            return False
        try:
            value = StudyRecord.model_validate({**record.model_dump(), 'learning_modes':json.loads(payload)})
            if 'gap' in value.learning_modes and not gap_fields(value)['GapSentence']:
                raise ValueError('Для пропуска нужно предложение с выбранным словом.')
        except (ValueError, TypeError) as exc:
            self.message('Выберите хотя бы один вариант. Для пропуска нужен контекст с выбранным словом.')
            return False
        if record.learning_modes == value.learning_modes:
            return True
        value.anki_modes_pending = bool(value.anki_note_id or value.anki_note_ids)
        if stored:
            # Choosing study modes must never overwrite a saved meaning with a fresh lookup.
            saved_value = stored.model_copy(deep=True)
            saved_value.learning_modes = value.learning_modes.copy()
            saved_value.anki_modes_pending = bool(stored.anki_note_id or stored.anki_note_ids)
            value.anki_modes_pending = saved_value.anki_modes_pending
            self.storage.save_record(saved_value)
            self.refresh()
        if self.record.uid == uid:
            self.record = value
            self.cardChanged.emit()
        self.ankiPreviewChanged.emit()
        self.message('Варианты сохранены. Обновите их в Anki.' if value.anki_modes_pending else 'При добавлении будут созданы выбранные варианты обучения.')
        return True

    @Slot(str)
    def syncStudyModes(self, uid):
        if self._busy:
            return
        record = self.storage.get_record(uid)
        if not record or not record.complete:
            self.message('Сначала добавьте слово и завершите его объяснение.')
            return
        deck = self._settings['deck']
        if not deck:
            self.message('Выберите колоду Anki в настройках.')
            return
        service = AnkiService(appearance=self._appearance.model_copy(), builder=self._builder.model_copy(deep=True))
        record.anki_modes_pending = True
        record.destination = 'anki'
        if not record.anki_note_id:
            record.status = 'pending_anki'
        self.storage.save_record(record)
        self.refresh()
        self.message('Обновляю варианты обучения в Anki…', True)
        generation = self._generation
        def work():
            try:
                service.sync_modes(record, deck)
                record.status, record.error = 'saved', ''
            except Exception as exc:
                record.error = self.friendly_error(exc)
                raise
            finally:
                self.storage.save_record(record)
        def done(value, error):
            self.refresh()
            if generation != self._generation:
                return
            if self.record.uid == record.uid:
                self.record = record
                self.cardChanged.emit()
            self.message(self.friendly_error(error) if error else 'Варианты обучения обновлены. История прежних карточек сохранена.', False)
        self.task(work, done)

    @Property(str, notify=stateChanged)
    def status(self):
        return self._status

    @Property(bool, notify=stateChanged)
    def busy(self):
        return self._busy

    @Property("QVariantMap", notify=overlayChanged)
    def overlay(self):
        return self._overlay

    def message(self, value, busy=None):
        self._status = str(value)
        if busy is not None:
            self._busy = busy
        self.stateChanged.emit()

    def task(self, function, done):
        task = Task(function, done, self._task_finished)
        self._tasks.add(task)
        QThreadPool.globalInstance().start(task)

    @Slot(object, object, object)
    def _task_finished(self, task, result, error):
        self._tasks.discard(task)
        if not self._closing:
            task.done(result, error)

    @Slot(QObject)
    def attachOverlay(self, window):
        self._overlay_window = window
        window.widthChanged.connect(self._update_mask)
        window.heightChanged.connect(self._update_mask)
        self._update_mask()

    @Slot(QObject, result='QVariantMap')
    def windowFrameMargins(self, window):
        margins = window.frameMargins()
        return {'left': margins.left(), 'top': margins.top(),
                'right': margins.right(), 'bottom': margins.bottom()}

    @Slot()
    def _update_mask(self):
        self.overlayKeys.enabled = self._overlay['visible']
        self.overlayMouse.enabled = self._overlay['visible']
        window = self._overlay_window
        if window is None or not self._overlay['visible']:
            return
        # Clear the former word-only mask: the complete source is now dimmed.
        # The selection surface keeps mouse input within the active overlay.
        window.setMask(QRegion())

    @Slot(object)
    def _pin_moved_window(self, hwnd):
        if not self._overlay['visible'] or self._closing:
            return
        for window in QGuiApplication.allWindows():
            if window.objectName() == 'wordPopup' and int(window.winId()) == hwnd:
                window.setProperty('manuallyPlaced', True)
                return

    @Slot(object)
    def _focus_mouse_window(self, hwnd):
        if not self._overlay['visible'] or self._closing or not self._settings['focusOnHover']:
            return
        for window in QGuiApplication.allWindows():
            if window.isVisible() and int(window.winId()) == hwnd:
                # Explicit native activation supports our initially non-activating
                # fullscreen windows without changing/recreating their HWNDs.
                focus_our_window(hwnd)
                return

    @Slot(bool)
    def setFocusOnHover(self, enabled):
        self._settings['focusOnHover'] = enabled
        self.overlayMouse.focus_on_hover = enabled
        self.storage.set_setting('focus_on_hover', 'true' if enabled else 'false')
        self.settingsChanged.emit()

    @Slot(str)
    def setOverlayMouseButton(self, button):
        if button not in ('none', 'mouse4', 'mouse5'):
            return
        self._settings['overlayMouseButton'] = button
        self.overlayMouse.interaction_button = {'none': 0, 'mouse4': 4, 'mouse5': 5}[button]
        self.storage.set_setting('overlay_mouse_button', button)
        self.settingsChanged.emit()

    @Slot()
    def initialize(self):
        try:
            self.dictionary.ensure_builtin()
            self.refresh()
        except Exception as exc:
            self.message('Не удалось загрузить встроенный словарь. ' + str(exc))
        self.refreshCaptureSources()
        try:
            self.hotkey.register(self._settings["hotkey"])
        except Exception as exc:
            self.message(exc)
        self.overlayKeys.start()
        try:
            self.overlayMouse.start()
        except Exception as exc:
            self.message(exc)
        # Loading existing databases stays fast; an explicit import starts from Settings/Dictionary.

    @Slot()
    def refreshCaptureSources(self):
        try:
            windows, screens = window_sources(), screen_sources()
        except Exception as exc:
            self.message('Не удалось обновить источники захвата. ' + str(exc))
            return
        self._settings.update(windows=windows, screens=screens)
        if not self._settings['screenId'] and screens:
            source = next((s for s in screens if s['primary']), screens[0])
            self._settings['screenId'] = source['id']
            self.storage.set_setting('capture_screen', source['id'])
        self.settingsChanged.emit()

    @Slot(str, str)
    def selectCaptureSource(self, mode, source_id):
        if mode not in ('window', 'monitor'):
            return
        items = self._settings['windows' if mode == 'window' else 'screens']
        if source_id and not any(item['id'] == source_id for item in items):
            self.message('Источник больше недоступен. Обновите список и выберите источник.')
            return
        key = 'windowId' if mode == 'window' else 'screenId'
        setting = 'capture_window' if mode == 'window' else 'capture_screen'
        self._settings.update(captureMode=mode)
        self._settings[key] = source_id
        self.storage.set_setting('capture_mode', mode)
        self.storage.set_setting(setting, source_id)
        self.settingsChanged.emit()
        self.message('Источник захвата сохранён.' if source_id else 'Выберите окно для захвата.')

    def set_ocr_words(self, values):
        words = [OCRWord.model_validate(value) for value in values]
        self._selection_anchor = None
        self._overlay['words'], self._overlay['sentenceLines'] = highlight_layout(words)

    @Slot()
    def refresh(self):
        self._saved = self.storage.records(self._query, self._drafts)
        self._dictionaries = self.dictionary.list()
        self.listsChanged.emit()

    @Slot(str, bool)
    def filterRecords(self, query, drafts):
        self._query, self._drafts = query, drafts
        self.refresh()

    @Slot(str, str)
    def lookup(self, term, sentence):
        self.cancel()
        if not term.strip():
            return
        self.record = StudyRecord(term=term.strip(), sentence=sentence.strip(), entries=self.dictionary.lookup(term))
        self.record.select_defaults()
        existing = self.storage.get_record(self.record.uid)
        if existing:
            self.record.learning_modes = existing.learning_modes.copy()
            self.record.anki_note_ids = existing.anki_note_ids.copy()
            self.record.anki_note_id = existing.anki_note_id
            self.record.anki_paused_cards = existing.anki_paused_cards.copy()
            self.record.anki_modes_pending = existing.anki_modes_pending
            self.record.word_audio, self.record.sentence_audio = existing.word_audio, existing.sentence_audio
        self.cardChanged.emit()
        self.resetCard.emit()
        self.message("Словарь найден." if self.record.entries else "Слова нет в подключённых словарях. Доступен Explain.", False)

    @Slot(int, int)
    def selectSense(self, entry_index, sense_index):
        if not 0 <= entry_index < len(self.record.entries):
            return
        old = self.record
        self.cancel()
        self.record = StudyRecord(term=old.term, sentence=old.sentence,
            selected_positions=old.selected_positions, selection_preview=old.selection_preview, entries=old.entries,
            entry_index=entry_index, sense_index=sense_index, learning_modes=old.learning_modes,
            anki_note_ids=old.anki_note_ids, anki_note_id=old.anki_note_id,
            anki_paused_cards=old.anki_paused_cards, anki_modes_pending=old.anki_modes_pending,
            word_audio=old.word_audio, sentence_audio=old.sentence_audio)
        self.record.select_defaults()
        self.cardChanged.emit()

    @Slot(str, str)
    def editContext(self, term, sentence):
        if self.record.term == term.strip() and self.record.sentence == sentence.strip():
            return
        self.lookup(term, sentence)

    @Slot(str)
    def loadRecord(self, uid):
        value = self.storage.get_record(uid)
        if value:
            self.cancel()
            if value.error:
                value.error = self.friendly_error(value.error)
            self.record = value
            self.cardChanged.emit()
            self.resetCard.emit()
            self.message(value.error or "Сохранённая запись открыта.", False)

    @Slot(str)
    def deleteRecord(self, uid):
        self.storage.delete_record(uid)
        self.refresh()

    @Slot(str)
    def requestLLM(self, mode):
        if self._busy or not self.record.term:
            return
        self._cancel = threading.Event()
        generation = self._generation
        record = self.record.model_copy(deep=True)
        cancel = self._cancel
        self.message("Gemini готовит объяснение…" if mode == "explain" else
                     "Gemini переводит выделенный текст…" if mode == "both" else "Gemini переводит контекст…", True)
        self._llm_save_uid = None
        self._llm_timer.start()
        def done(value, error):
            if generation != self._generation:
                return
            self._llm_timer.stop()
            if error:
                self.message(self.friendly_error(error), False)
                return
            result, model = value
            apply_result(self.record, result, model)
            self.cardChanged.emit()
            fallback = model == FALLBACK_MODEL and self._settings["model"] != model
            self.message("Ответ Gemini готов · резервная Flash Lite 3.5." if fallback else "Ответ Gemini готов.", False)
        self.task(lambda: self.gemini.generate(record, mode, cancel), done)

    @Slot()
    def cancel(self):
        self._generation += 1
        self._cancel.set()
        self._llm_timer.stop()
        self._llm_save_uid = None
        self._image = None
        self._clear_capture_request()
        if self._ocr_pending:
            self._ocr_pending.clear()
            self._ocr_timer.stop()
        if self._ocr_queued:
            self._release_ocr_memory(self._ocr_queued[0])
        self._ocr_queued = None
        # Keep the loaded models. The response ID rejects cancelled results;
        # only the latest waiting frame is retained when Alt+Q is repeated.
        self.message("Запрос отменён." if self._busy else self._status, False)

    @Slot()
    def _llm_timeout(self):
        saving = self._llm_save_uid == self.record.uid
        self.cancel()
        error = "Gemini не ответила вовремя. Повторите запрос."
        if saving:
            self.record.status = "draft"
            self.record.error = error
            self.storage.save_record(self.record)
            self.refresh()
            self.cardChanged.emit()
        self.message(("Черновик сохранён. " if saving else "") + error, False)

    def friendly_error(self, error):
        if isinstance(error, TimeoutException):
            return "Время ожидания Gemini истекло. Проверьте подключение и повторите запрос."
        if isinstance(error, (NetworkError, RemoteProtocolError)):
            return "Не удалось связаться с Gemini. Проверьте подключение и повторите запрос."
        api_errors = sys.modules.get('google.genai.errors')
        if api_errors and isinstance(error, api_errors.APIError):
            if error.code == 400:
                return "Gemini отклонила запрос. Проверьте API-ключ и выбранную модель в настройках."
            if error.code in (401, 403):
                return "Gemini отклонила API-ключ или доступ к модели. Проверьте ключ и модель в настройках."
            if error.code == 404:
                return "Выбранная модель Gemini недоступна. Выберите другую модель в настройках."
            if error.code in (500, 502, 503, 504):
                return "Сервис Gemini временно недоступен. Повторите запрос чуть позже."
        quota = quota_error(error, self._settings["model"])
        value = str(quota) if quota else str(error)
        # SDK errors can include request URLs. Never surface keys or credentials.
        try:
            key = get_key()
            if key:
                value = value.replace(key, "[ключ скрыт]")
        except Exception:
            pass
        return value[:700]

    @Slot()
    def addWord(self):
        """The card's plus saves locally and also sends to a configured Anki deck."""
        self.prepareSave("anki" if self._settings["deck"] else "dictionary", automatic=True)

    @Slot(str)
    def prepareSave(self, destination, *, automatic=False):
        if self._busy or not self.record.term:
            return
        self._cancel = threading.Event()
        generation = self._generation
        record = self.record.model_copy(deep=True)
        existing = self.storage.get_record(record.uid)
        if existing and existing.complete and not record.complete:
            # Reopening the same term/context must not replace saved manual edits with a draft.
            def meaning(value):
                entry = value.selected_entry()
                sense = entry.senses[min(value.sense_index, len(entry.senses)-1)].translation if entry and entry.senses else None
                return (value.lemma, entry.dictionary if entry else None, entry.pos if entry else None, sense)
            if meaning(existing) == meaning(record):
                modes, pending = record.learning_modes.copy(), record.anki_modes_pending
                record = existing.model_copy(deep=True)
                record.learning_modes, record.anki_modes_pending = modes, pending
        record.destination = destination
        record.status = "draft"
        record.error = ""
        self.storage.save_record(record)
        self.refresh()
        cancel = self._cancel
        self.record = record.model_copy(deep=True)
        self.cardChanged.emit()
        self.message("Готовлю недостающие LLM-данные для сохранения…", True)
        self._llm_save_uid = record.uid
        self._llm_timer.start()
        def work():
            try:
                ensure_enriched(record, self.gemini, cancel)
                if cancel.is_set():
                    raise ValueError('Запрос отменён.')
                record.status = "preview"
                self.storage.save_record(record)
                return record
            except Exception as exc:
                # Cancellation/timeout leaves the original draft in place.
                # A late response must not overwrite a successful newer retry.
                if cancel.is_set():
                    raise
                record.status = "draft"
                record.error = self.friendly_error(exc)
                self.storage.save_record(record)
                raise
        def done(value, error):
            self.refresh()
            if generation != self._generation:
                return
            self._llm_timer.stop()
            self._llm_save_uid = None
            if error:
                self.record = self.storage.get_record(record.uid) or record
                self.cardChanged.emit()
                self.message("Черновик сохранён. " + self.friendly_error(error), False)
                return
            self.record = value
            self.cardChanged.emit()
            if automatic:
                self.message("Сохраняю слово…", False)
                self.confirmSave()
            else:
                self.message("Проверьте материал перед сохранением.", False)
                self.previewReady.emit()
        self.task(work, done)

    @Slot(str)
    def updatePreview(self, payload):
        edits = json.loads(payload)
        for name in ("translation", "definition_en", "usage_en", "sentence_translation", "context_explanation"):
            if name in edits:
                setattr(self.record, name, str(edits[name]))
        if "examples" in edits:
            from .models import Example
            self.record.examples = [Example.model_validate(e) for e in edits["examples"]]
        if self.record.term:
            self.storage.save_record(self.record)
            self.refresh()
        self.cardChanged.emit()

    @Slot(result=bool)
    def confirmSave(self):
        if self._busy or not self.record.complete:
            self.message("Сначала получите обязательные LLM-данные.")
            return False
        if not self.record.definition_en.strip() or not self.record.translation.strip():
            self.message("Заполните перевод и английское объяснение.")
            return False
        if self.record.sentence and (not self.record.sentence_translation.strip() or not self.record.context_explanation.strip()):
            self.message("Заполните перевод и объяснение предложения.")
            return False
        record = self.record.model_copy(deep=True)
        if record.destination == "dictionary":
            record.status = "saved"
            record.error = ""
            self.storage.save_record(record)
            self.record = record
            self.cardChanged.emit()
            self.refresh()
            self.message("Сохранено в Dictionary.")
            return True
        record.status = "pending_anki"
        self.storage.save_record(record)
        generation = self._generation
        deck = self._settings["deck"]
        self.message("Добавляю в Anki…", True)
        def work():
            try:
                record.anki_note_id = self.anki.add(record, deck)
                record.status = "saved"
                record.error = ""
            except Exception as exc:
                record.error = self.friendly_error(exc)
                raise
            finally:
                self.storage.save_record(record)
            return record
        def done(value, error):
            self.refresh()
            if generation != self._generation:
                return
            self.record = value or self.storage.get_record(record.uid)
            self.cardChanged.emit()
            self.message("Сохранено в Dictionary и Anki." if not error else "Слово сохранено локально. Отправка в Anki ожидает повтора. " + self.friendly_error(error), False)
        self.task(work, done)
        return True

    @Slot()
    def chooseDictionary(self):
        path, _ = QFileDialog.getOpenFileName(None, "Импортировать словарь", "", "Словари (*.zip *.json)")
        if path:
            self.importDictionary(path)

    @Slot(str)
    def importDictionary(self, path):
        if self._busy:
            return
        self.message("Импортирую словарь…", True)
        generation = self._generation
        cancel = threading.Event()
        self._cancel = cancel
        def progress(count):
            if cancel.is_set():
                raise ValueError("Импорт отменён; действующий словарь сохранён.")
        def done(value, error):
            self.refresh()
            if generation != self._generation:
                return
            self.message(self.friendly_error(error) if error else
                f"{value['title']}: {value['count']:,} записей. " + ("Уже импортирован." if value["unchanged"] else "Готово."), False)
        self.task(lambda: self.dictionary.import_file(path, progress), done)

    @Slot(int, bool, int)
    def configureDictionary(self, dictionary_id, enabled, priority):
        self.dictionary.configure(dictionary_id, enabled, priority)
        self.refresh()

    @Slot(int)
    def deleteDictionary(self, dictionary_id):
        self.dictionary.delete(dictionary_id)
        self.refresh()

    @Slot(bool)
    def transferDictionary(self, importing):
        dialog = QFileDialog.getOpenFileName if importing else QFileDialog.getSaveFileName
        path, _ = dialog(None, "Личный Dictionary", "dictionary.json", "JSON (*.json)")
        if not path:
            return
        try:
            if importing:
                count = self.storage.import_records(path)
                self.message(f"Импортировано записей: {count}.")
            else:
                self.storage.export_records(path)
                self.message("Dictionary экспортирован.")
            self.refresh()
        except Exception as exc:
            self.message(self.friendly_error(exc))

    @Slot(str, str, str, str)
    def saveSettings(self, hotkey, capture_mode, model, deck):
        if capture_mode not in ('monitor', 'window'):
            self.message('Выберите захват монитора или активного окна.')
            return
        try:
            self.hotkey.register(hotkey)
        except Exception as exc:
            # Restore the previous valid registration after a failed replacement.
            try:
                self.hotkey.register(self._settings["hotkey"])
            except Exception:
                pass
            self.message(exc)
            return
        for key, value in [("hotkey", hotkey), ("capture_mode", capture_mode),
                           ("gemini_model", model), ("anki_deck", deck)]:
            self.storage.set_setting(key, value)
        self._settings.update(hotkey=hotkey, captureMode=capture_mode, model=model, deck=deck)
        self.settingsChanged.emit()
        self.message("Настройки сохранены.")

    @Slot(str)
    def saveKey(self, value):
        try:
            set_key(value)
            self.gemini.reset_client()
            self._settings["hasKey"] = bool(get_key())
            self.settingsChanged.emit()
            self.message("Ключ сохранён в хранилище Windows." if value else "Ключ удалён.")
        except Exception as exc:
            self.message(self.friendly_error(exc))

    @Slot(str, result=str)
    def thinkingStatus(self, model):
        if model.strip().removeprefix("models/").lower() == FALLBACK_MODEL:
            return "Thinking: Minimal · минимум размышлений"
        return ("Thinking budget: 0 · размышления отключены" if thinking_budget(model) == 0
                else "Thinking: параметры выбранной модели")

    @Slot(bool)
    def setGeminiFallback(self, enabled):
        if self._settings["geminiFallback"] == enabled:
            return
        self.storage.set_setting("gemini_fallback", enabled)
        self._settings["geminiFallback"] = enabled
        self.settingsChanged.emit()
        self.message("Резервная Flash Lite 3.5 включена." if enabled else "Резервная Flash Lite 3.5 выключена.")

    @Slot()
    def checkModels(self):
        if self._busy:
            return
        self.message("Проверяю доступные модели Gemini…", True)
        generation = self._generation
        def done(value, error):
            if generation != self._generation:
                return
            if not error:
                self._settings["models"] = value
                self.settingsChanged.emit()
            self.message(self.friendly_error(error) if error else "Список моделей получен. Выберите модель и сохраните настройки.", False)
        self.task(self.gemini.models, done)

    @Slot()
    def checkAnki(self):
        if self._busy:
            return
        self.message("Проверяю AnkiConnect…", True)
        generation = self._generation
        def work():
            decks = self.anki.connect()
            self.anki.ensure_model()
            return decks
        def done(value, error):
            if generation != self._generation:
                return
            if not error:
                self._settings["decks"] = value
                self.settingsChanged.emit()
            self.message(self.friendly_error(error) if error else
                         "Anki подключена. Оформление карточек обновлено. " +
                         (f"Колода: {self._settings['deck']}." if self._settings['deck'] in value
                          else "Выберите колоду для отправки слов."), False)
        self.task(work, done)

    @Slot(str)
    def selectAnkiDeck(self, deck):
        if deck and self._settings["decks"] and deck not in self._settings["decks"]:
            self.message("Выберите колоду из списка Anki.")
            return
        self.storage.set_setting("anki_deck", deck)
        self._settings["deck"] = deck
        self.settingsChanged.emit()
        self.cardChanged.emit()
        self.message(f"Слова будут добавляться в Dictionary и Anki → {deck}." if deck
                     else "Слова будут сохраняться в Dictionary.")

    @Slot()
    def requestCapture(self):
        self._request_capture(None)

    @Slot()
    def requestHotkeyCapture(self):
        if self._closing or self._capture_starting:
            return
        cursor = QCursor.pos()
        if self._overlay['visible']:
            if self._overlay['stage'] == 'ready':
                self._open_word_at(cursor)
            return
        self._request_capture(cursor)

    @Slot()
    def requestHotkeySelection(self):
        if self._closing or self._capture_starting:
            return
        if self._overlay['visible']:
            self._open_word_at(QCursor.pos(), multiple=True)
        elif self.hotkey.selection_is_primary:
            self.requestHotkeyCapture()

    def _clear_capture_request(self):
        self._capture_starting = False
        self._requested_target = None
        self._capture_cursor = None

    def _request_capture(self, cursor):
        if self._closing or self._capture_starting or self._overlay['visible']:
            return
        self.cancel()
        self._capture_starting = True
        self._capture_cursor = cursor
        # Identify the explicit source before hiding our UI; never follow focus/cursor.
        current = foreground_window()
        try:
            mode = self._settings['captureMode']
            source_id = self._settings['windowId' if mode == 'window' else 'screenId']
            if not source_id:
                raise ValueError('Выберите окно или экран в настройках захвата.')
            target = selected_target(mode, source_id)
        except Exception as exc:
            self.message(exc, False)
            self.captureFailed.emit()
            return
        if target.hwnd:
            self._previous_window = target.hwnd
        elif current and not window_is_ours(current):
            self._previous_window = current
        self._overlay.update(visible=False, words=[], sentenceLines=[], selected=[], selectionText='', multiSelect=False)
        self._overlay['settleMs']=target.settle_ms
        self.overlayChanged.emit()
        self._requested_target = target
        self.captureRequested.emit()

    @Slot()
    def startCapture(self):
        target = self._requested_target
        self._requested_target = None
        generation = self._generation
        if target is None:
            return
        if target.hwnd:
            # Restoring a minimized window changes its rectangle asynchronously.
            # Re-read geometry after the hide/restore delay, retaining the chosen source.
            try:
                target = selected_target('window', self._settings['windowId'])
            except Exception as exc:
                self.message(exc, False)
                self.captureFailed.emit()
                return
        self._capture_target = target
        target.fullscreen = fullscreen_window(self._previous_window, target)
        self.message("Захватываю экран…", True)
        def done(value, error):
            if generation != self._generation:
                return
            if error:
                self.message(error, False)
                self.captureFailed.emit()
                return
            self._image = value
            screens = QGuiApplication.screens()
            displays = monitors()
            if not screens or not 0 < target.monitor <= len(displays):
                self._image = None
                self.message('Источник захвата изменился. Обновите список экранов и повторите захват.', False)
                self.captureFailed.emit()
                return
            physical = displays[target.monitor - 1]
            name = monitor_name(physical[0])
            screen = next((s for s in screens if s.name().casefold() == name.casefold()),
                          screens[min(target.monitor - 1, len(screens) - 1)])
            geometry = screen.geometry()
            ratio = screen.devicePixelRatio()
            x, y, width, height = overlay_geometry(target, physical, (geometry.x(), geometry.y()), ratio)
            self._overlay.update(visible=True, stage="recognizing", passive=target.fullscreen,
                left=x, top=y, width=width, height=height,
                pixelWidth=value.shape[1], pixelHeight=value.shape[0], words=[], sentenceLines=[], selected=[], selectionText='', multiSelect=False)
            self._capture_starting = False
            self.overlayChanged.emit()
            self._run_ocr()
        self.task(lambda: capture(target), done)

    def _start_worker(self):
        if self._worker.state() != QProcess.ProcessState.NotRunning or self._closing:
            return
        self._ocr_buffer = b''
        self._ocr_log = b''
        self._ocr_inflight = None
        if getattr(sys, 'frozen', False):
            self._worker.start(str(Path(sys.executable).with_name('Golyahki-OCR.exe')), ['--ocr-worker'])
        else:
            self._worker.start(sys.executable, ['-m', 'golyah', '--ocr-worker'])

    def _warm_ocr(self):
        self._ocr_idle_timer.stop()
        self._worker.write((json.dumps({'id':0,'command':'warmup','engine':self._settings['ocrEngine']})+'\n').encode())

    @Slot(str)
    def selectOCREngine(self,engine):
        if engine not in ('auto','windows','paddle') or engine==self._settings['ocrEngine']:
            return
        self.cancel()
        self._settings['ocrEngine']=engine
        self.storage.set_setting('ocr_engine',engine)
        self.settingsChanged.emit()
        if self._worker.state()==QProcess.ProcessState.Running:
            self._warm_ocr()

    def _release_ocr_memory(self,request_id=None):
        ids=list(self._ocr_memory) if request_id is None else [request_id]
        for key in ids:
            memory=self._ocr_memory.pop(key,None)
            if memory is not None:
                memory.close(); memory.unlink()

    def _run_ocr(self):
        self._ocr_idle_timer.stop()
        self._ocr_id += 1
        self._ocr_pending = {self._ocr_id: True}
        self.message("Распознаю слова…", True)
        if self._worker.state() == QProcess.ProcessState.NotRunning:
            self._start_worker()
        if self._worker.state() == QProcess.ProcessState.Starting:
            if not self._worker.waitForStarted(3000):
                self.message("Не удалось запустить процесс OCR.", False)
                self._ocr_pending = {}
                self.captureFailed.emit()
                return
        try:
            shape = self._image.shape
            memory = SharedMemory(create=True, size=self._image.nbytes)
            self._ocr_memory[self._ocr_id] = memory
            np.ndarray(shape, dtype=np.uint8, buffer=memory.buf)[:] = self._image
        except (OSError, ValueError, BufferError):
            self._release_ocr_memory(self._ocr_id)
            self._image = None
            self._ocr_pending.clear()
            self._ocr_idle_timer.start()
            self.message('Не удалось передать кадр в OCR. Закройте лишние приложения и повторите захват.', False)
            self.captureFailed.emit()
            return
        request={"id":self._ocr_id,"memory":memory.name,"shape":shape,'engine':self._settings['ocrEngine']}
        payload = (json.dumps(request) + "\n").encode()
        if self._ocr_inflight is None:
            self._worker.write(payload)
            self._ocr_inflight = self._ocr_id
        else:
            if self._ocr_queued:
                self._release_ocr_memory(self._ocr_queued[0])
            self._ocr_queued = (self._ocr_id, payload)
        self._image = None
        self._ocr_timer.start(180000)

    def _read_worker(self):
        self._ocr_buffer += bytes(self._worker.readAllStandardOutput())
        while b"\n" in self._ocr_buffer:
            line, self._ocr_buffer = self._ocr_buffer.split(b"\n", 1)
            if not line.startswith(b"GOLYAH_JSON:"):
                continue
            try:
                response = json.loads(line[len(b"GOLYAH_JSON:"):].decode("utf-8"))
                if (not isinstance(response, dict) or not isinstance(response.get('id'), int)
                        or isinstance(response['id'], bool)):
                    raise ValueError('Invalid OCR response')
                if response['id'] in self._ocr_pending and 'error' not in response:
                    result = response['result']
                    if not isinstance(result, dict) or not isinstance(result['words'], list):
                        raise ValueError('Invalid OCR result')
                    for word in result['words']:
                        x1, y1, x2, y2 = OCRWord.model_validate(word).bounds()
                        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)) or x2 <= x1 or y2 <= y1:
                            raise ValueError('Invalid OCR coordinates')
                    if (not isinstance(result['seconds'], (int, float)) or isinstance(result['seconds'], bool)
                            or not math.isfinite(result['seconds']) or result['seconds'] < 0):
                        raise ValueError('Invalid OCR timing')
            except (ValueError, TypeError, KeyError, UnicodeError):
                self._ocr_buffer = b''
                self._ocr_pending.clear()
                self._ocr_timer.stop()
                self._worker.kill()
                self._release_ocr_memory()
                self.message('Процесс OCR вернул некорректный ответ. Повторите захват.', False)
                self.captureFailed.emit()
                return
            self._release_ocr_memory(response['id'])
            if response['id'] == self._ocr_inflight:
                self._ocr_inflight = None
                if self._ocr_queued:
                    self._ocr_inflight, payload = self._ocr_queued
                    self._ocr_queued = None
                    self._worker.write(payload)
            if response["id"] not in self._ocr_pending:
                if self._ocr_inflight is None and not self._ocr_pending:
                    self._ocr_idle_timer.start()
                continue
            self._ocr_pending.clear()
            self._ocr_timer.stop()
            if self._ocr_inflight is None:
                self._ocr_idle_timer.start()
            if "error" in response:
                self.message("OCR: " + response["error"], False)
                self.captureFailed.emit()
                return
            value = response["result"]
            self.set_ocr_words(value['words'])
            self._overlay['stage'] = 'ready'
            self.overlayChanged.emit()
            engine=value.get('engine','PaddleOCR')
            fallback=' · WindowsOCR недоступен, выбран PaddleOCR' if value.get('fallback') else ''
            self.message(f"{engine}: {len(value['words'])} слов · {value['seconds']:.2f} с{fallback}. Alt+Q / ЛКМ — слово; Ctrl+Alt+Q / Ctrl+ЛКМ — добавить слово.", False)
            if not value['words']:
                self.message('Текст не найден. Откройте приложение с английским текстом и повторите захват.', False)
                self.captureFailed.emit()
            else:
                self._open_capture_word()

    def _open_capture_word(self):
        cursor, self._capture_cursor = self._capture_cursor, None
        if cursor is not None:
            self._open_word_at(cursor)

    def _open_word_at(self, cursor, multiple=False):
        if not self._overlay['visible'] or self._overlay['stage'] != 'ready':
            return
        overlay = self._overlay
        x = (cursor.x() - overlay['left']) * overlay['pixelWidth'] / overlay['width']
        y = (cursor.y() - overlay['top']) * overlay['pixelHeight'] / overlay['height']
        word = word_at(overlay['words'], x, y)
        if word is not None:
            self._choose_word(word['id'], multiple, cursor)

    def _read_worker_error(self):
        self._ocr_log = (self._ocr_log + bytes(self._worker.readAllStandardError()))[-8000:]

    def _worker_error(self, error):
        if self._ocr_pending:
            self._ocr_pending.clear()
            self._ocr_timer.stop()
            self.message("Процесс OCR недоступен. Перезапустите захват.", False)
            self.captureFailed.emit()

    def _worker_finished(self, code, status):
        self._ocr_idle_timer.stop()
        self._release_ocr_memory()
        self._ocr_inflight = None
        self._ocr_queued = None
        if self._ocr_pending:
            self._ocr_pending.clear()
            self._ocr_timer.stop()
            self.message(f"Процесс OCR завершился ({code}). " + self._ocr_log.decode("utf-8", errors="replace")[-900:], False)
            self.captureFailed.emit()

    def _release_idle_worker(self):
        if (not self._closing and not self._ocr_pending and self._ocr_inflight is None
                and self._ocr_queued is None and not self._capture_starting):
            self._worker.kill()

    def _ocr_timeout(self):
        self._ocr_pending.clear()
        self._ocr_inflight = None
        self._ocr_queued = None
        self._worker.kill()
        self.message("OCR превысил время ожидания. Повторите захват; проверьте загрузку моделей.", False)
        self.captureFailed.emit()

    @Slot(int, bool)
    def chooseWord(self, word_id, multiple):
        self._choose_word(word_id, multiple)

    @Slot(int, bool)
    def chooseRange(self, word_id, additive=False):
        self._choose_word(word_id, additive, range_select=True)

    def _choose_word(self, word_id, multiple, cursor=None, *, range_select=False):
        words = reading_order([OCRWord.model_validate(w) for w in self._overlay['words']])
        ids = [word.id for word in words]
        if word_id not in ids:
            return
        chosen = self._overlay["selected"]
        if range_select:
            anchor = self._selection_anchor if self._selection_anchor in ids else word_id
            start, end = sorted((ids.index(anchor), ids.index(word_id)))
            interval = ids[start:end + 1]
            chosen = list(dict.fromkeys(chosen + interval)) if multiple else interval
            self._selection_anchor = anchor
        elif multiple:
            chosen = [i for i in chosen if i != word_id] if word_id in chosen else chosen + [word_id]
            self._selection_anchor = word_id if word_id in chosen else chosen[-1] if chosen else None
        else:
            chosen = [word_id]
            self._selection_anchor = word_id
        self._overlay["selected"] = chosen
        self._overlay['multiSelect'] = multiple or range_select
        self._overlay['selectionText'] = selection([OCRWord.model_validate(w) for w in self._overlay['words']], chosen).get('display', '')
        self.overlayChanged.emit()
        if chosen:
            self._open_selection(cursor if cursor is not None else QCursor.pos())
        else:
            self.cancel()
            self.record = StudyRecord(term="")
            self.cardChanged.emit()

    @Slot()
    def clearSelection(self):
        self._selection_anchor = None
        self._overlay.update(selected=[], selectionText='', multiSelect=False)
        self.overlayChanged.emit()

    def _open_selection(self, cursor):
        data = selection([OCRWord.model_validate(w) for w in self._overlay["words"]], self._overlay["selected"])
        if not data["term"]:
            return
        self._overlay.update(anchorX=cursor.x(), anchorY=cursor.y())
        self.overlayChanged.emit()
        self.lookup(data["term"], data["sentence"])
        self.record.selected_positions = data["positions"]
        self.record.selection_preview = data["display"]
        self.cardChanged.emit()
        # Popup appearance is coordinated in QML through the card signal.

    @Slot(int)
    def overlayKey(self, key):
        if not self._overlay['visible']:
            return
        if key == 0x1b:
            self.closeOverlay()

    @Slot()
    def closeOverlay(self):
        self.cancel()
        self._selection_anchor = None
        self.overlayKeys.enabled = False
        self.overlayMouse.enabled = False
        self._requested_target = None
        self._overlay.update(visible=False, stage='ready', words=[], sentenceLines=[], selected=[], selectionText='', multiSelect=False)
        self.overlayChanged.emit()
        restore_window(self._previous_window)

    def close(self):
        self._closing = True
        self._llm_timer.stop()
        self._ocr_idle_timer.stop()
        self._cancel.set()
        close_gemini = getattr(self.gemini, "close", None)
        if close_gemini:
            close_gemini()
        self.hotkey.close()
        self.overlayKeys.close()
        self.overlayMouse.close()
        self._worker.kill()
        self._worker.waitForFinished(2000)
        self._release_ocr_memory()
