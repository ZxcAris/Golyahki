import json
from pathlib import Path
import time

import pytest
from pydantic import ValidationError
from PySide6.QtCore import QObject, QMetaObject, QPointF, Qt, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from golyah.appearance import Appearance, load_appearance
from golyah.anki import card_css
from golyah.bridge import Bridge
from golyah.storage import Storage
from test_anki import transport_service
from test_qml import visual_child


@pytest.mark.parametrize('patch', [
    {'accent': 'red'}, {'cardBackground': '#123'}, {'cardFont': 'a";body{color:red}'},
    {'uiFont': 'bad\nfont'}, {'cardWidth': 10000}, {'overlayDim': -1},
    {'cardFontSize': 100}, {'cardLineHeight': 0}, {'theme': 'light'},
])
def test_bad_preferences_are_rejected(patch):
    with pytest.raises(ValidationError):
        Appearance.model_validate(patch)


def test_stored_preferences_recover_individual_invalid_values():
    value = load_appearance({'accent': '#80CDB8', 'cardWidth': 2, 'cardFont': 'Georgia',
                             'overlayDim': 80, 'unknown': True})
    assert value.accent == '#80cdb8' and value.cardFont == 'Georgia'
    assert value.cardWidth == Appearance().cardWidth and value.overlayDim == 80
    assert load_appearance(None) == Appearance()


def test_live_preferences_persist_atomically_without_changing_words(tmp_path):
    app = QApplication.instance() or QApplication([])
    storage = Storage(tmp_path / 'settings.sqlite')
    bridge = Bridge(storage)
    try:
        bridge.lookup('quick', 'A quick reply.')
        storage.save_record(bridge.record)
        original = storage.get_record(bridge.record.uid).model_dump()
        assert bridge.setAppearance(json.dumps({'accent': '#80CDB8', 'cardAccent': '#ffbd85',
            'cardFont': 'Georgia', 'cardWidth': 640, 'overlayDim': 0}))
        assert '#ffbd85' in bridge.card['sentence_html']
        previous = bridge.appearance.copy()
        assert not bridge.setAppearance(json.dumps({'accent': '#111111', 'cardWidth': 4}))
        assert bridge.appearance == storage.setting('appearance') == previous
        assert storage.get_record(bridge.record.uid).model_dump() == original
        restored = Bridge(storage)
        try:
            assert restored.appearance == previous
            assert restored.anki.appearance.cardFont == 'Georgia'
        finally:
            restored.close()
        bridge.resetAppearance()
        assert bridge.appearance == Appearance().model_dump()
    finally:
        bridge.close()


def test_custom_anki_style_updates_model_without_notes_or_scheduling():
    from golyah.anki import FIELDS, FRONT, BACK
    service, state = transport_service(fields=FIELDS, templates={'Vocabulary': {'Front': FRONT, 'Back': BACK}})
    service.appearance = Appearance(cardFont='Georgia', cardWidth=640, cardFontSize=24,
        cardBackground='#252135', cardBackgroundEnd='#171b22', cardGradient=True, cardAccent='#edabdb')
    service.ensure_model()
    assert state['css'] == card_css(service.appearance)
    assert 'linear-gradient' in state['css'] and 'max-width:640px' in state['css']
    assert [a for a, _ in state['calls'] if a.startswith('update')] == ['updateModelStyling']
    assert not state['notes']


def test_apply_anki_uses_snapshot_and_reports_connection_failure(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    bridge = Bridge(Storage(tmp_path / 'apply.sqlite'))
    instances = []
    class Offline:
        def __init__(self, appearance, builder): self.appearance = appearance; self.builder = builder; instances.append(self)
        def connect(self): raise RuntimeError('Anki недоступна.')
    monkeypatch.setattr('golyah.bridge.AnkiService', Offline)
    try:
        bridge.applyAnkiAppearance()
        bridge.setAppearance(json.dumps({'cardAccent': '#80cdb8'}))
        deadline = time.monotonic() + 4
        while bridge.busy and time.monotonic() < deadline: QTest.qWait(20)
        assert not bridge.busy and 'Anki недоступна' in bridge.status
        assert instances[0].appearance.cardAccent == Appearance().cardAccent
    finally:
        bridge.close()


@pytest.mark.parametrize('preferences,width,height', [
    ({}, 1280, 900),
    ({'uiFontSize':20, 'cardFontSize':24, 'cardWidth':360, 'cardFont':'Georgia',
      'cardGradient':True, 'cardBackground':'#272235', 'cardAccent':'#e6b886'}, 1040, 680),
    ({'uiFontSize':12, 'cardFontSize':13, 'cardWidth':840, 'cardRadius':0, 'cardSpacing':8}, 1280, 900),
])
def test_qml_appearance_live_preview_and_popup(tmp_path, preferences, width, height):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge(Storage(tmp_path / 'ui.sqlite'))
    bridge.setAppearance(json.dumps(preferences))
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    engine.rootContext().setContextProperty('backend', bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'golyah/qml/Main.qml')))
    assert engine.rootObjects(), warnings
    main = engine.rootObjects()[0]
    overlay = main.findChild(QQuickWindow, 'captureOverlay')
    popup = main.findChild(QQuickWindow, 'wordPopup')
    try:
        main.setWidth(width); main.setHeight(height); main.setProperty('page', 3)
        bridge.lookup('quick', 'A quick reply.')
        QTest.qWait(120)
        preview = visual_child(main.contentItem(), 'appearancePreviewCard')
        assert preview.property('previewOnly') and preview.property('translationVisible')
        term = visual_child(preview, 'selectedWord')
        assert term.property('font').family() == bridge.appearance['cardFont']
        assert term.property('lineCount') == 1, 'The sample word fits even with a large font and narrow card'
        background = visual_child(main.contentItem(), 'appearancePreviewBackground')
        assert background.width() <= bridge.appearance['cardWidth']
        assert background.width() > 220 and background.height() > 300
        assert background.property('radius') == bridge.appearance['cardRadius']
        # Sliders and typed custom colors use the public persistence path.
        accent = visual_child(main.contentItem(), 'accentColorHex')
        accent.setProperty('text', '#80CDB8')
        assert QMetaObject.invokeMethod(accent, 'editingFinished')
        assert bridge.appearance['accent'] == '#80cdb8'
        accent.setProperty('text', 'bad')
        QMetaObject.invokeMethod(accent, 'editingFinished')
        assert accent.property('text') == '#80CDB8'
        bridge.setAppearance(json.dumps({'accent':'#86bdef'}))
        assert accent.property('text') == '#86BDEF', 'Color field keeps its live binding'
        if not preferences:
            picker_button = visual_child(main.contentItem(), 'accentColorPicker')
            QMetaObject.invokeMethod(picker_button, 'clicked'); QTest.qWait(60)
            picker = main.findChild(QObject, 'accentColorDialog')
            assert picker.property('visible')
            picker.setProperty('selectedColor', QColor('#dca8dd'))
            assert QMetaObject.invokeMethod(picker, 'accept')
            assert bridge.appearance['accent'] == '#dca8dd'
            choice = visual_child(main.contentItem(), 'uiFontChoice')
            point = choice.mapToScene(QPointF(choice.width()/2, choice.height()/2)).toPoint()
            QTest.mouseClick(main, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            QTest.qWait(60)
            assert choice.property('down'), 'Font selector opens its actual menu'
            QTest.keyClick(main, Qt.Key.Key_Escape)
        slider = visual_child(main.contentItem(), 'overlayDimSlider')
        slider.setProperty('value', 80)
        assert QMetaObject.invokeMethod(slider, 'moved')
        assert bridge.appearance['overlayDim'] == 80
        # The sample card cannot save a word or request a definition.
        before = bridge.record.model_dump()
        plus = visual_child(preview, 'addWordButton')
        QMetaObject.invokeMethod(plus, 'clicked')
        assert bridge.record.model_dump() == before and not bridge.busy
        # Preserve screenshots of both control sections at the chosen size.
        output = Path(__file__).resolve().parents[1] / 'test-results' / 'appearance'
        output.mkdir(parents=True, exist_ok=True)
        main.grabWindow().save(str(output / f'interface-{width}-{bridge.appearance["cardFontSize"]}.png'))
        page = main.findChild(QObject, 'appearancePage')
        page.setProperty('section', 1); QTest.qWait(70)
        main.grabWindow().save(str(output / f'card-{width}-{bridge.appearance["cardFontSize"]}.png'))
        main.hide(); popup.show(); QTest.qWait(70)
        assert popup.width() == bridge.appearance['cardWidth']
        popup.grabWindow().save(str(output / f'popup-{bridge.appearance["cardFontSize"]}.png'))
        assert not warnings, warnings
    finally:
        bridge.close()
        for window in [overlay, popup, main]: window.close()
        engine.deleteLater(); QTest.qWait(20)


def test_overlay_dimming_changes_live_but_ocr_text_stays_clear(tmp_path):
    app = QApplication.instance() or QApplication([])
    bridge = Bridge(Storage(tmp_path / 'overlay.sqlite'))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'golyah/qml/Main.qml')))
    main = engine.rootObjects()[0]; main.hide()
    overlay = main.findChild(QQuickWindow, 'captureOverlay')
    popup = main.findChild(QQuickWindow, 'wordPopup')
    try:
        bridge._overlay.update(visible=True, left=0, top=0, width=800, height=500, pixelWidth=800, pixelHeight=500)
        bridge.set_ocr_words([{'id':0,'text':'quick','polygon':[[100,190],[250,190],[250,240],[100,240]],'confidence':1,'line':0,'block':0}])
        bridge.overlayChanged.emit()
        QTest.mouseMove(overlay, QPointF(500,100).toPoint())
        for dim in [0,80,28]:
            bridge.setAppearance(json.dumps({'overlayDim':dim})); QTest.qWait(100)
            pixels = overlay.grabWindow()
            scale = pixels.width() / overlay.width()
            assert abs(pixels.pixelColor(round(500*scale),round(100*scale)).alpha() - 255*dim/100) < 4
            assert pixels.pixelColor(round(160*scale),round(215*scale)).alpha() <= 1
    finally:
        bridge.close()
        for window in [overlay,popup,main]: window.close()
        engine.deleteLater(); QTest.qWait(20)
