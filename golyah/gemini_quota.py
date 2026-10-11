from __future__ import annotations

import math
import re
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class GeminiQuotaError(ValueError):
    def __init__(self, model: str, kind: str, retry_at: float, limit: int | None = None):
        self.model, self.kind, self.retry_at, self.limit = model, kind, retry_at, limit
        self.prefix = ""
        super().__init__(self.__str__())

    def __str__(self):
        model = self.model.removeprefix("models/")
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", model):
            model = "выбранной модели"
        local = datetime.fromtimestamp(self.retry_at).astimezone()
        # Windows strftime encodes its format using LC_TIME. Keep Russian text
        # outside that API so quota messages work on non-Russian Windows too.
        when = f"{local.day:02d}.{local.month:02d} в {local.hour:02d}:{local.minute:02d}"
        if self.kind == "daily":
            count = f" (лимит: {self.limit})" if self.limit else ""
            reason = f"Дневной лимит {model} исчерпан{count}."
        else:
            reason = f"Gemini временно ограничила запросы к {model}."
        return (self.prefix + reason + f" Повторить можно примерно {when}. "
                "Можно выбрать другую модель в настройках. Словарь и готовые ответы доступны.")

    def state(self):
        return {"model": self.model, "kind": self.kind, "retry_at": self.retry_at, "limit": self.limit}


def _seconds(value) -> float | None:
    if isinstance(value, dict):
        try:
            return float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
        except (ValueError, TypeError):
            return None
    if not isinstance(value, str):
        return None
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", value)
    if not matches:
        return None
    return sum(float(number) * {"h": 3600, "m": 60, "s": 1}[unit] for number, unit in matches)


def _daily_delay(now: float) -> float:
    try:
        pacific = datetime.fromtimestamp(now, ZoneInfo("America/Los_Angeles"))
        midnight = (pacific + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight.timestamp() - now
    except ZoneInfoNotFoundError:
        return 3600  # A conservative pause; the next manual request rechecks Google.


def quota_error(error, model: str, now: float | None = None) -> GeminiQuotaError | None:
    if isinstance(error, GeminiQuotaError):
        return error
    text = str(error)[:12000]
    code = getattr(error, "code", None)
    if (code is not None and code != 429) or (code is None and not re.search(r"\b429\s+RESOURCE_EXHAUSTED\b", text)):
        return None
    now = time.time() if now is None else now
    details = getattr(error, "details", {})
    if isinstance(details, dict):
        details = details.get("error", details)
    items = details.get("details", []) if isinstance(details, dict) else []
    daily = bool(re.search(r"per[_ ]?day", text, re.I))
    limit = None
    delay = None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("@type", "")).endswith("RetryInfo"):
            delay = _seconds(item.get("retryDelay"))
        for violation in item.get("violations", []) if isinstance(item.get("violations", []), list) else []:
            if not isinstance(violation, dict):
                continue
            metric = str(violation.get("quotaMetric", "")) + str(violation.get("quotaId", ""))
            daily = daily or bool(re.search(r"per[_ ]?day", metric, re.I))
            try:
                limit = int(violation["quotaValue"])
            except (KeyError, TypeError, ValueError):
                pass
    if limit is None:
        match = re.search(r"\blimit:\s*(\d+)\b", text)
        limit = int(match.group(1)) if match else None
    if delay is None:
        match = re.search(r"retry in\s+([\dhms. ]+)", text, re.I)
        delay = _seconds(match.group(1)) if match else None
    if delay is None:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        retry = headers.get("retry-after")
        if retry:
            try:
                delay = float(retry)
            except (TypeError, ValueError):
                try:
                    delay = parsedate_to_datetime(retry).timestamp() - now
                except (TypeError, ValueError, OverflowError):
                    pass
    if delay is None or not math.isfinite(delay):
        delay = _daily_delay(now) if daily else 60
    return GeminiQuotaError(model, "daily" if daily else "temporary", now + min(7 * 86400, max(1, delay)), limit)
