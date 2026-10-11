"""Migration and resource lifecycle checks for the lightweight desktop build."""
import copy
import json

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from golyah.anki import FIELDS, preview_html
from golyah.audio_models import AudioClip
from golyah.bridge import Bridge
from golyah.card_builder import CardBuilder, MODES, load_builder, templates
from golyah.models import StudyRecord
from golyah.storage import Storage


def test_retired_audio_layout_preserves_other_blocks():
    old = CardBuilder().model_dump()
    old['layouts']['forward']['front'].reverse()
    old['layouts']['forward']['front'][0]['visible'] = True
    original = copy.deepcopy(old)
    for mode in MODES:
        for side in ('front', 'back'):
            old['layouts'][mode][side].insert(2, {'key': 'word_audio', 'visible': True})
            old['layouts'][mode][side].append({'key': 'sentence_audio', 'visible': False})
    stored = copy.deepcopy(old)
    migrated = load_builder(old)
    assert migrated.model_dump() == original
    assert old == stored, 'Migration must not mutate saved preferences'
    for mode in MODES:
        assert 'Audio' not in str(templates(migrated, mode))


def test_existing_audio_fields_and_anki_history_survive_template_update():
    from test_card_builder import Collection, word
    collection = Collection()
    service = collection.service()
    record = word()
    service.sync_modes(record, 'English')
    note_id = record.anki_note_id
    model = collection.notes[note_id]['modelName']
    collection.models[model]['fields'] += ['WordAudio', 'SentenceAudio']
    collection.notes[note_id]['fields']['WordAudio'] = '[sound:own.mp3]'
    saved_notes, saved_cards = copy.deepcopy(collection.notes), copy.deepcopy(collection.cards)
    collection.models[model]['templates']['Vocabulary']['Front'] += '{{WordAudio}}'
    service.apply_layouts()
    assert collection.notes == saved_notes and collection.cards == saved_cards
    assert collection.models[model]['fields'] == FIELDS + ['WordAudio', 'SentenceAudio']
    assert 'Audio' not in str(collection.models[model]['templates']['Vocabulary'])
    assert not any(name == 'storeMediaFile' for name, _ in collection.calls)
    assert '[sound:' not in preview_html(record, side='back')


def test_saved_audio_metadata_remains_exportable(tmp_path):
    app = QApplication.instance() or QApplication([])
    storage = Storage(tmp_path / 'data.sqlite')
    clip = AudioClip(filename='golyahki_' + 'a' * 64 + '.wav', text='loud', source='windows')
    record = StudyRecord(term='loud', sentence='A loud voice.', word_audio=clip)
    storage.save_record(record)
    bridge = Bridge(storage)
    try:
        bridge.lookup(record.term, record.sentence)
        assert bridge.record.word_audio == clip
        assert 'Audio' not in bridge.ankiPreviewHtml
        assert not hasattr(bridge, 'playAudio')
        storage.export_records(tmp_path / 'export.json')
        assert json.loads((tmp_path / 'export.json').read_text(encoding='utf-8'))['records'][0]['word_audio']['filename'] == clip.filename
    finally:
        bridge.close()


def test_list_search_projects_fields_without_validating_whole_records(tmp_path, monkeypatch):
    storage = Storage(tmp_path / 'data.sqlite')
    record = StudyRecord(term='café', sentence='The cafe\u0301 is open.', translation='Кафе', status='draft')
    storage.save_record(record)
    with storage.connect() as db:
        payload = json.loads(record.model_dump_json())
        payload['large_legacy_data'] = 'x' * 500000
        db.execute('UPDATE records SET data=?', (json.dumps(payload),))
    def forbid_validation(*args, **kwargs):
        raise AssertionError('List search must not instantiate complete StudyRecords')
    monkeypatch.setattr(StudyRecord, 'model_validate_json', forbid_validation)
    assert storage.records('CAFÉ')[0] == {
        'uid': record.uid, 'term': record.term, 'sentence': record.sentence,
        'translation': record.translation, 'status': 'draft', 'error': '', 'destination': 'dictionary'}
    assert len(storage.records('кафе', drafts=True)) == 1
    assert storage.records('missing') == []


def test_ocr_worker_is_lazy_and_released_only_while_idle(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    bridge = Bridge(Storage(tmp_path / 'data.sqlite'))
    try:
        monkeypatch.setattr(bridge, 'refreshCaptureSources', lambda: None)
        monkeypatch.setattr(bridge.hotkey, 'register', lambda *args: None)
        monkeypatch.setattr(bridge.overlayKeys, 'start', lambda: None)
        monkeypatch.setattr(bridge.overlayMouse, 'start', lambda: None)
        bridge.initialize()
        assert bridge._worker.state() == QProcess.ProcessState.NotRunning
        killed = []
        monkeypatch.setattr(bridge._worker, 'kill', lambda: killed.append(True))
        bridge._ocr_pending = {1: True}
        bridge._release_idle_worker()
        bridge._ocr_pending.clear()
        bridge._ocr_inflight = 1
        bridge._release_idle_worker()
        bridge._ocr_inflight = None
        bridge._capture_starting = True
        bridge._release_idle_worker()
        assert not killed
        bridge._capture_starting = False
        bridge._release_idle_worker()
        assert killed == [True]
    finally:
        bridge.close()
