from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any


def clean_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text.replace("\u200e", "").replace("\u200f", "")).strip()


def normalized_key(value: Any) -> str:
    return re.sub(r"[^0-9a-zא-ת]+", " ", clean_text(value).lower()).strip()


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        return datetime.fromtimestamp(stamp, tz=timezone.utc).date()
    text = clean_text(value)
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        return date(year, month, day)
    for candidate in (text[:10], text[:19]):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return None


def record_identity(city_id: str, application_number: str | None, fallback: dict[str, Any]) -> str:
    if clean_text(application_number):
        return f"application:{normalized_key(application_number)}"
    canonical = json.dumps(fallback, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "hash:" + hashlib.sha256(f"{city_id}|{canonical}".encode()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def in_range(value: date | None, date_from: date, date_to: date) -> bool:
    return value is not None and date_from <= value <= date_to
