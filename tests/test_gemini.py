import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from google import genai

from golyah import gemini
from golyah.models import ContextTranslation, Enrichment, Entry, Example, Explanation, Sense, StudyRecord
from golyah.storage import Storage
from golyah.gemini_quota import GeminiQuotaError
from test_gemini_quota import quota_response


EXPLAIN = Explanation(definition_en="To undergo a situation.", usage_en="Used for personal events.",
                      translation_ru="испытывать", synonyms=["undergo"],
                      examples=[Example(en="I experienced relief.", ru="Я почувствовал облегчение.")])
CONTEXT = ContextTranslation(translation_ru="Вы испытаете это.", explanation_ru="О переживании ситуации.")


@pytest.fixture
def service(tmp_path, monkeypatch):
    calls, clients = [], []
    original_client = genai.Client

    def respond(request):
        body = json.loads(request.content) if request.content else {}
        calls.append(body)
        if request.method == "GET":
            return httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash",
                                                       "supportedGenerationMethods": ["generateContent"]}]})
        mode = json.loads(body["contents"][0]["parts"][0]["text"])["task"]
        result = Enrichment(explain=EXPLAIN, context=CONTEXT) if mode == "both" else EXPLAIN if mode == "explain" else CONTEXT
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": result.model_dump_json()}]}, "finishReason": "STOP"}]})

    def create(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        client = original_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(gemini, "get_key", lambda: "local-test-key")
    monkeypatch.setattr(gemini.genai, "Client", create)
    value = gemini.GeminiService(Storage(tmp_path / "gemini.sqlite"))
    yield value, calls, clients
    value.close()


def record():
    return StudyRecord(term="experience", sentence="You experience it.", selected_positions=[[4, 14]])


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "models/gemini-2.5-flash",
    "gemini-2.5-flash-lite", "gemini-2.5-flash-preview-09-2025"])
@pytest.mark.parametrize("mode", ["explain", "context", "both"])
def test_actual_sdk_body_disables_flash_thinking(service, model, mode):
    value, calls, _ = service
    value.storage.set_setting("gemini_model", model)
    result, returned_model = value.generate(record(), mode)
    assert returned_model == model and result
    assert calls[0]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert calls[0]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("model", ["gemini-2.5-pro", "gemini-3-flash-preview", "gemini-2.0-flash",
                                   "gemini-2.5-flash-image-preview", "custom-model"])
def test_other_models_keep_compatible_config(service, model):
    value, calls, _ = service
    value.storage.set_setting("gemini_model", model)
    value.generate(record(), "explain")
    assert "thinkingConfig" not in calls[0]["generationConfig"]


def test_request_contains_selected_sense_and_full_context(service):
    value, calls, _ = service
    item = record()
    item.sentence = "A long original sentence. " * 250
    item.entries = [Entry(word="experience", pos="v", definition_en="General definition.",
        etymology="Unrelated etymology." * 1000, extra="Long article." * 1000,
        raw={"untrusted": "raw article"}, sources=["source URL"], senses=[
            Sense(translation="опыт", examples=[Example(en="Unselected example.")]),
            Sense(translation="испытывать", definition_en="Selected definition.", examples=[
                Example(en="Relevant example.", ru="Нужный пример.")])])]
    item.sense_index = 1
    item.select_defaults()
    value.generate(item, "explain")
    payload = json.loads(calls[0]["contents"][0]["parts"][0]["text"])["data"]
    assert payload["selected_meaning"] == "испытывать"
    assert payload["sentence"] == item.sentence and payload["selected_positions"] == item.selected_positions
    assert payload["dictionary_entry"]["definition_en"] == "Selected definition."
    assert payload["dictionary_entry"]["examples"][0]["en"] == "Relevant example."
    assert "Unselected example" not in json.dumps(payload)
    assert not ({"raw", "extra", "etymology", "senses", "sources"} & payload["dictionary_entry"].keys())


def test_all_dictionary_content_does_not_change_contextual_meaning_or_cache(service):
    value, calls, _ = service
    item = record()
    item.entries = [Entry(word='experience', senses=[Sense(translation='опыт'),
        Sense(translation='испытывать', examples=[Example(en='Relevant example.')])])]
    item.sense_index = 1
    item.select_defaults()
    result, model = value.generate(item, 'both')
    gemini.apply_result(item, result, model)
    gemini.ensure_enriched(item, value)
    assert 'опыт' in item.translation and 'испытывать' in item.translation
    assert value.generate(item, 'both')[0] == result
    assert len(calls) == 1
    payload = json.loads(calls[0]['contents'][0]['parts'][0]['text'])['data']
    assert payload['selected_meaning'] == 'испытывать'


def test_missing_word_prompt_requests_meanings_and_bilingual_examples(service):
    value, calls, _ = service
    value.generate(StudyRecord(term='light'), 'explain')
    instruction = calls[0]['systemInstruction']['parts'][0]['text']
    assert 'For a word absent from the dictionary' in instruction
    assert 'matching English definitions' in instruction
    assert 'translation for each meaning' in instruction


@pytest.mark.parametrize("term,sentence,positions,kind", [
    ("Something may appear on TV", "Something may appear on TV.",
     [[0, 9], [10, 13], [14, 20], [21, 23], [24, 27]], "sentence"),
    ("may appear on TV", "Something may appear on TV.",
     [[10, 13], [14, 20], [21, 23], [24, 27]], "phrase"),
    ("Something TV", "Something may appear on TV.", [[0, 9], [24, 27]], "words"),
    ("Something may appear on TV", "", [], "phrase"),
])
def test_multiword_request_keeps_the_whole_selection(service, term, sentence, positions, kind):
    value, calls, _ = service
    item = StudyRecord(term=term, sentence=sentence, selected_positions=positions)
    value.generate(item, "explain")
    payload = json.loads(calls[0]["contents"][0]["parts"][0]["text"])["data"]
    assert payload["selected_text"] == term and payload["sentence"] == sentence
    assert payload["selected_positions"] == positions and payload["selection_kind"] == kind
    assert payload["dictionary_entry"] is None and payload["selected_meaning"] == ""


def test_new_prompt_does_not_reuse_old_single_word_translation(service):
    import hashlib
    value, calls, _ = service
    item = StudyRecord(term="Something may appear on TV", sentence="Something may appear on TV.")
    payload = gemini._payload(item)
    payload.pop("selection_kind")
    legacy_key = hashlib.sha256(json.dumps([2, "gemini-2.5-flash", "explain", payload],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    value.storage.cache_put(legacy_key, EXPLAIN.model_dump())
    value.generate(item, "explain")
    assert len(calls) == 1


@pytest.mark.parametrize("order", [("explain", "context"), ("context", "explain"), ("both",)])
@pytest.mark.parametrize("manual", ["", "Мой перевод всего предложения."])
def test_full_sentence_card_uses_complete_translation_and_preserves_edits(service, order, manual):
    value, calls, _ = service
    item = StudyRecord(term="You experience it", sentence="You experience it.", translation=manual)
    for mode in order:
        result, model = value.generate(item, mode)
        gemini.apply_result(item, result, model)
    assert item.complete and item.translation == (manual or CONTEXT.translation_ru)
    assert item.sentence_translation == CONTEXT.translation_ru
    before = len(calls)
    value.generate(item, "both")
    assert len(calls) == before


def test_phrase_card_does_not_use_translation_of_unselected_context():
    item = StudyRecord(term="experience it", sentence="You experience it.")
    gemini.apply_result(item, Enrichment(explain=EXPLAIN, context=CONTEXT), "test")
    assert item.translation == EXPLAIN.translation_ru
    assert item.sentence_translation == CONTEXT.translation_ru


def test_combined_response_populates_both_caches_even_after_apply(service):
    value, calls, _ = service
    item = record()
    result, model = value.generate(item, "both")
    gemini.apply_result(item, result, model)
    # A freshly reopened card and the populated card both use the same result.
    for source in (item, record()):
        assert value.generate(source, "explain")[0] == EXPLAIN
        assert value.generate(source, "context")[0] == CONTEXT
        assert value.generate(source, "both")[0] == result
    assert len(calls) == 1


@pytest.mark.parametrize("cached_mode", ["explain", "context"])
def test_combined_request_generates_only_missing_part(service, cached_mode):
    value, calls, clients = service
    item = record()
    value.generate(item, cached_mode)
    result, _ = value.generate(item, "both")
    assert result == Enrichment(explain=EXPLAIN, context=CONTEXT)
    tasks = [json.loads(call["contents"][0]["parts"][0]["text"])["task"] for call in calls]
    assert tasks == [cached_mode, "context" if cached_mode == "explain" else "explain"]
    assert len(clients) == 1 and not clients[0]._api_client._httpx_client.is_closed


def test_separate_results_can_be_combined_without_another_request(service):
    value, calls, _ = service
    value.generate(record(), "explain")
    value.generate(record(), "context")
    assert value.generate(record(), "both")[0] == Enrichment(explain=EXPLAIN, context=CONTEXT)
    assert len(calls) == 2


def test_cache_survives_service_restart_and_requires_no_key(service, monkeypatch):
    value, calls, _ = service
    value.generate(record(), "both")
    value.close()
    monkeypatch.setattr(gemini, "get_key", lambda: "")
    reopened = gemini.GeminiService(value.storage)
    try:
        assert reopened.generate(record(), "context")[0] == CONTEXT
        assert not reopened._session and len(calls) == 1
    finally:
        reopened.close()


def test_cache_does_not_mix_models_context_meanings_or_positions(service):
    value, calls, _ = service
    item = record()
    value.generate(item, "explain")
    for changes in ({"sentence": "Different context."}, {"translation": "опыт"},
                    {"selected_positions": [[0, 3], [4, 14]]}):
        value.generate(item.model_copy(update=changes), "explain")
    value.storage.set_setting("gemini_model", "gemini-2.5-pro")
    value.generate(item, "explain")
    assert len(calls) == 5


def test_without_sentence_requests_only_explain(service):
    value, calls, _ = service
    item = StudyRecord(term="experience")
    result, _ = value.generate(item, "both")
    assert result.context is None and result.explain == EXPLAIN
    assert json.loads(calls[0]["contents"][0]["parts"][0]["text"])["task"] == "explain"
    with pytest.raises(ValueError, match="исходное предложение"):
        value.generate(item, "context")
    assert len(calls) == 1


def test_cancelled_request_never_uses_cache_or_calls_api(service):
    value, calls, _ = service
    value.generate(record(), "both")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ValueError, match="отменён"):
        value.generate(record(), "both", cancel)
    assert len(calls) == 1


def test_key_rotation_and_close_wait_for_active_users(service, monkeypatch):
    value, _, clients = service
    with value.client() as first:
        monkeypatch.setattr(gemini, "get_key", lambda: "another-test-key")
        with value.client() as second:
            assert second is not first and len(clients) == 2
            assert not first._api_client._httpx_client.is_closed
        assert not second._api_client._httpx_client.is_closed
    assert first._api_client._httpx_client.is_closed
    with value.client() as active:
        value.close()
        assert not active._api_client._httpx_client.is_closed
        with pytest.raises(ValueError, match="закрывается"):
            with value.client():
                pass
    assert active._api_client._httpx_client.is_closed


def test_deleted_key_retires_existing_client(service, monkeypatch):
    value, _, clients = service
    with value.client():
        pass
    monkeypatch.setattr(gemini, "get_key", lambda: "")
    with pytest.raises(ValueError, match="API-ключ"):
        with value.client():
            pass
    assert clients[0]._api_client._httpx_client.is_closed


def test_listing_models_and_generate_reuse_same_client(service):
    value, calls, clients = service
    assert value.models() == ["gemini-2.5-flash"]
    value.generate(record(), "explain")
    assert len(calls) == 2 and len(clients) == 1


@pytest.mark.parametrize("mode,text", [("both", Enrichment(explain=EXPLAIN).model_dump_json()),
    ("explain", '{"definition_en":"","usage_en":"Example","translation_ru":"пример"}'),
    ("context", "incomplete JSON")])
def test_incomplete_response_never_enters_cache(service, monkeypatch, mode, text):
    value, _, _ = service
    with value.client() as client:
        monkeypatch.setattr(client.models, "generate_content", lambda **kwargs: SimpleNamespace(text=text))
    with pytest.raises(ValueError):
        value.generate(record(), mode)
    with value.storage.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0


def test_concurrent_requests_share_client_without_closing_it(service):
    value, _, clients = service
    barrier = threading.Barrier(3)
    identities, errors = [], []

    def work():
        try:
            with value.client() as client:
                identities.append(id(client))
                barrier.wait(3)
                barrier.wait(3)
                assert not client._api_client._httpx_client.is_closed
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(3)
    assert len(clients) == 1 and len(set(identities)) == 1
    barrier.wait(3)
    for thread in threads:
        thread.join(3)
    assert not errors and all(not thread.is_alive() for thread in threads)


def test_cancel_after_response_does_not_cache_it(service, monkeypatch):
    value, calls, _ = service
    cancel = threading.Event()
    with value.client() as client:
        original = client.models.generate_content
        def generate(**kwargs):
            response = original(**kwargs)
            cancel.set()
            return response
        monkeypatch.setattr(client.models, "generate_content", generate)
    with pytest.raises(ValueError, match="отменён"):
        value.generate(record(), "both", cancel)
    assert len(calls) == 1
    with value.storage.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0


def limit_models(service, models, code=429):
    value, calls, _ = service
    with value.client() as client:
        transport = client._api_client._httpx_client._transport
        original = transport.handler
        def respond(request):
            model = request.url.path.rsplit("/", 1)[-1].split(":")[0]
            if model in models:
                calls.append(json.loads(request.content))
                body = quota_response() if code == 429 else {"error": {"code": code, "status": "PERMISSION_DENIED"}}
                return httpx.Response(code, json=body)
            return original(request)
        transport.handler = respond


def test_429_switches_once_to_flash_lite_and_returns_actual_model(service):
    value, calls, clients = service
    limit_models(service, {"gemini-2.5-flash"})
    result, model = value.generate(record(), "both")
    assert model == "gemini-3.5-flash-lite" and result.explain == EXPLAIN and result.context == CONTEXT
    assert len(calls) == 2 and len(clients) == 1
    assert calls[1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert calls[1]["generationConfig"]["temperature"] == 1.0
    assert value.generate(record(), "both") == (result, model)
    assert len(calls) == 2  # Primary is paused; the fallback answer is cached.


def test_exhausted_primary_is_skipped_for_other_words(service):
    value, calls, _ = service
    limit_models(service, {"gemini-2.5-flash"})
    value.generate(record(), "explain")
    value.generate(record().model_copy(update={"term": "other"}), "context")
    assert len(calls) == 3


def test_both_models_exhausted_do_not_loop_or_repeat_http(service):
    value, calls, _ = service
    limit_models(service, {"gemini-2.5-flash", "gemini-3.5-flash-lite"})
    for _ in range(3):
        with pytest.raises(GeminiQuotaError, match="Основная и резервная"):
            value.generate(record(), "context")
    assert len(calls) == 2
    with value.storage.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0


def test_quota_pause_survives_restart(service):
    value, calls, _ = service
    limit_models(service, {"gemini-2.5-flash", "gemini-3.5-flash-lite"})
    with pytest.raises(GeminiQuotaError):
        value.generate(record(), "both")
    reopened = gemini.GeminiService(value.storage)
    try:
        with pytest.raises(GeminiQuotaError):
            reopened.generate(record(), "both")
        assert not reopened._session and len(calls) == 2
    finally:
        reopened.close()


def test_fallback_can_be_disabled_and_cache_remains_usable(service):
    value, calls, _ = service
    value.generate(record(), "both")
    value.storage.set_setting("gemini_fallback", False)
    limit_models(service, {"gemini-2.5-flash"})
    with pytest.raises(GeminiQuotaError, match="Дневной лимит"):
        value.generate(record().model_copy(update={"term": "other"}), "both")
    assert value.generate(record(), "context")[0] == CONTEXT
    assert len(calls) == 2


def test_expired_pause_allows_a_manual_request_again(service):
    value, calls, clients = service
    limit_models(service, {"gemini-2.5-flash"})
    value.storage.set_setting("gemini_fallback", False)
    with pytest.raises(GeminiQuotaError):
        value.generate(record(), "explain")
    key = value._quota_key("gemini-2.5-flash", "local-test-key")
    state = value.storage.setting(key)
    state["retry_at"] = 1
    value.storage.set_setting(key, state)
    clients[0]._api_client._httpx_client._transport.handler = lambda request: httpx.Response(200, json={
        "candidates": [{"content": {"parts": [{"text": EXPLAIN.model_dump_json()}]}}]})
    assert value.generate(record(), "explain")[0] == EXPLAIN


def test_api_key_change_does_not_inherit_other_project_pause(service, monkeypatch):
    value, calls, _ = service
    value.storage.set_setting("gemini_fallback", False)
    limit_models(service, {"gemini-2.5-flash"})
    with pytest.raises(GeminiQuotaError):
        value.generate(record(), "explain")
    monkeypatch.setattr(gemini, "get_key", lambda: "different-project-test-key")
    assert value.generate(record(), "explain")[0] == EXPLAIN
    assert len(calls) == 2


@pytest.mark.parametrize("model,code", [("gemini-2.5-pro", 429), ("gemini-3.5-flash-lite", 429),
                                     ("gemini-2.5-flash", 403)])
def test_other_models_and_non_quota_errors_do_not_trigger_fallback(service, model, code):
    value, calls, _ = service
    value.storage.set_setting("gemini_model", model)
    limit_models(service, {model}, code)
    with pytest.raises(Exception):
        value.generate(record(), "explain")
    assert len(calls) == 1


@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_transient_api_error_retries_once_and_caches_valid_translation(service, code):
    value, calls, clients = service
    with value.client() as client:
        transport = client._api_client._httpx_client._transport
        original = transport.handler
        failures = []
        def respond(request):
            if not failures:
                failures.append(code)
                return httpx.Response(code, json={"error": {"code": code, "status": "UNAVAILABLE"}})
            return original(request)
        transport.handler = respond
    assert value.generate(record(), "both")[0] == Enrichment(explain=EXPLAIN, context=CONTEXT)
    assert value.generate(record(), "both")[0].context == CONTEXT
    assert len(failures) == len(calls) == len(clients) == 1
    diagnostic = value.storage.setting("gemini_last_error")
    assert diagnostic["code"] == code
    assert "local-test-key" not in json.dumps(diagnostic) and "experience" not in json.dumps(diagnostic)


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError])
def test_transient_network_failure_retries_same_complete_selection(service, error_type):
    value, calls, _ = service
    item = StudyRecord(term="The image is there again", sentence="...The image is there again.")
    with value.client() as client:
        transport = client._api_client._httpx_client._transport
        original = transport.handler
        attempts = []
        def respond(request):
            attempts.append(json.loads(request.content))
            if len(attempts) == 1:
                raise error_type("temporary failure", request=request)
            return original(request)
        transport.handler = respond
    assert value.generate(item, "explain")[0] == EXPLAIN
    assert len(attempts) == 2 and attempts[0]["contents"] == attempts[1]["contents"]
    assert json.loads(calls[0]["contents"][0]["parts"][0]["text"])["data"]["selected_text"] == item.term


def test_persistent_server_failure_stops_after_one_retry_without_caching(service):
    value, _, _ = service
    attempts = []
    with value.client() as client:
        def respond(request):
            attempts.append(request)
            return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})
        client._api_client._httpx_client._transport.handler = respond
    with pytest.raises(gemini.APIError):
        value.generate(record(), "both")
    assert len(attempts) == 2
    with value.storage.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0


@pytest.mark.parametrize("bad_text", ["", "incomplete JSON", '{"translation_ru":" "}',
    Enrichment(explain=EXPLAIN).model_dump_json(),
    Enrichment(explain=EXPLAIN, context=ContextTranslation(translation_ru=" \n", explanation_ru=" ")).model_dump_json()])
def test_empty_or_incomplete_answer_is_retried_before_caching(service, bad_text):
    value, calls, _ = service
    with value.client() as client:
        transport = client._api_client._httpx_client._transport
        original = transport.handler
        responses = []
        def respond(request):
            responses.append(request)
            if len(responses) == 1:
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": bad_text}]},
                                                                 "finishReason": "STOP"}]})
            return original(request)
        transport.handler = respond
    assert value.generate(record(), "both")[0] == Enrichment(explain=EXPLAIN, context=CONTEXT)
    assert len(responses) == 2 and len(calls) == 1


def test_truncated_answer_retries_with_more_output_tokens(service):
    value, calls, _ = service
    bodies = []
    with value.client() as client:
        transport = client._api_client._httpx_client._transport
        original = transport.handler
        def respond(request):
            bodies.append(json.loads(request.content))
            if len(bodies) == 1:
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{"}]},
                                                                 "finishReason": "MAX_TOKENS"}]})
            return original(request)
        transport.handler = respond
    assert value.generate(record(), "explain")[0] == EXPLAIN
    assert [body["generationConfig"]["maxOutputTokens"] for body in bodies] == [2400, 4800]


def test_blocked_answer_reports_reason_without_retry_or_cache(service):
    value, _, _ = service
    attempts = []
    with value.client() as client:
        def respond(request):
            attempts.append(request)
            return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
        client._api_client._httpx_client._transport.handler = respond
    with pytest.raises(gemini.GeminiResponseError, match="отклонила"):
        value.generate(record(), "context")
    assert len(attempts) == 1 and value.storage.setting("gemini_last_error")["reason"] == "prompt_blocked:SAFETY"


def test_cancellation_during_retry_delay_prevents_another_request(service):
    value, _, _ = service
    cancel, attempts = threading.Event(), []
    timer = threading.Timer(.05, cancel.set)
    with value.client() as client:
        def respond(request):
            attempts.append(request)
            timer.start()
            raise httpx.ReadTimeout("temporary failure", request=request)
        client._api_client._httpx_client._transport.handler = respond
    try:
        with pytest.raises(ValueError, match="отменён"):
            value.generate(record(), "both", cancel)
        assert len(attempts) == 1
        with value.storage.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
    finally:
        timer.join(1)


def test_quota_fallback_uses_remaining_shared_deadline(service, monkeypatch):
    value, calls, _ = service
    elapsed, timeouts = [0.0], []
    real_time = gemini.time
    monkeypatch.setattr(gemini, "time", SimpleNamespace(monotonic=lambda: elapsed[0], time=real_time.time,
        sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)))
    with value.client() as client:
        transport = client._api_client._httpx_client._transport
        original = transport.handler
        def respond(request):
            timeouts.append(request.extensions["timeout"]["read"])
            if len(timeouts) == 1:
                elapsed[0] = 35.0
                return httpx.Response(429, json=quota_response())
            return original(request)
        transport.handler = respond
    assert value.generate(record(), "both")[1] == gemini.FALLBACK_MODEL
    assert timeouts == [30.0, 25.0] and len(calls) == 1


def test_expired_deadline_never_sends_another_request(service, monkeypatch):
    value, _, _ = service
    monkeypatch.setattr(gemini, "REQUEST_DEADLINE_SECONDS", 0)
    with pytest.raises(httpx.TimeoutException):
        value.generate(record(), "both")
    assert value._session is None


def test_retry_and_quota_fallback_share_one_retry_and_deadline(service, monkeypatch):
    value, _, _ = service
    elapsed, timeouts = [0.0], []
    real_time = gemini.time
    monkeypatch.setattr(gemini, "time", SimpleNamespace(monotonic=lambda: elapsed[0], time=real_time.time,
        sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)))
    with value.client() as client:
        def respond(request):
            timeouts.append(request.extensions["timeout"]["read"])
            elapsed[0] += 20
            if len(timeouts) == 2:
                return httpx.Response(429, json=quota_response())
            return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})
        client._api_client._httpx_client._transport.handler = respond
    with pytest.raises(gemini.APIError) as error:
        value.generate(record(), "both")
    assert error.value.code == 503
    assert timeouts == [30.0, 30.0, 19.5]
    assert value.storage.setting("gemini_last_error")["model"] == gemini.FALLBACK_MODEL
