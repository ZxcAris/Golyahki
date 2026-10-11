import copy
import html
import json
import re
import time
from pathlib import Path

import httpx
import pytest
from golyah.web_preview import initialize_preview

# Initialize before any test creates QApplication, as the production app does.
initialize_preview()
from PySide6.QtCore import QUrl, QObject
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from golyah.anki import AnkiService, FIELDS, LEGACY_FIELDS, preview_html
from golyah.appearance import Appearance
from golyah.bridge import Bridge
from golyah.card_builder import (CardBuilder, MODEL_NAMES, TEMPLATE_NAMES, MODES,
                                 gap_fields, render_template, templates)
from golyah.models import StudyRecord, Explanation, ContextTranslation, Entry, Example, Sense
from golyah.storage import Storage


def word(term='beckoning', sentence='The lights were beckoning us closer.'):
    return StudyRecord(term=term, sentence=sentence, translation='манящий', lemma='beckon',
        definition_en='Inviting someone to approach.', usage_en='Used for an inviting signal.',
        sentence_translation='Огни манили нас ближе.', context_explanation='Огни привлекали внимание.',
        explain=Explanation(definition_en='Inviting someone to approach.',
            usage_en='Used for an inviting signal.', translation_ru='манящий'),
        context=ContextTranslation(translation_ru='Огни манили нас ближе.', explanation_ru='Огни привлекали внимание.'),
        examples=[Example(en='She was beckoning to us.', ru='Она манила нас к себе.')], status='saved')


class Collection:
    """Stateful AnkiConnect protocol fixture, including note and card scheduling."""
    def __init__(self):
        self.models, self.notes, self.cards, self.calls = {}, {}, {}, []
        self.fail_once = None
        self.empty_cards = False
        self.next_id = 100

    def handler(self, request):
        body = json.loads(request.content)
        action, p = body['action'], body['params']
        self.calls.append((action, copy.deepcopy(p)))
        result = None
        if action == 'version': result = 6
        elif action == 'deckNames': result = ['English']
        elif action == 'modelNames': result = list(self.models)
        elif action == 'createModel':
            self.models[p['modelName']] = {'fields':p['inOrderFields'], 'css':p['css'], 'sort':0,
                'templates':{t['Name']:{k:t[k] for k in ('Front','Back')} for t in p['cardTemplates']}}
        elif action == 'modelFieldNames': result = self.models[p['modelName']]['fields']
        elif action == 'modelFieldAdd': self.models[p['modelName']]['fields'].append(p['fieldName'])
        elif action == 'modelTemplates': result = self.models[p['modelName']]['templates']
        elif action == 'modelStyling': result = {'css':self.models[p['modelName']]['css']}
        elif action == 'updateModelTemplates': self.models[p['model']['name']]['templates'].update(p['model']['templates'])
        elif action == 'updateModelStyling': self.models[p['model']['name']]['css'] = p['model']['css']
        elif action == 'findNotes':
            model, uid = re.match(r'"note:(.+)" UID:(\w+)', p['query']).groups()
            result = [nid for nid,n in self.notes.items() if n['modelName'] == model and n['fields']['UID'] == uid]
        elif action == 'canAddNotes': result = [True for n in p['notes']]
        elif action == 'addNote':
            nid = self.next_id; self.next_id += 1
            self.notes[nid] = copy.deepcopy(p['note'])
            if not self.empty_cards:
                self.cards[nid*10] = {'cardId':nid*10, 'note':nid, 'ord':0, 'queue':0, 'reps':7, 'interval':11, 'lapses':1}
            result = nid
        elif action == 'notesInfo':
            result = [{'noteId':nid, 'modelName':self.notes[nid]['modelName'],
                'fields':{k:{'value':v} for k,v in self.notes[nid]['fields'].items()},
                'cards':[cid for cid,c in self.cards.items() if c['note']==nid]} for nid in p['notes'] if nid in self.notes]
        elif action == 'storeMediaFile':
            import base64
            if not hasattr(self,'media'): self.media={}
            self.media[p['filename']]=base64.b64decode(p['data'])
            result=p['filename']
        elif action == 'updateNoteFields': self.notes[p['note']['id']]['fields'].update(p['note']['fields'])
        elif action == 'cardsInfo': result = [copy.deepcopy(self.cards[c]) for c in p['cards'] if c in self.cards]
        elif action in ('suspend','unsuspend'):
            for cid in p['cards']: self.cards[cid]['queue'] = -1 if action == 'suspend' else 0
            result = True if action == 'suspend' else None
        else: raise AssertionError(action)
        if action == self.fail_once:
            self.fail_once = None
            # Server completed the operation but the client did not receive confirmation.
            raise httpx.ReadTimeout('ambiguous response')
        return httpx.Response(200, json={'result':result, 'error':None})

    def service(self): return AnkiService(transport=httpx.MockTransport(self.handler))


@pytest.mark.parametrize('mode', MODES)
def test_actual_templates_show_question_answer_and_hide_empty_fields(mode):
    r = word()
    front, back = preview_html(r, mode=mode), preview_html(r, mode=mode, side='back')
    assert '{{' not in front and '{{' not in back
    assert 'data-block="etymology"' not in back
    assert 'манящий' in (front if mode == 'reverse' else back)
    if mode == 'forward': assert r.term in front
    if mode == 'reverse': assert r.term not in front and r.term in back
    if mode == 'gap': assert r.term not in front and 'class="gap"' in front and r.term in back


def test_nested_conditions_and_user_text_are_safe():
    assert render_template('{{#X}}a{{#X}}b{{/X}}{{^Y}}c{{/Y}}{{/X}}', {'X':'yes'}) == 'abc'
    assert render_template('{{#X}}a{{#X}}b{{/X}}{{/X}}', {}) == ''
    for invalid in ('{{#X}}a', '{{/X}}', '{{#X}}a{{/Y}}'):
        with pytest.raises(ValueError): render_template(invalid, {'X':'yes'})
    r = word('<script>alert(1)</script>', '<script>alert(1)</script> <&>')
    r.translation = '<img src=x onerror="evil()">'
    html = preview_html(r, side='back')
    assert '<script>' not in html and '<img' not in html
    assert '&lt;script&gt;' in html and '&lt;img' in html


@pytest.mark.parametrize('term,sentence,positions,answer', [
    ('get back','Get him back <now>.',[[0,3],[8,12]],'Get … back'),
    ('quick','A QUICK reply.\n<&>',[],'QUICK'),
    ('inn','Dinner is ready.',[],''),
    ('quick','A quick reply.',[[-1,2],[2,99],[2],[4,3]],'quick'),
    ('A quick','A quick reply.',[[0,7],[2,7],[0,7]],'A quick'),
    ('café','The café is open.',[],'café'),
    ('loud','Not so loud, you idiot!',[[7,12]],'loud'),
    ("can't","I can't, sorry.",[[2,8]],"can't"),
    ("James'","James', please.",[[0,7]],"James'"),
    ('get back','Get, then back.',[[0,4],[10,15]],'Get … back'),
])
def test_gap_uses_real_selected_text_and_boundaries(term,sentence,positions,answer):
    fields = gap_fields(StudyRecord(term=term,sentence=sentence,selected_positions=positions))
    assert html.unescape(fields['GapAnswer']) == answer
    assert '<now>' not in fields['GapSentence'] and '<&>' not in fields['GapSentence']
    if answer: assert 'class="gap"' in fields['GapSentence']
    else: assert fields['GapSentence'] == ''


def test_gap_keeps_ocr_punctuation_outside_blank():
    r=word('loud','Not so loud, you idiot!'); r.selected_positions=[[7,12]]
    fields=gap_fields(r)
    assert fields['GapAnswer']=='loud'
    assert fields['GapSentence']=='Not so <span class="gap">_____</span>, you idiot!'


def test_gap_optional_context_block_stays_masked_on_question():
    builder = CardBuilder()
    next(b for b in builder.layouts['gap'].front if b.key=='sentence').visible=True
    r=word()
    assert r.term not in preview_html(r,builder,mode='gap')
    assert r.term in preview_html(r,builder,mode='gap',side='back')


@pytest.mark.parametrize('invalid', ['hide_prompt','duplicate','missing','wrong_key','missing_mode'])
def test_builder_rejects_unusable_layout(invalid):
    value=CardBuilder().model_dump(); blocks=value['layouts']['forward']['front']
    if invalid=='hide_prompt': blocks[0]['visible']=False
    if invalid=='duplicate': blocks.append(blocks[0])
    if invalid=='missing': blocks.pop()
    if invalid=='wrong_key': blocks[1]['key']='evil'
    if invalid=='missing_mode': value['layouts'].pop('gap')
    with pytest.raises(ValueError): CardBuilder.model_validate(value)


def test_modes_create_only_selected_and_retry_without_duplicates():
    c=Collection(); service=c.service(); r=word(); r.learning_modes=['reverse','gap']
    service.add(r,'English'); service.add(r,'English')
    assert len(c.notes)==2 and set(r.anki_note_ids)=={'reverse','gap'}
    assert MODEL_NAMES['forward'] not in c.models
    for mode in r.learning_modes:
        assert c.models[MODEL_NAMES[mode]]['fields'][0]=='Term'
    other=word(sentence='I was beckoning to them.'); other.learning_modes=['reverse','gap']
    service.add(other,'English')
    assert len(c.notes)==4
    assert all(n['options']['allowDuplicate'] for n in c.notes.values())


@pytest.mark.parametrize('mode', MODES)
def test_each_anki_variant_receives_all_dictionary_meanings_and_examples(mode):
    c = Collection()
    record = word('light', 'Turn on the light.')
    record.translation = 'свет'
    record.entries = [Entry(word='light', pos='n', senses=[
        Sense(translation='свет', definition_en='Visible radiation.', examples=[
            Example(en='Bright light.', ru='Яркий свет.')]),
        Sense(translation='лампа', definition_en='A lamp.', examples=[
            Example(en='Turn on the light.', ru='Включи лампу.')])]),
        Entry(word='light', pos='adj', senses=[Sense(translation='лёгкий', definition_en='Not heavy.',
            examples=[Example(en='A light bag.', ru='Лёгкая сумка.')])])]
    record.learning_modes = [mode]
    c.service().add(record, 'English')
    assert len(c.notes) == 1
    fields = next(iter(c.notes.values()))['fields']
    for value in ('свет', 'лампа', 'лёгкий'):
        assert value in fields['Translation']
    for value in ('Visible radiation.', 'A lamp.', 'Not heavy.'):
        assert value in fields['DictionaryDefinitionEN']
    for value in ('Bright light.', 'Turn on the light.', 'A light bag.', 'Лёгкая сумка.'):
        assert value in fields['Examples']
    preview = preview_html(record, mode=mode, side='back')
    assert all(value in preview for value in ('свет', 'лампа', 'лёгкий', 'A light bag.'))


def test_switching_modes_keeps_history_manual_pauses_and_custom_cards():
    c=Collection(); service=c.service(); r=word(); r.learning_modes=MODES.copy()
    service.add(r,'English'); ids=r.anki_note_ids.copy()
    forward=c.cards[ids['forward']*10]; gap=c.cards[ids['gap']*10]
    gap['queue']=-1  # User suspended this card directly in Anki.
    custom=9999
    c.models[MODEL_NAMES['forward']]['templates']['Custom']={'Front':'mine','Back':'mine'}
    c.models[MODEL_NAMES['forward']]['sort']=1
    c.cards[custom]={'cardId':custom,'note':ids['forward'],'ord':1,'queue':2,'reps':23}
    original_notes=copy.deepcopy(c.notes); history={k:forward[k] for k in ('reps','interval','lapses')}
    r.learning_modes=['reverse']; service.sync_modes(r,'English')
    assert forward['queue']==-1 and r.anki_paused_cards==[forward['cardId']]
    assert c.cards[custom]['queue']==2 and gap['queue']==-1
    r.learning_modes=MODES.copy(); service.sync_modes(r,'English')
    assert forward['queue']==0 and not r.anki_paused_cards and gap['queue']==-1
    assert c.notes==original_notes and r.anki_note_ids==ids
    assert {k:forward[k] for k in history}==history
    assert c.models[MODEL_NAMES['forward']]['sort']==1


@pytest.mark.parametrize('action', ['addNote','suspend','unsuspend'])
def test_ambiguous_network_failure_keeps_journal_and_safe_retry(action):
    c=Collection(); s=c.service(); r=word(); r.learning_modes=['forward','reverse']
    if action!='addNote': s.sync_modes(r,'English'); r.learning_modes=['reverse']
    if action=='unsuspend': s.sync_modes(r,'English'); r.learning_modes=['forward','reverse']
    c.fail_once=action
    with pytest.raises(RuntimeError): s.sync_modes(r,'English')
    assert r.anki_modes_pending
    if action=='suspend': assert r.anki_paused_cards
    s.sync_modes(r,'English')
    assert len(c.notes)==2 and not r.anki_modes_pending
    assert all(c.cards[n*10]['queue'] == (0 if m in r.learning_modes else -1) for m,n in r.anki_note_ids.items())


def test_imported_note_ids_are_not_used_to_modify_unrelated_cards():
    c=Collection(); s=c.service(); r=word(); r.learning_modes=['reverse']; r.anki_note_ids={'forward':456}
    s.sync_modes(r,'English')
    assert set(r.anki_note_ids)=={'reverse'}
    assert not any(action=='suspend' for action,p in c.calls)


def test_missing_managed_card_does_not_report_success():
    c=Collection(); c.empty_cards=True; r=word(); r.learning_modes=['reverse']
    with pytest.raises(RuntimeError,match='не создала карточку'): c.service().sync_modes(r,'English')
    assert r.anki_modes_pending and r.anki_note_ids


def test_old_forward_model_keeps_fields_sort_and_notes():
    c=Collection()
    c.models[MODEL_NAMES['forward']]={'fields':LEGACY_FIELDS.copy(),'sort':1,'css':'old',
        'templates':{'Vocabulary':{'Front':'old','Back':'old'}}}
    c.service().apply_layouts()
    assert c.models[MODEL_NAMES['forward']]['fields']==FIELDS
    assert c.models[MODEL_NAMES['forward']]['sort']==1 and not c.notes


def test_export_import_modes_and_old_record_defaults(tmp_path):
    s=Storage(tmp_path/'a.sqlite'); r=word(); uid=r.uid
    r.learning_modes=['reverse','gap']; r.anki_note_ids={'reverse':123,'gap':124}; r.anki_paused_cards=[1000]
    s.save_record(r); path=tmp_path/'export.json'; s.export_records(path)
    target=Storage(tmp_path/'b.sqlite'); target.import_records(path)
    restored=target.get_record(uid)
    assert restored.learning_modes==r.learning_modes and restored.anki_note_ids==r.anki_note_ids
    assert restored.anki_paused_cards==[1000] and restored.uid==uid
    legacy=r.model_dump()
    for key in ('learning_modes','anki_note_ids','anki_paused_cards','anki_modes_pending'): legacy.pop(key)
    assert StudyRecord.model_validate(legacy).learning_modes==['forward']
    assert StudyRecord.model_validate(legacy).uid==uid
    for modes in ([],['gap','gap'],['unknown']):
        with pytest.raises(ValueError): StudyRecord.model_validate({**legacy,'learning_modes':modes})


def test_bridge_preview_and_preferences_preserve_saved_enrichment(tmp_path):
    app=QApplication.instance() or QApplication([])
    s=Storage(tmp_path/'test.sqlite'); r=word(); r.anki_note_id=123; s.save_record(r)
    bridge=Bridge(s)
    try:
        bridge.lookup(r.term,r.sentence) # Fresh dictionary lookup has no LLM enrichment.
        assert not bridge.record.complete
        bridge.selectBuilderWord(r.uid)
        assert bridge.builderWord['complete'] and r.term in bridge.ankiPreviewHtml
        bridge.setAnkiPreview('reverse','front')
        assert r.translation in bridge.ankiPreviewHtml and r.term not in bridge.ankiPreviewHtml
        assert bridge.setRecordStudyModes(r.uid,'["reverse","gap"]')
        saved=s.get_record(r.uid)
        assert saved.complete and saved.definition_en==r.definition_en and saved.anki_modes_pending
        assert not bridge.setRecordStudyModes(r.uid,'[]')
        bridge.setAnkiPreview('forward','back')
        assert bridge.setBuilderBlock('forward','back','definition',False)
        assert r.definition_en not in bridge.ankiPreviewHtml
        bridge.moveBuilderBlock('forward','back','lemma',-1)
        assert bridge.cardBuilder['layouts']['forward']['back'][0]['key']=='lemma'
        assert not bridge.setBuilderBlock('forward','front','prompt',False)
        assert s.setting('card_builder')['layouts']['forward']['back'][0]['key']=='lemma'
        assert bridge.setAppearance('{"cardAccent":"#80cdb8"}')
        assert '#80cdb8' in bridge.ankiPreviewHtml
        bridge.lookup('other','')
        assert bridge.builderWord['uid']==r.uid and bridge.record.term=='other'
    finally: bridge.close()


def test_bridge_sync_offline_persists_retry_and_avoids_llm(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    s=Storage(tmp_path/'test.sqlite'); r=word(); r.learning_modes=['reverse']; s.save_record(r)
    s.set_setting('anki_deck','English'); bridge=Bridge(s)
    class Offline:
        def __init__(self,**kw): pass
        def sync_modes(self,record,deck):
            record.anki_note_ids={'reverse':123}
            raise RuntimeError('Anki недоступна.')
    monkeypatch.setattr('golyah.bridge.AnkiService',Offline)
    try:
        bridge.syncStudyModes(r.uid)
        deadline=time.monotonic()+4
        while bridge.busy and time.monotonic()<deadline: QTest.qWait(20)
        assert not bridge.busy and 'Anki недоступна' in bridge.status
        saved=s.get_record(r.uid)
        assert saved.complete and saved.anki_modes_pending and saved.anki_note_ids=={'reverse':123}
        assert saved.status=='pending_anki'
    finally: bridge.close()


@pytest.mark.parametrize('width,height,font', [(1280,900,14),(1040,680,20)])
@pytest.mark.desktop
def test_constructor_native_preview_and_controls(tmp_path,width,height,font):
    from test_qml import visual_child
    app=QApplication.instance() or QApplication([]); app.setQuitOnLastWindowClosed(False)
    s=Storage(tmp_path/'test.sqlite'); r=word(); s.save_record(r)
    bridge=Bridge(s); bridge.setAppearance(json.dumps({'uiFontSize':font}))
    engine=QQmlApplicationEngine(); warnings=[]
    engine.warnings.connect(lambda messages:warnings.extend(m.toString() for m in messages))
    engine.rootContext().setContextProperty('backend',bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'golyah/qml/Main.qml')))
    assert engine.rootObjects()
    window=engine.rootObjects()[0]; window.resize(width,height); window.setProperty('page',4)
    window.show(); QTest.qWait(1800)
    def item(name): return visual_child(window.contentItem(),name)
    try:
        assert item('cardBuilderPage') and item('ankiWebPreview').height()>170
        assert item('builderWordChoice').property('popupInWindow')
        assert item('applyCardBuilder').isVisible() and item('applyCardBuilder').height()>25
        assert not item('builderBlock_prompt').isEnabled()
        assert item('builderBlock_sentence').property('checked')
        bridge.setBuilderBlock('forward','front','sentence',False); QTest.qWait(100)
        assert not item('builderBlock_sentence').property('checked')
        assert bridge.setRecordStudyModes(r.uid,'["forward","reverse","gap"]')
        item('cardBuilderPage').setProperty('mode','gap'); item('cardBuilderPage').setProperty('side','back')
        QTest.qWait(800)
        assert r.term in bridge.ankiPreviewHtml and 'class="gap"' in bridge.ankiPreviewHtml
        assert not warnings, '\n'.join(warnings)
        output=Path(__file__).resolve().parents[1]/'test-results/builder'
        output.mkdir(parents=True,exist_ok=True)
        window.grabWindow().save(str(output/f'constructor-{width}-{font}.png'))
    finally:
        bridge.close()
        for root in engine.rootObjects(): root.close()
        engine.deleteLater(); QTest.qWait(50)
