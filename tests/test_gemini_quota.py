import time
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from google.genai.errors import ClientError

from golyah.gemini_quota import GeminiQuotaError, _daily_delay, quota_error


def test_quota_message_works_with_non_russian_time_locale():
    import locale
    previous = locale.setlocale(locale.LC_TIME)
    try:
        locale.setlocale(locale.LC_TIME, 'C')
        message = str(GeminiQuotaError('gemini-test', 'daily', 100000))
        assert 'Дневной лимит' in message and ' в ' in message
    finally:
        locale.setlocale(locale.LC_TIME, previous)


def quota_response(daily=True, delay="10313.28855s"):
    metric = "generate_content_free_tier_requests_per_day" if daily else "generate_content_requests_per_minute"
    return {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": f"Quota exceeded for metric: {metric}, limit: 20, model: gemini-2.5-flash. secret-key",
        "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaMetric": "generativelanguage.googleapis.com/" + metric,
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel" if daily else "GenerateRequestsPerMinute",
            "quotaValue": "20"}]}, {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}}


def test_daily_error_has_russian_explanation_and_server_retry_time():
    result = quota_error(ClientError(429, quota_response()), "gemini-2.5-flash", now=100000)
    assert result.kind == "daily" and result.limit == 20
    assert result.retry_at == pytest.approx(110313.28855)
    assert "Дневной лимит" in str(result) and "20" in str(result)
    assert "secret-key" not in str(result) and "RESOURCE_EXHAUSTED" not in str(result)
    assert "type.googleapis" not in str(result) and "настройках" in str(result)
    assert GeminiQuotaError(**result.state()).retry_at == result.retry_at


@pytest.mark.parametrize("delay,seconds", [("1h2m3.5s", 3723.5), ("45s", 45),
    ({"seconds": "2", "nanos": 500000000}, 2.5), ("0s", 1)])
def test_google_retry_duration_variants(delay, seconds):
    result = quota_error(ClientError(429, quota_response(False, delay)), "test", now=100000)
    assert result.kind == "temporary" and result.retry_at == pytest.approx(100000 + seconds)


def test_daily_error_without_hint_uses_pacific_midnight_including_dst():
    body = quota_response()
    body["error"]["details"].pop()
    for now, reset in [(datetime(2026, 10, 5, 21, tzinfo=timezone.utc), datetime(2026, 10, 6, 7, tzinfo=timezone.utc)),
                       (datetime(2026, 12, 5, 21, tzinfo=timezone.utc), datetime(2026, 12, 6, 8, tzinfo=timezone.utc))]:
        result = quota_error(ClientError(429, body), "gemini-2.5-flash", now=now.timestamp())
        assert result.retry_at == reset.timestamp()


def test_temporary_error_honors_retry_after_header():
    error = ClientError(429, {"error": {"code": 429, "message": "Too many requests"}},
                        httpx.Response(429, headers={"Retry-After": "19"}))
    assert quota_error(error, "test", now=100000).retry_at == 100019


def test_legacy_truncated_sdk_message_is_readable():
    text = ("429 RESOURCE_EXHAUSTED. {'error': {'message': 'Quota exceeded for metric: "
            "generate_content_free_tier_requests_per_day, limit: 20, model: gemini-2.5-flash. "
            "Please retry in 2h51m53.28855s.'")
    result = quota_error(text, "gemini-2.5-flash", now=100000)
    assert result.kind == "daily" and result.retry_at == pytest.approx(110313.28855)
    assert "{'error'" not in str(result)


@pytest.mark.parametrize("code", [400, 401, 403, 404, 500])
def test_other_http_errors_are_not_treated_as_quota(code):
    assert quota_error(ClientError(code, {"message": "429 RESOURCE_EXHAUSTED appears in quoted data"}), "test") is None


def test_unstructured_429_has_bounded_pause():
    result = quota_error(ClientError(429, {"message": "Too many requests"}), "test", now=100000)
    assert result.kind == "temporary" and result.retry_at == 100060


def test_invalid_delay_and_model_cannot_leak_server_text():
    result = quota_error(ClientError(429, quota_response(False, "999999999999999999999s")), "unsafe/url?key=secret", now=100000)
    assert result.retry_at <= 100000 + 7 * 86400
    assert "secret" not in str(result) and "выбранной модели" in str(result)
