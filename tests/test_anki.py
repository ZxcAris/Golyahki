import json

import httpx
import pytest

from golyah.anki import (AnkiService, BACK, CSS, FIELDS, FRONT, LEGACY_FIELDS,
                         MODEL, highlighted_sentence, note_fields)
from golyah.models import Entry, Example, Explanation, Sense, StudyRecord


def transport_service(fields=None, templates=None, css="old css", existing=None, add_result=123):
    state = {"fields": list(fields if fields is not None else LEGACY_FIELDS),
             "templates": templates if templates is not None else {"Vocabulary": {"Front": "old", "Back": "old"}},
             "css": css, "calls": [], "notes": [], "existing": existing or []}

    def handler(request):
        body = json.loads(request.content)
        action, params = body["action"], body["params"]
        state["calls"].append((action, params))
        result = None
        if action == "version": result = 6
        elif action == "deckNames": result = ["English"]
        elif action == "modelNames": result = [MODEL]
        elif action == "modelFieldNames": result = state["fields"]
        elif action == "modelTemplates": result = state["templates"]
        elif action == "modelStyling": result = {"css": state["css"]}
        elif action == "modelFieldAdd": state["fields"].append(params["fieldName"])
        elif action == "updateModelTemplates": state["templates"].update(params["model"]["templates"])
        elif action == "updateModelStyling": state["css"] = params["model"]["css"]
        elif action == "findNotes": result = state["existing"]
        elif action == "canAddNotes": result = [True]
        elif action == "addNote":
            state["notes"].append(params["note"])
            result = add_result
        else: raise AssertionError(action)
        return httpx.Response(200, json={"result": result, "error": None})

    return AnkiService(transport=httpx.MockTransport(handler)), state


def test_legacy_model_upgrades_once_and_keeps_existing_note():
    service, state = transport_service(existing=[321])
    record = StudyRecord(term="word", explain=Explanation(definition_en="A term.", usage_en="Use it.", translation_ru="слово"))
    assert service.add(record, "English") == 321
    assert state["fields"] == FIELDS
    assert state["css"] == CSS
    assert state["templates"]["Vocabulary"] == {"Front": FRONT, "Back": BACK}
    assert not state["notes"]
    before = len(state["calls"])
    service.ensure_model()
    assert not any(a.startswith("update") or a == "modelFieldAdd" for a, _ in state["calls"][before:])


def test_partial_upgrade_resumes_and_preserves_extra_fields_and_templates():
    templates = {"Vocabulary": {"Front": "old", "Back": "old"}, "Custom": {"Front": "custom", "Back": "custom"}}
    service, state = transport_service(fields=FIELDS[:13] + ["Personal"], templates=templates)
    service.ensure_model()
    assert len(state["fields"]) == len(FIELDS) + 1
    assert set(FIELDS) < set(state["fields"])
    assert state["templates"]["Custom"]["Front"] == "custom"


@pytest.mark.parametrize("fields,templates", [(["Term", "UID"], None), (LEGACY_FIELDS, {"Other": {}})])
def test_conflicting_model_is_rejected_before_any_mutation(fields, templates):
    service, state = transport_service(fields=fields, templates=templates)
    with pytest.raises(RuntimeError): service.ensure_model()
    assert not any(a.startswith("update") or a == "modelFieldAdd" for a, _ in state["calls"])


def test_new_model_gets_all_fields_and_one_card():
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"result": [] if body["action"] == "modelNames" else {}, "error": None})
    AnkiService(transport=httpx.MockTransport(handler)).ensure_model()
    params = calls[1]["params"]
    assert params["inOrderFields"] == FIELDS
    assert params["cardTemplates"] == [{"Name": "Vocabulary", "Front": FRONT, "Back": BACK}]


def test_export_uses_all_senses_preserves_edits_and_escapes_every_source():
    entry = Entry(word="experience", pos="v", ipa="/test/", tags=["Informal", "<script>"],
                  definition_en="General definition", etymology="<origin>", extra="A & B",
                  senses=[Sense(translation="first", definition_en="Wrong sense"),
                          Sense(translation="second", definition_en="Selected <sense>")])
    record = StudyRecord(term="experience", lemma="experience", entries=[entry], sense_index=1,
                         translation="Мой перевод", definition_en="My <definition>", usage_en="My usage",
                         examples=[Example(en="A <sample>.", ru="Пример & перевод"), Example(en="A <sample>.", ru="Пример & перевод")],
                         synonyms=["face", "face", "<synonym>"], sources=["", "dictionary", "dictionary"])
    fields = note_fields(record)
    assert set(fields) == set(FIELDS)
    assert fields["DefinitionEN"] == "My &lt;definition&gt;" and fields["UsageEN"] == "My usage"
    assert fields["Translation"] == "Мой перевод<br><br>1. first<br>2. second"
    assert fields["DictionaryDefinitionEN"] == "General definition<br>1. first — Wrong sense<br>2. second — Selected &lt;sense&gt;"
    assert fields["PartOfSpeech"] == "v" and fields["IPA"] == "/test/"
    assert "<script>" not in fields["Register"] and "&lt;script&gt;" in fields["Register"]
    assert fields["Examples"].count('<li class="example">') == 1
    assert "Пример &amp; перевод" in fields["Examples"]
    assert fields["Synonyms"].count('class="synonym"') == 2
    assert fields["Etymology"] == "&lt;origin&gt;" and fields["Notes"] == "A &amp; B"
    assert fields["Source"] == "dictionary"
    assert record.translation == "Мой перевод", 'Export must not mutate saved edits'


def test_export_restores_all_articles_and_examples_from_legacy_selected_sense():
    shared = Example(en='Shared <example>.', ru='Общий & перевод.')
    entries = [
        Entry(word='light', pos='n', dictionary='First', definition_en='General noun definition.',
              sources=['https://first.test'], synonyms=['illumination'], senses=[
                  Sense(translation='свет', definition_en='Visible light.', examples=[shared]),
                  Sense(translation='лампа', definition_en='A lamp.', examples=[
                      Example(en='Turn on the light.', ru='Включи лампу.')])]),
        Entry(word='light', pos='adj', dictionary='Second', ipa='/laɪt/', tags=['Informal'],
              sources=['https://second.test'], synonyms=['weightless'], etymology='Other origin.', extra='Other notes.',
              senses=[Sense(translation='лёгкий', definition_en='Not heavy.', examples=[shared,
                  Example(en='A light bag.', ru='Лёгкая сумка.')])]),
    ]
    record = StudyRecord(term='light', entries=entries, translation='лампа', sense_index=1,
                         examples=[entries[0].senses[1].examples[0]], sources=['First'])
    fields = note_fields(record)
    for translation in ['свет', 'лампа', 'лёгкий']:
        assert translation in fields['Translation']
    for definition in ['General noun definition.', 'Visible light.', 'A lamp.', 'Not heavy.']:
        assert definition in fields['DictionaryDefinitionEN']
    assert fields['Examples'].count('<li class="example">') == 3
    assert 'Shared &lt;example&gt;.' in fields['Examples'] and 'Общий &amp; перевод.' in fields['Examples']
    assert 'Лёгкая сумка.' in fields['Examples'] and 'Включи лампу.' in fields['Examples']
    assert fields['PartOfSpeech'] == 'n<br>adj'
    assert fields['IPA'] == '/laɪt/' and 'Informal' in fields['Register']
    assert fields['Etymology'] == 'Other origin.' and fields['Notes'] == 'Other notes.'
    assert 'illumination' in fields['Synonyms'] and 'weightless' in fields['Synonyms']
    assert fields['Source'] == 'First<br>https://first.test<br>https://second.test<br>Second'
    record.entry_index, record.sense_index = 1, 0
    assert note_fields(record) == fields, 'Selection only controls the contextual LLM explanation'


def test_export_without_optional_data_has_empty_fields():
    fields = note_fields(StudyRecord(term="word"))
    for field in ["Examples", "Synonyms", "IPA", "Register", "PartOfSpeech", "Etymology", "DictionaryDefinitionEN"]:
        assert fields[field] == ""


@pytest.mark.parametrize("term,sentence,positions,expected", [
    ("inn", "Dinner at the inn.", [], "Dinner at the <mark>inn</mark>."),
    ("inn", "Dinner is ready.", [], "Dinner is ready."),
    ("quick", "A QUICK reply.", [], "A <mark>QUICK</mark> reply."),
    ("get back", "Get him back <now>.", [[0, 3], [8, 12]], "<mark>Get</mark> him <mark>back</mark> &lt;now&gt;."),
    ("quick", "A quick reply.", [[-1, 2], [2, 99], [2], [4, 3]], "A <mark>quick</mark> reply."),
    ("A quick", "A quick reply.", [[0, 7], [2, 7], [0, 7]], "<mark>A quick</mark> reply."),
])
def test_context_highlight_handles_phrases_boundaries_and_invalid_positions(term, sentence, positions, expected):
    assert highlighted_sentence(StudyRecord(term=term, sentence=sentence, selected_positions=positions)) == expected


@pytest.mark.parametrize("result", [None, False, 0, "123"])
def test_unconfirmed_creation_stays_an_error(result):
    service, _ = transport_service(add_result=result)
    record = StudyRecord(term="word", explain=Explanation(definition_en="A term.", usage_en="Use it.", translation_ru="слово"))
    with pytest.raises(RuntimeError, match="не подтвердила"): service.add(record, "English")


@pytest.mark.parametrize("payload", [[], {}, {"result": None}])
def test_malformed_connect_response_is_explained(payload):
    service = AnkiService(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    with pytest.raises(RuntimeError, match="некорректный ответ"): service.connect()
