from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

Confidence = Literal["low", "medium", "high"]


@dataclass(slots=True)
class SearchUnit:
    id: str
    run_id: str
    sequence: int
    unit_key: str
    payload: dict[str, Any]


@dataclass(slots=True)
class ApplicationRecord:
    city_id: str
    application_number: str | None
    address: str | None
    source_url: str
    source_reference: str | None
    adapter_name: str
    adapter_version: str
    raw_data: dict[str, Any]
    building_file_number: str | None = None
    street_name: str | None = None
    house_number: str | None = None
    block_number: str | None = None
    parcel_number: str | None = None
    application_type: str | None = None
    work_description: str | None = None
    submission_date: date | None = None
    approval_date: date | None = None
    is_approved: bool = False
    approval_confidence: Confidence | None = None
    permit_number: str | None = None
    permit_issue_date: date | None = None
    permit_status_original: str | None = None
    is_permit_issued: bool = False
    permit_confidence: Confidence | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_database(self, *, run_id: str, identity_key: str, content_hash: str) -> dict[str, Any]:
        data = asdict(self)
        data.pop("evidence")
        for key in ("submission_date", "approval_date", "permit_issue_date"):
            value = data[key]
            data[key] = value.isoformat() if value else None
        data.update(
            identity_key=identity_key,
            content_hash=content_hash,
            last_run_id=run_id,
            last_seen_at=datetime.now(timezone.utc).isoformat(),
        )
        return data


class AdapterReviewRequired(RuntimeError):
    """The public source blocked or challenged the request; no bypass is attempted."""


class AdapterRateLimited(RuntimeError):
    """The source asked the worker to pause before safely retrying the unit."""

    def __init__(self, message: str, *, retry_after_seconds: float) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
