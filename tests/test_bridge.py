import threading
import time

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from golyah.bridge import Bridge
from golyah.models import Enrichment, Explanation, ContextTranslation
from golyah.storage import Storage


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bridge(app, tmp_path):
    value = Bridge(Storage(tmp_path / "app.sqlite"))
    yield value
    value.close()


def await_idle(bridge):
    deadline = time.monotonic() + 5
    while bridge.busy and time.monotonic() < deadline:
        QTest.qWait(20)
    assert not bridge.busy


@pytest.mark.parametrize('passive', [False, True])
@pytest.mark.parametrize('focus_on_hover', [False, True])
def test_escape_closes_overlay_during_recognition_and_selection(bridge, passive, focus_on_hover):
    bridge.setFocusOnHover(focus_on_hover)
    for stage in ['recognizing', 'ready']:
        bridge._overlay.update(visible=True, passive=passive, stage=stage,
            words=[{'id': 0}], selected=[0], selectionText='quick')
        bridge._ocr_pending = {123: True}
        bridge.overlayChanged.emit()
        assert bridge.overlayKeys.enabled
        bridge.overlayKeyTriggered.emit(0x1b)
        QTest.qWait(20)
        assert not bridge.overlay['visible']
        assert not bridge.overlay['words'] and not bridge.overlay['selected']
        assert not bridge._ocr_pending and not bridge._capture_starting
        assert not bridge.overlayKeys.enabled and not bridge.overlayMouse.enabled
    generation = bridge._generation
    bridge.overlayKey(0x1b)
    assert bridge._generation == generation, 'Esc outside the overlay must leave work alone'


class Provider:
    def generate(self, record, mode, cancel):
        explain = Explanation(definition_en="To undergo a situation.", usage_en="A verb in this sentence.",
                              translation_ru="испытывать")
        context = ContextTranslation(translation_ru="Вы испытаете это.", explanation_ru="О переживании ситуации.")
        result = Enrichment(explain=explain, context=context) if mode == "both" else explain if mode == "explain" else context
        return result, "test-model"


def test_missing_phrase_waits_for_explicit_llm_request(bridge):
    calls = []
    class Translator(Provider):
        def generate(self, record, mode, cancel):
            calls.append((record.term, record.selected_positions, mode))
            explain = Explanation(definition_en="Something could become visible on television.",
                usage_en="Describes a possible TV appearance.",
                translation_ru="появляться")
            return Enrichment(explain=explain, context=ContextTranslation(
                translation_ru="Что-то может появиться на телевидении.",
                explanation_ru="О возможном появлении на телевидении.")), "test-model"
    bridge.gemini = Translator()
    bridge._settings["hasKey"] = True
    bridge.lookup("Something may", "Something may appear on TV.")
    QTest.qWait(100)
    bridge.lookup("Something may appear on TV", "Something may appear on TV.")
    bridge.record.selected_positions = [[0, 9], [10, 13], [14, 20], [21, 23], [24, 27]]
    QTest.qWait(600)
    await_idle(bridge)
    assert calls == []
    assert bridge.record.explain is None and bridge.record.context is None
    bridge.requestLLM("both")
    await_idle(bridge)
    assert calls == [(bridge.record.term, bridge.record.selected_positions, "both")]
    assert bridge.record.translation == "Что-то может появиться на телевидении."
    assert bridge.record.complete


@pytest.mark.parametrize("action", ["cancel", "new_word", "explain", "save"])
def test_phrase_selection_does_not_duplicate_or_reopen_requests(bridge, action):
    calls = []
    class Translator(Provider):
        def generate(self, record, mode, cancel):
            calls.append(mode)
            return super().generate(record, mode, cancel)
    bridge.gemini = Translator()
    bridge._settings["hasKey"] = True
    bridge.lookup("experience it", "You experience it.")
    if action == "cancel":
        bridge.cancel()
    elif action == "new_word":
        bridge.lookup("quick", "A quick look.")
    elif action == "explain":
        bridge.requestLLM("explain")
    else:
        bridge.prepareSave("dictionary")
    QTest.qWait(650)
    await_idle(bridge)
    assert calls == (["explain"] if action == "explain" else ["both"] if action == "save" else [])


def test_dictionary_phrase_and_missing_key_do_not_start_automatic_llm(bridge):
    from golyah.models import Entry, Sense
    calls = []
    class Dictionary:
        def lookup(self, term):
            return [Entry(word=term, senses=[Sense(translation="появиться на телевидении")])]
    bridge._settings["hasKey"] = True
    class NoRequests:
        def generate(self, *args):
            calls.append(args)
            raise AssertionError("Selection must not request LLM data")
    bridge.gemini = NoRequests()
    bridge.dictionary = Dictionary()
    bridge.lookup("appear on TV", "Something may appear on TV.")
    assert bridge.record.translation == "появиться на телевидении"
    QTest.qWait(650)
    assert not bridge.busy and bridge.record.explain is None
    assert calls == []
    bridge.dictionary = type("Missing", (), {"lookup": lambda self, term: []})()
    bridge._settings["hasKey"] = False
    bridge.lookup("Something may appear on TV", "Something may appear on TV.")
    QTest.qWait(650)
    assert not bridge.busy and bridge.record.explain is None
    assert calls == []


@pytest.mark.parametrize("automatic", [False, True])
def test_full_sentence_save_exports_entire_translation_to_anki(bridge, automatic):
    from golyah.anki import note_fields
    calls, exported = [], []
    class SentenceTranslator:
        def generate(self, record, mode, cancel):
            calls.append(mode)
            assert record.term == "Something may appear on TV"
            assert not record.entries
            return Enrichment(explain=Explanation(definition_en="Something could become visible on TV.",
                usage_en="Describes a possible appearance on television.", translation_ru="появляться"),
                context=ContextTranslation(translation_ru="Что-то может появиться на телевидении.",
                    explanation_ru="Говорится о возможном появлении на телевидении.")), "test-model"
    bridge.gemini = SentenceTranslator()
    class Anki:
        def add(self, record, deck):
            assert deck == "Vocabulary"
            exported.append(note_fields(record)["Translation"])
            return 123
    bridge.anki = Anki()
    bridge._settings["deck"] = "Vocabulary"
    bridge._settings["hasKey"] = True
    bridge.lookup("Something may appear on TV", "Something may appear on TV.")
    QTest.qWait(650)
    assert calls == []
    if automatic:
        bridge.addWord()
    else:
        bridge.prepareSave("dictionary")
    await_idle(bridge)
    assert note_fields(bridge.record)["Translation"] == "Что-то может появиться на телевидении."
    if not automatic:
        assert bridge.confirmSave()
    saved = bridge.storage.get_record(bridge.record.uid)
    assert saved.status == "saved" and saved.translation == "Что-то может появиться на телевидении."
    assert calls == ["both"]
    assert exported == ([saved.translation] if automatic else [])


@pytest.mark.parametrize("requested", [None, "explain", "context", "both"])
def test_phrase_anki_add_generates_only_missing_llm_data(bridge, requested):
    calls, sent = [], []
    class Translator(Provider):
        def generate(self, record, mode, cancel):
            calls.append(mode)
            return super().generate(record, mode, cancel)
    class Anki:
        def add(self, record, deck):
            assert record.complete and deck == "Vocabulary"
            sent.append(record.uid)
            return 123
    bridge.gemini = Translator()
    bridge.anki = Anki()
    bridge._settings.update(hasKey=True, deck="Vocabulary")
    bridge.lookup("experience it", "You experience it.")
    if requested:
        bridge.requestLLM(requested)
        await_idle(bridge)
    QTest.qWait(650)
    assert calls == ([requested] if requested else [])
    bridge.addWord()
    await_idle(bridge)
    missing = {None: ["both"], "explain": ["context"], "context": ["explain"], "both": []}
    assert calls == ([requested] if requested else []) + missing[requested]
    assert sent == [bridge.record.uid]
    assert bridge.record.status == "saved" and bridge.record.destination == "anki"


def test_quota_error_is_readable_and_word_stays_in_drafts(bridge):
    from golyah.gemini_quota import GeminiQuotaError
    class Limited:
        def generate(self, *args):
            raise GeminiQuotaError("gemini-2.5-flash", "daily", time.time() + 3600, 20)
    bridge.gemini = Limited()
    bridge.lookup("experience", "You experience it.")
    bridge.requestLLM("context")
    await_idle(bridge)
    assert "Дневной лимит" in bridge.status and "20" in bridge.status
    assert bridge.record.term == "experience" and bridge.record.context is None
    bridge.addWord()
    await_idle(bridge)
    draft = bridge.storage.get_record(bridge.record.uid)
    assert draft.status == "draft" and "Дневной лимит" in draft.error
    assert "RESOURCE_EXHAUSTED" not in draft.error


def test_legacy_quota_error_is_sanitized_when_opening_draft(bridge):
    bridge.lookup("experience", "You experience it.")
    bridge.record.error = ("429 RESOURCE_EXHAUSTED. {'error': {'message': 'Quota exceeded for metric: "
        "generate_content_free_tier_requests_per_day, limit: 20. Please retry in 40s.'")
    bridge.storage.save_record(bridge.record)
    bridge.loadRecord(bridge.record.uid)
    assert "Дневной лимит" in bridge.status and "Дневной лимит" in bridge.record.error
    assert "{'error'" not in bridge.record.error


def test_fallback_preference_is_persisted(bridge):
    assert bridge.settings["geminiFallback"]
    bridge.setGeminiFallback(False)
    restored = Bridge(bridge.storage)
    try:
        assert not restored.settings["geminiFallback"]
    finally:
        restored.close()


def test_card_identifies_fallback_response(bridge):
    class Lite(Provider):
        def generate(self, *args):
            result, _ = super().generate(*args)
            return result, "gemini-3.5-flash-lite"
    bridge.gemini = Lite()
    bridge.lookup("experience", "You experience it.")
    bridge.requestLLM("explain")
    await_idle(bridge)
    assert bridge.record.llm_model == "gemini-3.5-flash-lite"
    assert "резервная Flash Lite" in bridge.status


def test_save_without_buttons_enriches_and_preserves_manual_edits(bridge):
    bridge.gemini = Provider()
    bridge.lookup("experience", "You experience it.")
    assert bridge.record.explain is None
    bridge.prepareSave("dictionary")
    await_idle(bridge)
    assert bridge.record.complete and bridge.record.status == "preview"
    bridge.updatePreview('{"definition_en":"My own English explanation."}')
    assert bridge.confirmSave()
    saved = bridge.storage.get_record(bridge.record.uid)
    assert saved.status == "saved" and saved.definition_en == "My own English explanation."
    assert saved.context.explanation_ru


def test_card_plus_saves_without_opening_preview_and_reuses_saved_edits(bridge):
    bridge.gemini = Provider()
    previews = []
    bridge.previewReady.connect(lambda: previews.append(True))
    bridge.lookup('experience', 'You experience it.')
    bridge.addWord()
    await_idle(bridge)
    saved = bridge.storage.get_record(bridge.record.uid)
    assert saved.status == 'saved' and saved.complete
    assert bridge.card['saved'] and not bridge.card['saved_to_anki']
    assert not previews
    saved.definition_en = 'My edited definition.'
    bridge.storage.save_record(saved)
    class NoMoreRequests:
        def generate(self, *args):
            raise AssertionError('Saved enrichment must be reused')
    bridge.gemini = NoMoreRequests()
    bridge.lookup('experience', 'You experience it.')
    assert bridge.card['saved']
    bridge.addWord()
    await_idle(bridge)
    assert bridge.record.definition_en == 'My edited definition.'
    assert len(bridge.storage.records()) == 1 and not previews


@pytest.mark.parametrize('automatic', [False, True])
def test_save_sends_all_dictionary_senses_independently_of_selected_sense(bridge, automatic):
    from golyah.anki import note_fields
    from golyah.models import Entry, Example, Sense
    entries = [Entry(word='light', pos='n', dictionary='Test', senses=[
        Sense(translation='свет', definition_en='Visible radiation.', examples=[
            Example(en='Bright light.', ru='Яркий свет.')]),
        Sense(translation='лампа', definition_en='A lamp.', examples=[
            Example(en='Turn on the light.', ru='Включи лампу.')])]),
        Entry(word='light', pos='adj', dictionary='Test', senses=[Sense(translation='лёгкий',
            definition_en='Not heavy.', examples=[Example(en='A light bag.', ru='Лёгкая сумка.')])])]
    class Dictionary:
        def lookup(self, term): return entries
        def list(self): return []
    exported = []
    class Anki:
        def add(self, record, deck):
            assert deck == 'Vocabulary'
            exported.append(note_fields(record))
            return 123
    bridge.dictionary = Dictionary()
    bridge.gemini = Provider()
    bridge.anki = Anki()
    bridge._settings['deck'] = 'Vocabulary'
    bridge.lookup('light', 'Turn on the light.')
    bridge.selectSense(1, 0)
    if automatic:
        bridge.addWord()
    else:
        bridge.prepareSave('anki')
    await_idle(bridge)
    if not automatic:
        assert bridge.record.status == 'preview'
        assert bridge.confirmSave()
        await_idle(bridge)
    assert len(exported) == 1
    saved = bridge.storage.get_record(bridge.record.uid)
    assert saved.status == 'saved' and saved.complete
    assert saved.translation == bridge.record.translation
    for value in ('свет', 'лампа', 'лёгкий'):
        assert value in saved.translation and value in exported[0]['Translation']
    for value in ('Bright light.', 'Turn on the light.', 'A light bag.'):
        assert value in [example.en for example in saved.examples]
        assert value in exported[0]['Examples']
    assert 'Visible radiation.' in exported[0]['DictionaryDefinitionEN']
    assert 'A lamp.' in exported[0]['DictionaryDefinitionEN']
    assert 'Not heavy.' in exported[0]['DictionaryDefinitionEN']


def test_word_absent_from_dictionary_is_filled_by_llm_and_sent_to_anki(bridge):
    from golyah.anki import note_fields
    from golyah.models import Example
    calls, exported = [], []
    class Translator:
        def generate(self, record, mode, cancel):
            calls.append((record.term, mode))
            assert not record.entries
            return Explanation(definition_en='A made-up test word.', usage_en='Used in a test.',
                translation_ru='тестовое слово', examples=[
                    Example(en='A test word.', ru='Тестовое слово.')]), 'test-model'
    class Anki:
        def add(self, record, deck):
            exported.append(note_fields(record))
            return 123
    bridge.gemini = Translator()
    bridge.anki = Anki()
    bridge._settings['deck'] = 'Vocabulary'
    bridge.lookup('zzgolyahmissing', '')
    bridge.addWord()
    await_idle(bridge)
    assert calls == [('zzgolyahmissing', 'explain')]
    assert bridge.record.status == 'saved'
    assert exported[0]['Translation'] == 'тестовое слово'
    assert exported[0]['DefinitionEN'] == 'A made-up test word.'
    assert 'A test word.' in exported[0]['Examples'] and 'Тестовое слово.' in exported[0]['Examples']


@pytest.mark.parametrize('fail', [False, True])
def test_card_plus_also_sends_to_configured_anki_and_keeps_local_record(bridge, fail):
    calls = []
    class Anki:
        def add(self, record, deck):
            calls.append((record.uid, deck))
            assert record.complete
            if fail:
                raise RuntimeError('Anki closed')
            return 321
    bridge.gemini = Provider()
    bridge.anki = Anki()
    bridge._settings['deck'] = 'Vocabulary'
    bridge.lookup('experience', 'You experience it.')
    bridge.addWord()
    await_idle(bridge)
    saved = bridge.storage.get_record(bridge.record.uid)
    assert calls == [(saved.uid, 'Vocabulary')]
    assert saved.complete and saved.destination == 'anki'
    assert saved.status == ('pending_anki' if fail else 'saved')
    assert saved.error == ('Anki closed' if fail else '')
    assert bridge.card['saved_to_anki'] == (not fail)
    assert len(bridge.storage.records()) == 1


def test_anki_deck_choice_saves_immediately_and_can_disable_sending(bridge):
    bridge._settings['decks'] = ['Default', 'English']
    bridge.selectAnkiDeck('English')
    assert bridge.settings['deck'] == bridge.storage.setting('anki_deck') == 'English'
    bridge.selectAnkiDeck('missing')
    assert bridge.settings['deck'] == 'English'
    bridge.selectAnkiDeck('')
    assert bridge.settings['deck'] == bridge.storage.setting('anki_deck') == ''


def test_anki_connect_does_not_choose_an_arbitrary_deck(bridge):
    class Anki:
        def connect(self): return ['Default', 'English']
        def ensure_model(self): pass
    bridge.anki = Anki()
    bridge.checkAnki()
    await_idle(bridge)
    assert bridge.settings['decks'] == ['Default', 'English']
    assert bridge.settings['deck'] == ''
    assert 'Выберите колоду' in bridge.status


def test_card_plus_cancel_does_not_send_or_replace_new_selection(bridge):
    started, release = threading.Event(), threading.Event()
    class Slow(Provider):
        def generate(self, *args):
            started.set()
            release.wait(2)
            return super().generate(*args)
    class NoAnki:
        def add(self, *args):
            raise AssertionError('Cancelled saving must not send to Anki')
    bridge.gemini = Slow()
    bridge.anki = NoAnki()
    bridge._settings['deck'] = 'Vocabulary'
    bridge.lookup('experience', 'You experience it.')
    uid = bridge.record.uid
    bridge.addWord()
    assert started.wait(2)
    bridge.lookup('quick', 'A quick look.')
    release.set()
    QTest.qWait(150)
    assert bridge.record.term == 'quick'
    assert bridge.storage.get_record(uid).status == 'draft'


def test_failed_enrichment_leaves_restorable_draft(bridge):
    class Failing:
        def generate(self, *args):
            raise RuntimeError("offline")
    bridge.gemini = Failing()
    bridge.lookup("experience", "You experience it.")
    bridge.prepareSave("anki")
    await_idle(bridge)
    saved = bridge.storage.get_record(bridge.record.uid)
    assert saved.status == "draft" and saved.destination == "anki" and saved.error == "offline"
    bridge.loadRecord(saved.uid)
    bridge.gemini = Provider()
    bridge.prepareSave("dictionary")
    await_idle(bridge)
    assert bridge.record.complete


def test_repeated_save_preserves_existing_manual_translation(bridge):
    bridge.gemini = Provider()
    bridge.lookup('experience', 'You experience it.')
    bridge.prepareSave('dictionary')
    await_idle(bridge)
    bridge.updatePreview('{"translation":"мой перевод"}')
    assert bridge.confirmSave()
    class NoMoreRequests:
        def generate(self, *args):
            raise AssertionError('Existing enrichment must be reused')
    bridge.gemini = NoMoreRequests()
    bridge.lookup('experience', 'You experience it.')
    bridge.prepareSave('dictionary')
    await_idle(bridge)
    assert bridge.record.complete and bridge.record.translation == 'мой перевод'


def test_stale_llm_result_cannot_change_new_selection(bridge):
    started, release = threading.Event(), threading.Event()
    class Slow(Provider):
        def generate(self, *args):
            started.set()
            release.wait(2)
            return super().generate(*args)
    bridge.gemini = Slow()
    bridge.lookup("experience", "You experience it.")
    bridge.requestLLM("explain")
    assert started.wait(2)
    bridge.lookup("quick", "A quick look.")
    release.set()
    QTest.qWait(100)
    assert bridge.record.term == "quick" and bridge.record.explain is None


@pytest.mark.parametrize("mode", ["explain", "context", "both"])
def test_llm_deadline_unlocks_card_and_discards_late_result(bridge, mode):
    started, release = threading.Event(), threading.Event()
    class Stalled(Provider):
        def generate(self, *args):
            started.set()
            release.wait(3)
            result, _ = super().generate(*args)
            return result, "late-model"
    bridge.gemini = Stalled()
    bridge.lookup("experience it", "You experience it.")
    bridge._llm_timer.setInterval(30)
    try:
        bridge.requestLLM(mode)
        assert started.wait(2)
        await_idle(bridge)
        assert "не ответила вовремя" in bridge.status
        assert bridge._cancel.is_set() and not bridge._llm_timer.isActive()
        assert bridge.record.explain is None and bridge.record.context is None
        bridge.gemini = Provider()
        bridge._llm_timer.setInterval(1000)
        bridge.requestLLM(mode)
        await_idle(bridge)
        assert bridge.record.llm_model == "test-model"
        assert not bridge._llm_timer.isActive()
        release.set()
        QTest.qWait(100)
        assert bridge.record.llm_model == "test-model"
        assert not bridge.busy
    finally:
        release.set()


def test_save_deadline_keeps_draft_and_late_result_cannot_overwrite_retry(bridge):
    started, release = threading.Event(), threading.Event()
    class Stalled(Provider):
        def generate(self, *args):
            started.set()
            release.wait(3)
            return super().generate(*args)
    sent = []
    class Anki:
        def add(self, record, deck):
            sent.append(record.uid)
            return 123
    bridge.gemini = Stalled()
    bridge.anki = Anki()
    bridge._settings['deck'] = 'Vocabulary'
    bridge.lookup("experience it", "You experience it.")
    bridge._llm_timer.setInterval(30)
    try:
        bridge.addWord()
        assert started.wait(2)
        await_idle(bridge)
        draft = bridge.storage.get_record(bridge.record.uid)
        assert draft.status == "draft" and "не ответила вовремя" in draft.error
        assert sent == []
        bridge.gemini = Provider()
        bridge._llm_timer.setInterval(1000)
        bridge.addWord()
        await_idle(bridge)
        assert sent == [bridge.record.uid]
        release.set()
        QTest.qWait(100)
        saved = bridge.storage.get_record(bridge.record.uid)
        assert saved.status == "saved" and not saved.error and saved.complete
    finally:
        release.set()


def test_old_llm_completion_does_not_stop_new_request_deadline(bridge):
    releases = [threading.Event(),threading.Event()]
    started = [threading.Event(),threading.Event()]
    class Stalled(Provider):
        def __init__(self,index): self.index=index
        def generate(self,*args):
            started[self.index].set()
            releases[self.index].wait(3)
            return super().generate(*args)
    bridge.lookup('experience it','You experience it.')
    try:
        bridge.gemini=Stalled(0)
        bridge._llm_timer.setInterval(30)
        bridge.requestLLM('explain')
        assert started[0].wait(2)
        await_idle(bridge)
        bridge.gemini=Stalled(1)
        bridge._llm_timer.setInterval(150)
        bridge.requestLLM('explain')
        assert started[1].wait(2)
        releases[0].set()
        QTest.qWait(60)
        assert bridge.busy and bridge._llm_timer.isActive()
        await_idle(bridge)
        assert 'не ответила вовремя' in bridge.status
        assert bridge.record.explain is None
    finally:
        for release in releases: release.set()


def test_http_timeout_reenables_actions_and_has_readable_error(bridge):
    from httpx import ReadTimeout
    class Failing:
        def generate(self, *args):
            raise ReadTimeout("transport details")
    bridge.gemini = Failing()
    bridge.lookup("experience it", "You experience it.")
    bridge.requestLLM("explain")
    await_idle(bridge)
    assert "ожидания" in bridge.status and "повторите" in bridge.status.casefold()
    assert "transport details" not in bridge.status
    assert not bridge._llm_timer.isActive()


@pytest.mark.parametrize("code, expected", [(400, "отклонила запрос"), (401, "API-ключ"),
    (403, "API-ключ"), (404, "модель"), (500, "временно недоступен"), (503, "временно недоступен")])
def test_gemini_api_failure_is_readable_and_unlocks_card(bridge, code, expected):
    from google.genai.errors import APIError
    class Failing:
        def generate(self, *args):
            raise APIError(code, {"error": {"message": "technical request details"}})
    bridge.gemini = Failing()
    bridge.lookup("The image is there again", "...The image is there again.")
    bridge.requestLLM("explain")
    await_idle(bridge)
    assert expected in bridge.status
    assert "technical request details" not in bridge.status
    assert bridge.record.explain is None and not bridge._llm_timer.isActive()


def test_anki_failure_retains_prepared_record(bridge):
    class FailingAnki:
        def add(self, record, deck):
            raise RuntimeError("Anki closed")
    bridge.gemini = Provider()
    bridge.anki = FailingAnki()
    bridge.lookup("experience", "You experience it.")
    bridge.prepareSave("anki")
    await_idle(bridge)
    assert bridge.confirmSave()
    await_idle(bridge)
    record = bridge.storage.get_record(bridge.record.uid)
    assert record.status == "pending_anki" and record.complete
    assert record.error == "Anki closed"


def test_cancelled_save_is_draft_even_when_provider_ignores_cancellation(bridge):
    # Orchestration must also reject providers that return after cancellation.
    class Slow(Provider):
        def generate(self, record, mode, cancel):
            time.sleep(.1)
            return super().generate(record, mode, cancel)
    bridge.gemini = Slow()
    bridge.lookup("experience", "You experience it.")
    bridge.prepareSave("dictionary")
    uid = bridge.record.uid
    bridge.cancel()
    QTest.qWait(200)
    assert bridge.storage.get_record(uid).status == "draft"


@pytest.mark.parametrize('old', ['Ctrl+Alt+Q', 'Ctrl+Shift+F8'])
def test_requested_alt_q_migration_runs_once(app, tmp_path, old):
    storage = Storage(tmp_path/'migration.sqlite')
    storage.set_setting('hotkey', old)
    storage.set_setting('capture_mode', 'region')
    value = Bridge(storage)
    try:
        assert value.settings['hotkey'] == 'Alt+Q'
        assert value.settings['captureMode'] == 'monitor'
        # A later explicit choice must survive future launches.
        storage.set_setting('hotkey', 'Ctrl+Alt+Q')
        second = Bridge(storage)
        try:
            assert second.settings['hotkey'] == 'Ctrl+Alt+Q'
        finally:
            second.close()
    finally:
        value.close()


def test_window_target_is_chosen_before_interface_hides(bridge, monkeypatch):
    from golyah.windows import CaptureTarget
    import golyah.bridge as module
    timeline = []
    target = CaptureTarget('window', 1, 20, 30, 800, 600, 123, 'Reader')
    monkeypatch.setattr(module, 'foreground_window', lambda: 123)
    monkeypatch.setattr(module, 'window_is_ours', lambda hwnd: False)
    def identify(mode, source_id):
        assert source_id == '42:123'
        timeline.append('target')
        return target
    monkeypatch.setattr(module, 'selected_target', identify)
    bridge._settings['captureMode'] = 'window'
    bridge._settings['windowId'] = '42:123'
    bridge.captureRequested.connect(lambda: timeline.append('hide'))
    bridge.requestCapture()
    assert timeline == ['target', 'hide'] and bridge._requested_target is target


def test_closed_capture_ignores_previous_frame(bridge, monkeypatch):
    import numpy as np
    import golyah.bridge as module
    from golyah.windows import CaptureTarget
    monkeypatch.setattr(module, 'foreground_window', lambda: 123)
    monkeypatch.setattr(module, 'window_is_ours', lambda hwnd: False)
    monkeypatch.setattr(module, 'selected_target', lambda mode, source_id: CaptureTarget('monitor', 1, 0, 0, 100, 100))
    bridge._settings['screenId'] = 'display'
    requests = []
    bridge.task = lambda function, done: requests.append(done)
    bridge.requestCapture(); bridge.startCapture()
    bridge.requestCapture()
    assert len(requests)==1, 'An ongoing capture cannot be restarted'
    bridge.closeOverlay()
    bridge.requestCapture(); bridge.startCapture()
    requests[0](np.zeros((100,100,4), dtype='uint8'), None)
    assert bridge._image is None and not bridge.overlay['visible']
    failures = []
    bridge.captureFailed.connect(lambda: failures.append(bridge.status))
    requests[1](None, RuntimeError('Capture unavailable'))
    assert failures == ['Capture unavailable'] and not bridge.busy


@pytest.mark.parametrize('phase',['delay','capture','recognizing','ready'])
def test_repeat_capture_and_empty_hotkey_leave_current_capture_unchanged(bridge,monkeypatch,phase):
    from PySide6.QtCore import QPoint
    import golyah.bridge as module
    from golyah.windows import CaptureTarget
    selected=[]; requested=[]; tasks=[]
    point=[QPoint(100,100)]
    monkeypatch.setattr(module,'QCursor',type('Cursor',(),{'pos':staticmethod(lambda:point[0])}))
    monkeypatch.setattr(module,'foreground_window',lambda:123)
    monkeypatch.setattr(module,'window_is_ours',lambda hwnd:False)
    def identify(*args):
        selected.append(args)
        return CaptureTarget('monitor',1,0,0,800,500)
    monkeypatch.setattr(module,'selected_target',identify)
    bridge._settings['screenId']='display'
    bridge.captureRequested.connect(lambda:requested.append(True))
    bridge.task=lambda function,done:tasks.append(done)
    bridge.requestHotkeyCapture()
    if phase!='delay':bridge.startCapture()
    if phase in ('recognizing','ready'):
        bridge._capture_starting=False
        bridge._overlay.update(visible=True,stage=phase)
    generation=bridge._generation
    point[0]=QPoint(400,300)
    for _ in range(5):
        bridge.requestHotkeyCapture();bridge.requestCapture()
    assert len(selected)==len(requested)==1
    assert len(tasks)==(0 if phase=='delay' else 1)
    assert bridge._generation==generation and bridge._capture_cursor==QPoint(100,100)


@pytest.mark.parametrize('scale', [1, 1.25, 1.5, 2])
def test_active_overlay_hotkey_selects_current_word_without_capture(bridge, monkeypatch, scale):
    from PySide6.QtCore import QPoint
    import golyah.bridge as module
    current = [QPoint(-600 + round(210 / scale), -200 + round(215 / scale))]
    monkeypatch.setattr(module, 'QCursor', type('Cursor', (), {'pos': staticmethod(lambda: current[0])}))
    monkeypatch.setattr(module, 'selected_target', lambda *args: pytest.fail('An active overlay must not capture again'))
    requested = []
    bridge.captureRequested.connect(lambda: requested.append(True))
    worker, ocr_id = bridge._worker, bridge._ocr_id
    bridge._overlay.update(visible=True, stage='ready', left=-600, top=-200,
                          width=800 / scale, height=500 / scale, pixelWidth=800, pixelHeight=500)
    bridge.set_ocr_words([
        {'id': i, 'text': text, 'polygon': [[x,200],[x+65,200],[x+65,230],[x,230]],
         'confidence': 1, 'line': 0, 'block': 0}
        for i, (text, x) in enumerate([('A',100), ('quick',180), ('look.',260)])])
    bridge.requestHotkeyCapture()
    assert bridge.record.term == 'quick' and bridge.record.sentence == 'A quick look.'
    assert bridge.overlay['selected'] == [1] and bridge.record.selected_positions == [[2,7]]
    current[0] = QPoint(-600 + round(290 / scale), -200 + round(215 / scale))
    bridge.requestHotkeyCapture()
    assert bridge.record.term == 'look' and bridge.overlay['selected'] == [2]
    assert (bridge.overlay['anchorX'], bridge.overlay['anchorY']) == (current[0].x(), current[0].y())
    assert bridge._worker is worker and bridge._ocr_id == ocr_id and not requested
    assert bridge.overlay['visible'] and not bridge.overlay['multiSelect']
    # Empty space and the capture button preserve the existing card and frame.
    current[0] = QPoint(1900,1000)
    bridge.requestHotkeyCapture()
    bridge.requestCapture()
    assert bridge.record.term == 'look' and bridge.overlay['selected'] == [2] and not requested
    bridge._overlay['stage'] = 'recognizing'
    current[0] = QPoint(-600 + round(210 / scale), -200 + round(215 / scale))
    bridge.requestHotkeyCapture()
    assert bridge.record.term == 'look' and bridge._ocr_id == ocr_id and not requested


@pytest.mark.parametrize('end',['cancel','failure'])
def test_cancel_or_failure_releases_capture_and_discards_delayed_start(bridge,monkeypatch,end):
    import golyah.bridge as module
    from golyah.windows import CaptureTarget
    monkeypatch.setattr(module,'foreground_window',lambda:123)
    monkeypatch.setattr(module,'window_is_ours',lambda hwnd:False)
    monkeypatch.setattr(module,'selected_target',lambda *args:CaptureTarget('monitor',1,0,0,800,500))
    bridge._settings['screenId']='display'
    requested=[];bridge.captureRequested.connect(lambda:requested.append(True))
    bridge.requestHotkeyCapture()
    if end=='cancel':bridge.cancel()
    else:bridge.captureFailed.emit()
    assert not bridge._capture_starting and bridge._capture_cursor is None
    bridge.startCapture()
    assert len(requested)==1, 'A stale delay timer cannot start another capture'
    bridge.requestHotkeyCapture()
    assert len(requested)==2


@pytest.mark.parametrize('scale', [1, 1.25, 1.5, 2])
def test_selection_hotkey_toggles_words_in_shared_selection(bridge, monkeypatch, scale):
    from PySide6.QtCore import QPoint
    import golyah.bridge as module
    point = [QPoint(-600 + round(210 / scale), -200 + round(215 / scale))]
    monkeypatch.setattr(module, 'QCursor', type('Cursor', (), {'pos': staticmethod(lambda: point[0])}))
    bridge._overlay.update(visible=True, stage='ready', left=-600, top=-200,
                          width=800 / scale, height=500 / scale, pixelWidth=800, pixelHeight=500)
    bridge.set_ocr_words([
        {'id': i, 'text': text, 'polygon': [[x,200],[x+65,200],[x+65,230],[x,230]],
         'confidence': 1, 'line': 0, 'block': 0}
        for i, (text,x) in enumerate([('A',100), ('quick',180), ('look.',260)])])
    cards, captures = [], []
    bridge.cardChanged.connect(lambda: cards.append(True))
    bridge.captureRequested.connect(lambda: captures.append(True))
    worker, ocr_id = bridge._worker, bridge._ocr_id
    bridge.requestHotkeyCapture()
    assert bridge.overlay['selected'] == [1] and not bridge.overlay['multiSelect'] and cards
    assert bridge.record.term == 'quick'
    bridge.chooseWord(2, True)
    assert bridge.overlay['selected'] == [1,2]
    assert bridge.record.term == 'quick look'
    bridge.requestHotkeySelection()
    assert bridge.overlay['selected'] == [2] and bridge.record.term == 'look'
    bridge.requestHotkeySelection()
    assert bridge.overlay['selected'] == [2,1]
    assert not captures and bridge._worker is worker and bridge._ocr_id == ocr_id
    assert bridge.record.term == 'quick look' and bridge.record.selected_positions == [[2,7],[8,13]]
    bridge.chooseWord(0, True)
    assert bridge.record.term == 'A quick look' and bridge.overlay['multiSelect']
    bridge.chooseWord(0, True)
    assert bridge.record.term == 'quick look'
    bridge.requestHotkeySelection()
    point[0] = QPoint(-600 + round(290 / scale), -200 + round(215 / scale))
    bridge.requestHotkeySelection()
    assert not bridge.record.term and not bridge.overlay['selected'] and bridge.overlay['visible']
    bridge.requestHotkeySelection()
    assert bridge.record.term == 'look' and bridge.overlay['selected'] == [2]
    assert not captures and bridge._ocr_id == ocr_id


def range_words(bridge):
    bridge._overlay.update(visible=True, stage='ready')
    bridge.set_ocr_words([
        {'id': identity, 'text': text, 'polygon': [[x,y],[x+65,y],[x+65,y+30],[x,y+30]],
         'confidence': 1, 'line': line, 'block': 0}
        for identity, text, x, y, line in [
            (90, 'Something', 80, 160, 0), (5, 'may', 180, 160, 0),
            (20, 'appear', 270, 160, 0), (7, 'on', 80, 205, 1), (30, 'TV.', 180, 205, 1)]])


@pytest.mark.parametrize('start,end,expected', [
    (90, 30, [90,5,20,7,30]), (30, 90, [90,5,20,7,30]),
    (5, 7, [5,20,7]), (7, 5, [5,20,7]), (20, 20, [20])])
def test_range_selection_follows_reading_order_across_wrapped_lines(bridge, start, end, expected):
    range_words(bridge)
    bridge.chooseWord(start, False)
    bridge.chooseRange(end, False)
    assert bridge.overlay['selected'] == expected and bridge.overlay['multiSelect']
    assert bridge.record.sentence == 'Something may appear on TV.'
    assert len(bridge.record.selected_positions) == len(expected)
    assert '…' not in bridge.record.selection_preview
    if len(expected) == 5:
        assert bridge.record.term == 'Something may appear on TV'


def test_range_anchor_stays_fixed_and_ctrl_shift_can_add_another_range(bridge):
    range_words(bridge)
    bridge.chooseWord(90, False)
    bridge.chooseRange(30, False)
    bridge.chooseRange(20, False)
    assert bridge.overlay['selected'] == [90,5,20]
    bridge.chooseWord(7, True)
    bridge.chooseRange(30, True)
    assert bridge.overlay['selected'] == [90,5,20,7,30]
    bridge.chooseWord(5, False)
    bridge.chooseRange(20, False)
    assert bridge.overlay['selected'] == [5,20]


@pytest.mark.parametrize('reset', ['clear', 'frame'])
def test_range_does_not_reuse_an_anchor_from_an_old_selection(bridge, reset):
    range_words(bridge)
    bridge.chooseWord(90, False)
    if reset == 'clear':
        bridge.clearSelection()
    else:
        range_words(bridge)
    bridge.chooseRange(30, False)
    assert bridge.overlay['selected'] == [30]
    bridge.chooseRange(999, False)
    assert bridge.overlay['selected'] == [30]


@pytest.mark.parametrize('state', ['closed','recognizing','starting','empty','closing'])
def test_selection_hotkey_ignores_unavailable_words(bridge, monkeypatch, state):
    from PySide6.QtCore import QPoint
    import golyah.bridge as module
    monkeypatch.setattr(module, 'QCursor', type('Cursor', (), {'pos': staticmethod(lambda: QPoint(500,100))}))
    captures = []
    bridge.captureRequested.connect(lambda: captures.append(True))
    bridge._overlay.update(visible=state != 'closed', stage='recognizing' if state == 'recognizing' else 'ready')
    bridge._capture_starting = state == 'starting'
    bridge._closing = state == 'closing'
    generation = bridge._generation
    bridge.requestHotkeySelection()
    assert not bridge.overlay['selected'] and not bridge.record.term and not captures
    assert bridge._generation == generation


def test_selection_chord_as_primary_still_captures_when_closed(bridge, monkeypatch):
    from PySide6.QtCore import QPoint
    import golyah.bridge as module
    from golyah.windows import CaptureTarget
    monkeypatch.setattr(module, 'QCursor', type('Cursor', (), {'pos': staticmethod(lambda: QPoint(210,215))}))
    monkeypatch.setattr(module, 'foreground_window', lambda: 123)
    monkeypatch.setattr(module, 'window_is_ours', lambda hwnd: False)
    monkeypatch.setattr(module, 'selected_target', lambda *args: CaptureTarget('monitor',1,0,0,800,500))
    bridge._settings['screenId'] = 'display'
    bridge.hotkey.selection_is_primary = True
    requested = []
    bridge.captureRequested.connect(lambda: requested.append(True))
    bridge.requestHotkeySelection()
    assert requested == [True] and bridge._capture_cursor == QPoint(210,215)
    bridge.requestHotkeySelection()
    assert requested == [True], 'Starting capture cannot be restarted'


def test_ocr_request_uses_memory_instead_of_file(bridge, tmp_path):
    import json
    import numpy as np
    from multiprocessing.shared_memory import SharedMemory
    from PySide6.QtCore import QProcess
    class Worker:
        payload = b''
        def state(self): return QProcess.ProcessState.Running
        def write(self, data): self.payload = data
        def kill(self): pass
        def waitForFinished(self, timeout): return True
    worker = Worker()
    bridge._worker = worker
    expected=np.arange(20*40*4,dtype=np.uint8).reshape(20,40,4)
    bridge._image = expected.copy()
    bridge._run_ocr()
    payload = json.loads(worker.payload)
    assert 'path' not in payload
    assert payload['engine']=='auto'
    mapping=SharedMemory(name=payload['memory'])
    try:
        frame=np.ndarray(tuple(payload['shape']),dtype=np.uint8,buffer=mapping.buf)
        assert frame.shape==(20,40,4) and np.array_equal(frame,expected)
        del frame
    finally:
        mapping.close()
    assert bridge._image is None and 'image' not in payload
    assert not list(tmp_path.rglob('*.png'))


def test_cancelled_ocr_retains_models_and_only_queues_latest_frame(bridge):
    import json
    import numpy as np
    from PySide6.QtCore import QProcess
    class Worker:
        sent = []
        incoming = b''
        def state(self): return QProcess.ProcessState.Running
        def write(self, data): self.sent.append(json.loads(data))
        def readAllStandardOutput(self):
            data, self.incoming = self.incoming, b''
            return data
        def kill(self): pass
        def waitForFinished(self, timeout): return True
    worker = Worker(); bridge._worker = worker
    def request():
        bridge._image = np.full((10,20,4), 255, dtype='uint8'); bridge._run_ocr()
    request(); first = worker.sent[0]['id']
    bridge.cancel(); request(); second = bridge._ocr_id
    bridge.cancel(); request(); last = bridge._ocr_id
    assert len(worker.sent) == 1
    worker.incoming = ('GOLYAH_JSON:' + json.dumps({'id':first,'result':{'words':[], 'seconds':.5}})+'\n').encode()
    bridge._read_worker()
    assert [r['id'] for r in worker.sent] == [first, last]
    assert second not in bridge._ocr_pending and bridge._ocr_inflight == last
    assert list(bridge._ocr_memory)==[last], 'Cancelled queued frames and completed frames must release mappings'


def test_background_task_callback_runs_on_gui_thread(bridge):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    received = []
    gui_thread = threading.get_ident()
    def done(value, error):
        received.append((value, threading.get_ident(), error))
        loop.quit()
    bridge.task(threading.get_ident, done)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    assert received and received[0][0] != gui_thread
    assert received[0][1] == gui_thread and received[0][2] is None


def test_ocr_engine_choice_is_saved_and_cancels_the_previous_result(bridge):
    bridge._ocr_pending={7:True}
    bridge.selectOCREngine('windows')
    assert bridge.settings['ocrEngine']=='windows'
    assert bridge.storage.setting('ocr_engine')=='windows'
    assert not bridge._ocr_pending
    bridge.selectOCREngine('unknown')
    assert bridge.settings['ocrEngine']=='windows'


def test_source_selection_survives_reordering_and_missing_window(bridge, monkeypatch):
    import golyah.bridge as module
    first = [{'id':'7:80', 'label':'Reader'}, {'id':'8:90', 'label':'Browser'}]
    screens = [{'id':'display-b', 'primary':False}, {'id':'display-a', 'primary':True}]
    monkeypatch.setattr(module, 'window_sources', lambda: first)
    monkeypatch.setattr(module, 'screen_sources', lambda: screens)
    bridge.refreshCaptureSources()
    assert bridge.settings['screenId'] == 'display-a'
    bridge.selectCaptureSource('window', '7:80')
    first.reverse(); screens.reverse()
    bridge.refreshCaptureSources()
    assert bridge.settings['windowId'] == '7:80'
    first[:] = [{'id':'8:90', 'label':'Browser'}]
    bridge.refreshCaptureSources()
    assert bridge.settings['windowId'] == '7:80', 'Never silently capture a different window'
    def unavailable(*args): raise ValueError('Window closed')
    monkeypatch.setattr(module, 'selected_target', unavailable)
    bridge.requestCapture()
    assert bridge.status == 'Window closed' and not bridge.overlay['visible']


def test_restored_window_geometry_is_refreshed_before_reading_pixels(bridge, monkeypatch):
    import golyah.bridge as module
    from golyah.windows import CaptureTarget
    bridge._settings.update(captureMode='window', windowId='77:123')
    old = CaptureTarget('window', 1, 0, 0, 300, 200, 123)
    restored = CaptureTarget('window', 1, 40, 80, 800, 600, 123)
    bridge._requested_target = old
    monkeypatch.setattr(module, 'selected_target', lambda mode, source: restored if source == '77:123' else None)
    targets = []
    monkeypatch.setattr(module, 'capture', lambda target: targets.append(target))
    bridge.task = lambda function, done: function()
    bridge.startCapture()
    assert targets == [restored] and bridge._capture_target is restored


@pytest.mark.parametrize('scale', [1, 1.25, 1.5, 2])
def test_hotkey_opens_original_cursor_word_after_ocr(bridge, monkeypatch, scale):
    import json
    from PySide6.QtCore import QPoint
    import golyah.bridge as module
    from golyah.windows import CaptureTarget
    point=QPoint(-600+round(210/scale),-200+round(215/scale))
    current=[point]
    monkeypatch.setattr(module,'QCursor',type('Cursor',(),{'pos':staticmethod(lambda:current[0])}))
    monkeypatch.setattr(module,'foreground_window',lambda:123)
    monkeypatch.setattr(module,'window_is_ours',lambda hwnd:False)
    monkeypatch.setattr(module,'selected_target',lambda *args:CaptureTarget('monitor',1,-1200,-400,800,500))
    bridge._settings['screenId']='display'
    bridge.requestHotkeyCapture()
    current[0]=QPoint(1900,1000)  # Moving during recognition must not change the chosen word.
    bridge._overlay.update(visible=True,left=-600,top=-200,width=800/scale,height=500/scale,
                          pixelWidth=800,pixelHeight=500,stage='recognizing')
    words=[{'id':i,'text':text,'polygon':[[x,200],[x+65,200],[x+65,230],[x,230]],
            'confidence':1,'line':0,'block':0}
           for i,(text,x) in enumerate([('A',100),('quick',180),('look.',260)])]
    class Worker:
        data=('GOLYAH_JSON:'+json.dumps({'id':7,'result':{'words':words,'seconds':.02}})+'\n').encode()
        def readAllStandardOutput(self):
            value,self.data=self.data,b'';return value
        def kill(self):pass
        def waitForFinished(self,timeout):return True
    bridge._worker=Worker();bridge._ocr_pending={7:True}
    bridge._read_worker()
    assert bridge.record.term=='quick' and bridge.record.sentence=='A quick look.'
    assert bridge.record.selected_positions==[[2,7]] and bridge.overlay['selected']==[1]
    assert (bridge.overlay['anchorX'],bridge.overlay['anchorY'])==(point.x(),point.y())
    assert bridge._capture_cursor is None, 'Auto-open is consumed once for this capture'


@pytest.mark.parametrize('mode',['button','empty','cancelled','stale'])
def test_auto_open_requires_a_current_hotkey_and_a_word(bridge,monkeypatch,mode):
    import json
    from PySide6.QtCore import QPoint
    import golyah.bridge as module
    from golyah.windows import CaptureTarget
    monkeypatch.setattr(module,'QCursor',type('Cursor',(),{'pos':staticmethod(lambda:QPoint(500,100) if mode=='empty' else QPoint(210,215))}))
    monkeypatch.setattr(module,'foreground_window',lambda:123)
    monkeypatch.setattr(module,'window_is_ours',lambda hwnd:False)
    monkeypatch.setattr(module,'selected_target',lambda *args:CaptureTarget('monitor',1,0,0,800,500))
    bridge._settings['screenId']='display'
    if mode=='button':bridge.requestCapture()
    else:bridge.requestHotkeyCapture()
    bridge._overlay.update(visible=True,left=0,top=0,width=800,height=500,pixelWidth=800,pixelHeight=500)
    words=[{'id':0,'text':'quick','polygon':[[180,200],[245,200],[245,230],[180,230]],
            'confidence':1,'line':0,'block':0}]
    class Worker:
        data=('GOLYAH_JSON:'+json.dumps({'id':7,'result':{'words':words,'seconds':.02}})+'\n').encode()
        def readAllStandardOutput(self):
            value,self.data=self.data,b'';return value
        def kill(self):pass
        def waitForFinished(self,timeout):return True
    bridge._worker=Worker();bridge._ocr_pending={8 if mode=='stale' else 7:True}
    if mode=='cancelled':bridge.closeOverlay()
    bridge._read_worker()
    assert not bridge.record.term and not bridge.overlay['selected']
    if mode=='stale':assert not bridge.overlay['words'], 'The old result must not populate a newer capture'
