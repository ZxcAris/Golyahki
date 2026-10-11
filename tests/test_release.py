"""Release regressions: data migration, UI responsiveness and recoverable failures."""
import json
import sqlite3
import threading
import subprocess
import sys

import httpx
import numpy as np
import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from golyah.anki import AnkiService
from golyah.bridge import Bridge
from golyah.dictionaries import DictionaryService
from golyah.gemini import apply_result, ensure_enriched
from golyah.models import Entry, Example, Explanation, Sense, StudyRecord
from golyah.storage import Storage


def explained(term='word', sentence=''):
    return StudyRecord(term=term, sentence=sentence, translation='слово',
        definition_en='A word.', usage_en='Used in speech.',
        explain=Explanation(definition_en='A word.', usage_en='Used in speech.', translation_ru='слово'))


@pytest.fixture
def bridge(tmp_path):
    app = QApplication.instance() or QApplication([])
    value = Bridge(Storage(tmp_path / 'release.sqlite'))
    yield value
    value.close()


def test_summary_migration_preserves_legacy_records_and_missing_optional_fields(tmp_path):
    path = tmp_path / 'old.sqlite'
    old = explained()
    raw = old.model_dump_json()
    minimal = json.dumps({'term': 'legacy', 'translation': 'прежний'})
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE records(uid TEXT PRIMARY KEY,term TEXT,sentence TEXT,status TEXT,updated_at TEXT,data TEXT)')
        db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)', (old.uid, old.term, '', 'saved', old.updated_at, raw))
        db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)', ('legacy', 'legacy', '', 'draft', old.updated_at, minimal))
    storage = Storage(path)
    assert len(storage.records()) == 2
    assert storage.record_state(old.uid) == {'status': 'saved', 'complete': 1, 'has_anki': 0}
    assert storage.record_state('legacy') == {'status': 'draft', 'complete': 0, 'has_anki': 0}
    with storage.connect() as db:
        assert db.execute('SELECT data FROM records WHERE uid=?', (old.uid,)).fetchone()[0] == raw
    assert Storage(path).records() == storage.records()


def test_summary_stays_correct_after_old_style_writes_import_and_delete(tmp_path):
    storage = Storage(tmp_path / 'data.sqlite')
    item = explained()
    with storage.connect() as db:
        db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?)',
            (item.uid, item.term, '', 'draft', item.updated_at, item.model_dump_json()))
    assert storage.records()[0]['translation'] == 'слово'
    item.translation, item.error, item.anki_note_ids = 'обновлено', 'retry', {'reverse': 123}
    with storage.connect() as db:
        db.execute('UPDATE records SET status=?,data=? WHERE uid=?', ('pending_anki', item.model_dump_json(), item.uid))
    other = Storage(storage.path)
    assert other.records('обновлено', True)[0]['error'] == 'retry'
    assert other.record_state(item.uid)['has_anki'] == 1
    path = tmp_path / 'export.json'
    storage.export_records(path)
    storage.delete_record(item.uid)
    assert not storage.record_state(item.uid) and not storage.records()
    storage.import_records(path)
    assert storage.record_state(item.uid)['has_anki'] == 1


@pytest.mark.parametrize('sentence', ['', ' \t\r\n', '\u00a0\u2009\u3000'])
def test_summary_completeness_matches_model_whitespace_rules(tmp_path, sentence):
    storage = Storage(tmp_path / 'data.sqlite')
    item = explained(sentence=sentence)
    storage.save_record(item)
    assert bool(storage.record_state(item.uid)['complete']) == item.complete


def test_ui_reads_summary_and_builder_opens_only_one_complete_record(bridge, monkeypatch):
    item = explained()
    item.entries = [Entry(word='word', raw={'large': 'x' * 500000})]
    bridge.storage.save_record(item)
    bridge.record = item
    original = bridge.storage.get_record
    calls = []
    def read(uid):
        calls.append(uid)
        return original(uid)
    monkeypatch.setattr(bridge.storage, 'get_record', read)
    assert bridge.card['saved'] is False
    assert calls == []
    for index in range(10):
        bridge.storage.save_record(StudyRecord(term=f'draft {index}'))
    bridge.record = StudyRecord(term='')
    assert bridge._builder_record().uid == item.uid
    assert calls == [item.uid]


def test_atomic_export_failure_keeps_previous_backup(tmp_path, monkeypatch):
    import golyah.storage as module
    storage = Storage(tmp_path / 'data.sqlite')
    storage.save_record(explained())
    path = tmp_path / 'backup.json'
    path.write_text('previous backup', encoding='utf-8')
    def unavailable(*args):
        raise OSError('Disk unavailable')
    monkeypatch.setattr(module.os, 'replace', unavailable)
    with pytest.raises(OSError):
        storage.export_records(path)
    assert path.read_text(encoding='utf-8') == 'previous backup'
    assert not list(tmp_path.glob('*.tmp'))


def test_small_dictionary_import_cancellation_rolls_back_replacement(tmp_path):
    service = DictionaryService(Storage(tmp_path / 'data.sqlite'))
    path = tmp_path / 'dictionary.json'
    payload = {'schemaVersion': 1, 'kind': 'golyah-dictionary', 'name': 'Test',
               'entries': [{'word': 'original'}]}
    path.write_text(json.dumps(payload), encoding='utf-8')
    service.import_file(path)
    payload['entries'] = [{'word': 'replacement'}]
    path.write_text(json.dumps(payload), encoding='utf-8')
    def cancelled(count):
        if count:
            raise ValueError('Cancelled')
    with pytest.raises(ValueError, match='Cancelled'):
        service.import_file(path, cancelled)
    assert service.lookup('original') and not service.lookup('replacement')


@pytest.mark.parametrize('payload', [[], None, {}, {'schemaVersion': 1, 'kind': 'golyah-study', 'records': None}])
def test_invalid_personal_import_reports_format_error_without_changes(tmp_path, payload):
    storage = Storage(tmp_path / 'data.sqlite')
    storage.save_record(explained())
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError):
        storage.import_records(path)
    assert len(storage.records()) == 1


def test_anki_batch_reuses_connection_and_closes_after_error(monkeypatch):
    import golyah.anki as module
    from test_card_builder import Collection, word
    original, clients = httpx.Client, []
    def create(*args, **kwargs):
        value = original(*args, **kwargs)
        clients.append(value)
        return value
    monkeypatch.setattr(module.httpx, 'Client', create)
    collection = Collection()
    service = collection.service()
    collection.fail_once = 'addNote'
    record = word()
    with pytest.raises(RuntimeError):
        service.add(record, 'English')
    assert len(clients) == 1 and clients[0].is_closed
    service.add(record, 'English')
    assert len(clients) == 2 and all(client.is_closed for client in clients)
    assert len(collection.notes) == 1


def test_anki_request_timeout_uses_remaining_batch_budget(monkeypatch):
    import golyah.anki as module
    moment, timeouts = [0.0], []
    monkeypatch.setattr(module.time, 'monotonic', lambda: moment[0])
    def respond(request):
        action = json.loads(request.content)['action']
        timeouts.append(request.extensions['timeout']['read'])
        if action == 'version':
            moment[0] = 29.8
        return httpx.Response(200, json={'result': 6 if action == 'version' else ['English'], 'error': None})
    assert AnkiService(transport=httpx.MockTransport(respond)).connect() == ['English']
    assert timeouts[0] == 5.0 and 0 < timeouts[1] < .3


@pytest.mark.parametrize('version', [None, True, '6', 5])
def test_invalid_anki_version_has_clear_error(version):
    service = AnkiService(transport=httpx.MockTransport(lambda request:
        httpx.Response(200, json={'result': version, 'error': None})))
    with pytest.raises(RuntimeError, match='AnkiConnect'):
        service.connect()


@pytest.mark.parametrize('line', [b'{', b'null', b'{"id":true}', b'{"id":1,"result":{}}'])
def test_malformed_ocr_response_unlocks_ui_and_releases_frame(bridge, monkeypatch, line):
    bridge._ocr_pending = {1: True}
    bridge.message('OCR', True)
    monkeypatch.setattr(bridge._worker, 'readAllStandardOutput', lambda: b'GOLYAH_JSON:' + line + b'\n')
    bridge._read_worker()
    assert not bridge.busy and not bridge._ocr_pending and not bridge._ocr_memory
    assert 'некорректный ответ' in bridge.status


def test_shared_memory_failure_is_recoverable(bridge, monkeypatch):
    import golyah.bridge as module
    monkeypatch.setattr(bridge._worker, 'state', lambda: QProcess.ProcessState.Running)
    def unavailable(**kwargs):
        raise OSError('Out of memory')
    monkeypatch.setattr(module, 'SharedMemory', unavailable)
    bridge._image = np.zeros((20, 20, 4), dtype=np.uint8)
    bridge._run_ocr()
    assert not bridge.busy and not bridge._ocr_pending and bridge._image is None
    assert not bridge._ocr_memory and 'передать кадр' in bridge.status


def test_cancelled_complete_enrichment_never_runs_or_changes_record():
    item = explained()
    before = item.model_dump()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ValueError, match='отменён'):
        ensure_enriched(item, None, cancel)
    assert item.model_dump() == before


def test_duplicate_llm_examples_are_stored_once():
    item = StudyRecord(term='word')
    result = explained().explain
    result.examples = [Example(en='A word.', ru='Слово.'), Example(en='A word.', ru='Слово.')]
    apply_result(item, result, 'test')
    assert len(item.examples) == 1


def test_cold_ui_import_does_not_load_google_sdk():
    completed = subprocess.run([sys.executable, '-c',
        "import sys; import golyah.bridge; assert 'google.genai' not in sys.modules"],
        capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr


def test_cached_explanation_does_not_require_loading_sdk(tmp_path, monkeypatch):
    import hashlib
    from golyah import gemini
    storage = Storage(tmp_path / 'cache.sqlite')
    item = StudyRecord(term='word')
    model = 'gemini-2.5-flash'
    payload = gemini._payload(item)
    key = hashlib.sha256(json.dumps([gemini.PROMPT_VERSION, model, 'explain', payload],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    storage.cache_put(key, explained().explain.model_dump())
    def forbid_sdk():
        raise AssertionError('Cached data must not load the SDK')
    monkeypatch.setattr(gemini, '_load_sdk', forbid_sdk)
    service = gemini.GeminiService(storage)
    try:
        assert service.generate(item, 'explain')[0].translation_ru == 'слово'
    finally:
        service.close()


def test_release_version_matches_package_and_interface(bridge):
    from pathlib import Path
    import tomllib
    from golyah import __version__
    import importlib.metadata
    package = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text(encoding='utf-8'))
    assert bridge.version == __version__ == package['project']['version']
    assert importlib.metadata.version('golyah') == __version__


def test_unknown_word_keeps_all_llm_meanings_definitions_and_bilingual_examples():
    from golyah.anki import note_fields
    from golyah.gemini import _payload
    item = StudyRecord(term='light')
    result = Explanation(definition_en='A word with several meanings.', usage_en='Used as a noun or adjective.',
        translation_ru='свет', senses=[
            Sense(translation='свет', definition_en='Visible illumination.', examples=[
                Example(en='Bright light.', ru='Яркий свет.')]),
            Sense(translation='лёгкий', definition_en='Not heavy.', examples=[
                Example(en='A light bag.', ru='Лёгкая сумка.')])])
    apply_result(item, result, 'test')
    fields = note_fields(item)
    assert fields['Translation'] == '1. свет<br>2. лёгкий'
    assert all(value in fields['DefinitionEN'] for value in ('Visible illumination.', 'Not heavy.'))
    assert all(value in fields['Examples'] for value in ('Bright light.', 'Лёгкая сумка.'))
    assert len(item.explain.examples) == 2 and item.complete
    assert _payload(item)['selected_meaning'] == '', 'Generated senses must retain the original cache identity'


def test_network_explanation_without_bilingual_examples_is_rejected():
    from types import SimpleNamespace
    from golyah.gemini import GeminiResponseError, _validated_response
    result = explained().explain
    response = SimpleNamespace(text=result.model_dump_json(), candidates=[])
    with pytest.raises(GeminiResponseError):
        _validated_response(response, 'explain', Explanation)


def test_disconnected_monitor_during_capture_unlocks_ui(bridge, monkeypatch):
    import golyah.bridge as module
    from golyah.windows import CaptureTarget
    callbacks = []
    bridge._requested_target = CaptureTarget('monitor', 1, 0, 0, 20, 20)
    monkeypatch.setattr(module, 'fullscreen_window', lambda *args: False)
    monkeypatch.setattr(module, 'monitors', lambda: [])
    monkeypatch.setattr(bridge, 'task', lambda function, done: callbacks.append(done))
    bridge.startCapture()
    callbacks[0](np.zeros((20, 20, 4), dtype=np.uint8), None)
    assert not bridge.busy and bridge._image is None and not bridge._capture_starting
    assert 'Источник захвата изменился' in bridge.status


def test_empty_ocr_coordinates_are_rejected_before_rendering(bridge, monkeypatch):
    response = {'id': 1, 'result': {'words': [{'id': 0, 'text': 'word', 'polygon': [],
        'confidence': 1, 'line': 0}], 'seconds': 0.1}}
    bridge._ocr_pending = {1: True}
    bridge.message('OCR', True)
    monkeypatch.setattr(bridge._worker, 'readAllStandardOutput', lambda:
        b'GOLYAH_JSON:' + json.dumps(response).encode() + b'\n')
    bridge._read_worker()
    assert not bridge.busy and 'некорректный ответ' in bridge.status
