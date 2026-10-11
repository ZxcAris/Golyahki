import json
import zipfile
from pathlib import Path

import httpx
import pytest

from golyah.anki import AnkiService, BACK, CSS, FIELDS, FRONT, MODEL
from golyah.dictionaries import DictionaryService, parse_wty
from golyah.gemini import apply_result, ensure_enriched
from golyah.models import ContextTranslation, Enrichment, Entry, Example, Explanation, OCRWord, Sense, StudyRecord
from golyah.ocr import convert_result
from golyah.selection import selection
from golyah.storage import Storage


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "database.sqlite")


def example_entry(word="quick", translation="быстрый"):
    return [word, "", "adj", "adj", 0, [{"type": "structured-content", "content": [
        {"tag": "ol", "data": {"content": "glosses"}, "content": [
            {"tag": "li", "content": [translation, {"tag": "details", "content": [
                {"tag": "div", "data": {"content": "example-sentence"}, "content": [
                    {"tag": "div", "data": {"content": "example-sentence-a"}, "content": "A quick look."},
                    {"tag": "div", "data": {"content": "example-sentence-b"}, "content": "Быстрый взгляд."}
                ]}
            ]}]}]
        }, {"tag": "div", "data": {"content": "Etymology-content"}, "content": "Old English"}
    ]}], 0, ""]


def archive(path, rows, revision="1"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("index.json", json.dumps({"title": "test-wty", "format": 3, "revision": revision}))
        z.writestr("term_bank_1.json", json.dumps(rows, ensure_ascii=False))


def enriched(term="quick", sentence="A quick look."):
    r = StudyRecord(term=term, sentence=sentence)
    apply_result(r, Explanation(definition_en="Fast.", usage_en="Describes speed.", translation_ru="быстрый",
                               examples=[Example(en="A quick reply.", ru="Быстрый ответ.")]), "test-model")
    if sentence:
        apply_result(r, ContextTranslation(translation_ru="Быстрый взгляд.", explanation_ru="Скорость действия."), "test-model")
    return r


def test_wty_preserves_senses_and_examples():
    entry, forms = parse_wty(example_entry(), "test")
    assert entry.senses[0].translation == "быстрый"
    assert entry.senses[0].examples[0].ru == "Быстрый взгляд."
    assert entry.etymology == "Old English"
    assert not forms


def test_builtin_nah_is_available_and_keeps_user_dictionary_preferences(storage):
    service = DictionaryService(storage)
    assert service.ensure_builtin()['count'] == 1
    entry = service.lookup('Nah,')[0]
    assert entry.senses[0].translation == 'неа; нет'
    assert entry.definition_en and entry.tags == ['Informal']
    assert all(example.en and example.ru for example in entry.senses[0].examples)
    built_in = next(item for item in service.list() if item['title'] == entry.dictionary)
    assert built_in['priority'] == -100
    service.configure(built_in['id'],False,7)
    assert service.ensure_builtin()['unchanged']
    assert not service.lookup('nah')
    saved = next(item for item in service.list() if item['id'] == built_in['id'])
    assert not saved['enabled'] and saved['priority'] == 7


def test_import_forms_priority_and_idempotence(storage, tmp_path):
    file = tmp_path / "dictionary.zip"
    archive(file, [example_entry(), ["quicker", "", "non-lemma", "adj", 0, [["quick", ["comparative"]]], 0, ""]])
    service = DictionaryService(storage)
    assert service.import_file(file)["count"] == 2
    assert service.import_file(file)["unchanged"]
    assert len(service.lookup("quick")) == 1
    assert service.lookup("quicker")[0].word == "quick"
    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"schemaVersion": 1, "kind": "golyah-dictionary", "name": "custom",
        "entries": [{"word": "quick", "senses": [{"translation": "скорый"}]}]}), encoding="utf-8")
    service.import_file(custom)
    second = next(d for d in service.list() if d["title"] == "custom")
    service.configure(second["id"], True, 10)
    assert service.lookup("quick")[0].dictionary == "custom"
    service.configure(second["id"], False, 10)
    assert service.lookup("quick")[0].dictionary == "test-wty"


def test_failed_update_is_atomic(storage, tmp_path):
    file = tmp_path / "dictionary.zip"
    service = DictionaryService(storage)
    archive(file, [example_entry()])
    service.import_file(file)
    archive(file, [example_entry("new"), ["malformed"]], "2")
    with pytest.raises(ValueError):
        service.import_file(file)
    assert service.lookup("quick")
    assert not service.lookup("new")
    assert service.list()[0]["revision"] == "1"


@pytest.mark.parametrize('query', ['*chuckle*', ' **chuckle** ', '*chuckles*'])
def test_dictionary_looks_up_asterisk_wrapped_words(storage, tmp_path, query):
    file = tmp_path / 'actions.zip'
    archive(file, [example_entry('chuckle', 'тихо смеяться'),
        ['chuckles', '', 'non-lemma', 'adj', 0, [['chuckle', []]], 0, '']])
    service = DictionaryService(storage)
    service.import_file(file)
    assert service.lookup(query)[0].word == 'chuckle'
    assert service.lookup(query)[0].senses[0].translation == 'тихо смеяться'


def test_dictionary_never_substitutes_a_keyword_for_a_missing_sentence(storage, tmp_path):
    file = tmp_path / 'phrases.zip'
    archive(file, [example_entry('appear', 'появляться'),
                   example_entry('appear on TV', 'появиться на телевидении')])
    service = DictionaryService(storage)
    service.import_file(file)
    assert not service.lookup('Something may appear on TV')
    assert service.lookup('appear on TV.')[0].senses[0].translation == 'появиться на телевидении'


def test_dictionary_preserves_optional_english_definitions_and_word_metadata(storage, tmp_path):
    file = tmp_path / 'english.json'
    file.write_text(json.dumps({'schemaVersion': 1, 'kind': 'golyah-dictionary', 'name': 'English',
        'entries': [{'word': 'experience', 'pos': 'v', 'tags': ['Figurative'], 'ipa': '/test/',
            'definition_en': 'To undergo a situation.', 'senses': [{'translation': 'испытывать',
                'definition_en': 'To feel a particular emotion.', 'examples': [
                    {'en': 'I experienced relief.', 'ru': 'Я почувствовал облегчение.'}]}]}]}), encoding='utf-8')
    service = DictionaryService(storage)
    service.import_file(file)
    entry = service.lookup('experience')[0]
    assert entry.tags == ['Figurative'] and entry.ipa == '/test/'
    assert entry.definition_en == 'To undergo a situation.'
    assert entry.senses[0].definition_en == 'To feel a particular emotion.'
    assert entry.senses[0].examples[0].ru == 'Я почувствовал облегчение.'


def test_saved_roundtrip_and_uid(storage, tmp_path):
    r = enriched(); r.status = "saved"
    storage.save_record(r)
    assert storage.get_record(r.uid).complete
    path = tmp_path / "export.json"
    storage.export_records(path)
    other = Storage(tmp_path / "other.sqlite")
    assert other.import_records(path) == 1
    imported = other.get_record(r.uid)
    assert imported.context == r.context
    assert imported.examples == r.examples
    assert StudyRecord(term=" QUICK ", sentence="a QUICK look.").uid == r.uid
    assert StudyRecord(term="quick", sentence="A different sentence.").uid != r.uid


def test_invalid_personal_import_does_not_partially_write(storage, tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"schemaVersion": 1, "kind": "golyah-study",
        "records": [enriched().model_dump(), {"term": "broken", "explain": {"definition_en": ""}}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        storage.import_records(path)
    assert storage.records() == []


def test_save_enrichment_combines_requests_and_preserves_edits():
    class Provider:
        calls = []
        def generate(self, record, mode, cancel):
            self.calls.append(mode)
            r = enriched()
            return Enrichment(explain=r.explain, context=r.context), "test-model"
    provider = Provider()
    record = StudyRecord(term="quick", sentence="A quick look.", translation="ручной перевод")
    ensure_enriched(record, provider)
    assert provider.calls == ["both"] and record.complete
    assert record.translation == "ручной перевод"
    ensure_enriched(record, provider)
    assert provider.calls == ["both"]


def test_word_only_enrichment_does_not_invent_context():
    class Provider:
        def generate(self, record, mode, cancel):
            assert mode == "explain"
            return enriched(sentence="").explain, "test-model"
    record = StudyRecord(term="quick")
    ensure_enriched(record, Provider())
    assert record.complete and record.context is None and not record.sentence


def test_dictionary_defaults_include_every_sense_and_keep_manual_content():
    entries = [Entry(word='light', pos='n', dictionary='Test', senses=[
        Sense(translation='свет', examples=[Example(en='Bright light.', ru='Яркий свет.')]),
        Sense(translation='лампа', examples=[Example(en='A lamp.', ru='Лампа.')])]),
        Entry(word='light', pos='adj', dictionary='Other', senses=[Sense(translation='лёгкий')])]
    record = StudyRecord(term='light', entries=entries, sense_index=1)
    record.select_defaults()
    assert all(value in record.translation for value in ('свет', 'лампа', 'лёгкий'))
    assert [example.en for example in record.examples] == ['Bright light.', 'A lamp.']
    assert record.sources == ['Test', 'Other']
    record.translation = 'Ручное уточнение'
    record.examples.append(Example(en='My example.', ru='Мой пример.'))
    record.include_dictionary_content()
    before = record.model_dump()
    record.include_dictionary_content()
    assert record.model_dump() == before
    assert record.translation.startswith('Ручное уточнение\n\n')
    assert len(record.examples) == 3


def test_completed_legacy_record_gains_missing_dictionary_senses_without_llm():
    class NoRequests:
        def generate(self, *args):
            raise AssertionError('Completed data must be reused')
    record = enriched(sentence='')
    record.entries = [Entry(word='quick', senses=[Sense(translation='быстрый'),
        Sense(translation='живой', examples=[Example(en='The quick and the dead.', ru='Живые и мёртвые.')])])]
    record.translation = 'быстрый'
    ensure_enriched(record, NoRequests())
    assert record.translation == '1. быстрый\n2. живой'
    assert 'The quick and the dead.' in [example.en for example in record.examples]


def test_anki_retry_checks_uid_before_sending_and_escapes_html():
    calls, notes = [], []
    def handler(request):
        body = json.loads(request.content)
        action, params = body["action"], body["params"]
        calls.append(action)
        result = {"version": 6, "deckNames": ["Test"], "modelNames": [MODEL], "modelFieldNames": FIELDS,
                  "modelTemplates": {"Vocabulary": {"Front": FRONT, "Back": BACK}}, "modelStyling": {"css": CSS},
                  "findNotes": [123] if notes else [], "canAddNotes": [True]}.get(action)
        if action == "addNote":
            notes.append(params["note"]); result = 123
        return httpx.Response(200, json={"result": result, "error": None})
    service = AnkiService(transport=httpx.MockTransport(handler))
    r = enriched(term="<script>alert(1)</script>")
    assert service.add(r, "Test") == 123
    assert service.add(r, "Test") == 123
    assert calls.count("addNote") == 1
    assert "&lt;script&gt;" in notes[0]["fields"]["Term"]


def test_incomplete_records_cannot_reach_anki():
    with pytest.raises(ValueError):
        AnkiService().add(StudyRecord(term="quick"), "Test")


def test_paddle_word_boxes_and_disjoint_selection():
    words = convert_result({"res": {"rec_texts": ["A quick look."], "rec_scores": [0.95],
        "text_word": [["A", "quick", "look."]],
        "text_word_boxes": [[[0, 10, 10, 30], [12, 10, 60, 30], [63, 10, 100, 30]]]}})
    assert len(words) == 3
    data = selection(words, [0, 2])
    assert data["display"] == "A … look."
    assert data["sentence"] == "A quick look."
    assert data["positions"] == [[0, 1], [8, 13]]


def test_ocr_refuses_fake_word_coordinates():
    with pytest.raises(ValueError):
        convert_result({"rec_texts": ["two words"], "rec_scores": [0.8], "rec_polys": [[[0,0],[50,0],[50,20],[0,20]]]})


def test_ocr_filters_icons_punctuation_numbers_and_low_confidence():
    labels = ['✓', '...', '99', 'x', 'quick', 'uncertain', 'I', 'a', '*', '***']
    result = {'rec_texts': labels, 'rec_scores': [.99,.99,.99,.99,.95,.4,.97,.96,.99,.99],
              'text_word': [[x] for x in labels],
              'text_word_boxes': [[[10, 10 + 30*i, 70, 30 + 30*i]] for i in range(len(labels))]}
    words = convert_result(result)
    assert [w.text for w in words] == ['quick', 'I', 'a']
    assert [w.id for w in words] == [0,1,2]


@pytest.mark.parametrize('label', ['*chuckle*', '**sigh**', '*I*', '*a*', '*chuckle*,'])
def test_ocr_keeps_asterisk_wrapped_text_and_real_word_bounds(label):
    from golyah.selection import highlight_layout, word_at
    pieces = list(label)
    words = convert_result({'rec_texts': [label], 'rec_scores': [.97],
        'text_word': [pieces],
        'text_word_boxes': [[[i*10,10,i*10+8,30] for i in range(len(pieces))]]})
    assert len(words) == 1 and words[0].text == label
    assert words[0].bounds() == (0,10,(len(label)-1)*10+8,30)
    annotated, segments = highlight_layout(words)
    assert word_at(annotated, 30, 20)['text'] == label
    assert len(segments) == 1
    data = selection(words, [words[0].id])
    assert data['term'] == label.strip('*,')
    assert data['display'] == data['sentence'] == label
    assert data['positions'] == [[0,len(label)]]


def test_english_ocr_keeps_contractions_punctuation_and_sentence_numbers():
    labels = ['I', ' ', 'can', "'", 't', ' ', 'buy', ' ', '2', ' ', 'well', '-', 'known', ' ', 'books', '.']
    words = convert_result({'rec_texts': ["I can't buy 2 well-known books."], 'rec_scores': [.97],
        'text_word': [labels], 'text_word_boxes': [[[i*10,10,i*10+8,30] for i in range(len(labels))]]})
    assert [w.text for w in words] == ['I', "can't", 'buy', '2', 'well-known', 'books.']
    assert selection(words, [1])['sentence'] == "I can't buy 2 well-known books."


def test_sentence_highlights_follow_wrapping_and_keep_distinct_sentences():
    from golyah.selection import highlight_layout
    from golyah.models import OCRWord
    words = [OCRWord(id=i, text=text, line=line, block=0,
        polygon=[[x,y],[x+40,y],[x+40,y+20],[x,y+20]], confidence=1)
        for i, (text,line,x,y) in enumerate([
            ('Mr.',0,10,10), ('Smith',0,60,10), ('went',0,110,10),
            ('home.',1,10,40), ('Another',1,60,40), ('sentence.',1,110,40)])]
    annotated, lines = highlight_layout(words)
    assert [w['sentenceId'] for w in annotated] == [0,0,0,0,1,1]
    assert len(lines) == 2, 'Sentences on one row share the clear contour; sentence IDs stay distinct'
    assert lines[1]['sentenceIds'] == [0,1]
    assert lines[1]['left'] <= 10 and lines[1]['left']+lines[1]['width'] >= 50
    assert selection(words, [2])['sentence'] == 'Mr. Smith went home.'


def test_word_highlights_follow_actual_boxes_for_mixed_font_sizes():
    from golyah.models import OCRWord
    from golyah.selection import highlight_layout, word_at
    words = [OCRWord(id=i, text=text, line=0, block=0, confidence=1,
        polygon=[[x,top],[x+40,top],[x+40,bottom],[x,bottom]])
        for i,(text,x,top,bottom) in enumerate([
            ('Large',10,10,46), ('small',65,22,40), ('lower.',120,28,48)])]
    annotated, _ = highlight_layout(words)
    for original, value in zip(words,annotated):
        left,top,right,bottom = original.bounds()
        box = value['highlightBounds']
        assert abs(box['left']-left) <= 6 and abs(box['top']-top) <= 6
        assert abs(box['left']+box['width']-right) <= 6
        assert abs(box['top']+box['height']-bottom) <= 6
        assert word_at(annotated,(left+right)/2,(top+bottom)/2)['id'] == original.id
    assert annotated[1]['highlightBounds']['height'] < annotated[0]['highlightBounds']['height']
    assert annotated[2]['highlightBounds']['top'] > annotated[0]['highlightBounds']['top']
