from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx

from heterscan import supabase as supabase_module
from heterscan.domain import ApplicationRecord, DiscoveredUnit
from heterscan.supabase import SupabaseRepository, _json_safe


class FakeResponse:
    def __init__(self, data: Any) -> None:
        self.data = data

    def json(self) -> Any:
        return self.data

    def raise_for_status(self) -> None:
        return None


def test_rest_retries_transient_connection_failures(monkeypatch) -> None:
    repository = SupabaseRepository.__new__(SupabaseRepository)
    repository.url = "https://example.supabase.co"
    attempts = 0
    delays: list[float] = []

    class FakeClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> FakeResponse:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise httpx.ConnectError("temporary DNS failure")
            return FakeResponse({"ok": True})

    repository.client = FakeClient()  # type: ignore[assignment]
    monkeypatch.setattr(supabase_module.time, "sleep", delays.append)

    assert repository._rest("GET", "runs?limit=1").json() == {"ok": True}
    assert attempts == 3
    assert delays == [0.5, 1.0]


def test_json_safe_serializes_nested_dates_and_tuples() -> None:
    value = {
        "event": (date(2025, 7, 1), "issued"),
        "nested": [{"seen_at": datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)}],
    }

    assert _json_safe(value) == {
        "event": ["2025-07-01", "issued"],
        "nested": [{"seen_at": "2026-08-03T04:00:00+00:00"}],
    }


def test_get_all_pages_past_supabase_default_limit() -> None:
    repository = SupabaseRepository.__new__(SupabaseRepository)
    calls: list[str] = []

    def fake_rest(method: str, path: str, **_: Any) -> FakeResponse:
        calls.append(path)
        offset = int(path.split("offset=")[1])
        size = 1000 if offset < 4000 else 383
        return FakeResponse([{"sequence": offset + index} for index in range(size)])

    repository._rest = fake_rest  # type: ignore[method-assign]

    rows = repository._get_all("run_units?run_id=eq.test&select=*&order=sequence")

    assert len(rows) == 4383
    assert rows[-1]["sequence"] == 4382
    assert len(calls) == 5
    assert calls[-1].endswith("limit=1000&offset=4000")


def test_progress_summary_uses_database_aggregate() -> None:
    repository = SupabaseRepository.__new__(SupabaseRepository)

    def fake_rest(method: str, path: str, **kwargs: Any) -> FakeResponse:
        assert method == "POST"
        assert path == "rpc/get_run_progress"
        assert kwargs["json"] == {"p_run_id": "run-1"}
        return FakeResponse(
            [
                {
                    "units_completed": 4383,
                    "applications_found": 12,
                    "permits_found": 4,
                    "units_failed": 0,
                    "units_requires_review": 0,
                }
            ]
        )

    repository._rest = fake_rest  # type: ignore[method-assign]

    assert repository.progress_counts("run-1") == {
        "units_completed": 4383,
        "applications_found": 12,
        "permits_found": 4,
    }


def test_cancellation_requested_reads_persistent_run_flag() -> None:
    repository = SupabaseRepository.__new__(SupabaseRepository)

    def fake_rest(method: str, path: str, **_: Any) -> FakeResponse:
        assert method == "GET"
        assert path == "runs?id=eq.run-1&select=cancel_requested_at"
        return FakeResponse([{"cancel_requested_at": "2026-08-03T20:00:00+00:00"}])

    repository._rest = fake_rest  # type: ignore[method-assign]

    assert repository.cancellation_requested("run-1") is True


def test_save_applications_uses_four_bulk_requests_for_multiple_records() -> None:
    repository = SupabaseRepository.__new__(SupabaseRepository)
    calls: list[tuple[str, str, Any]] = []
    records = [
        ApplicationRecord(
            city_id="7900",
            application_number=str(number),
            address=f"רחוב {number}",
            source_url=f"https://example.test/{number}",
            source_reference=str(number),
            adapter_name="complot",
            adapter_version="0.1.0",
            raw_data={"number": number},
            submission_date=date(2025, 7, number),
            is_approved=True,
            approval_date=date(2025, 7, number + 1),
        )
        for number in (1, 2)
    ]

    def fake_rest(method: str, path: str, **kwargs: Any) -> FakeResponse:
        calls.append((method, path, kwargs.get("json")))
        if path.startswith("applications?"):
            return FakeResponse(
                [
                    {
                        "id": f"app-{index}",
                        "city_id": row["city_id"],
                        "identity_key": row["identity_key"],
                        "content_hash": row["content_hash"],
                    }
                    for index, row in enumerate(kwargs["json"], start=1)
                ]
            )
        return FakeResponse([])

    repository._rest = fake_rest  # type: ignore[method-assign]

    saved = repository.save_applications("run-1", records)

    assert saved == ["app-1", "app-2"]
    assert len(calls) == 4
    assert all(call[0] == "POST" for call in calls)
    assert [len(call[2]) for call in calls] == [2, 2, 2, 2]


def test_release_units_returns_unprocessed_claims_to_pending() -> None:
    repository = SupabaseRepository.__new__(SupabaseRepository)
    calls: list[tuple[str, str, Any]] = []

    def fake_rest(method: str, path: str, **kwargs: Any) -> FakeResponse:
        calls.append((method, path, kwargs["json"]))
        return FakeResponse([])

    repository._rest = fake_rest  # type: ignore[method-assign]

    repository.release_units(["unit-1", "unit-2"])

    assert calls == [
        (
            "PATCH",
            "run_units?id=in.(unit-1,unit-2)&status=eq.processing",
            {"status": "pending", "claimed_by": None, "claimed_at": None},
        )
    ]


def test_enqueue_units_uses_one_rpc_call() -> None:
    repository = SupabaseRepository.__new__(SupabaseRepository)
    calls: list[tuple[str, str, Any]] = []

    def fake_rest(method: str, path: str, **kwargs: Any) -> FakeResponse:
        calls.append((method, path, kwargs["json"]))
        return FakeResponse(2)

    repository._rest = fake_rest  # type: ignore[method-assign]
    inserted = repository.enqueue_units(
        "run-1",
        [
            DiscoveredUnit("request:1", {"mode": "request", "seen": date(2025, 7, 1)}),
            DiscoveredUnit("request:2", {"mode": "request"}),
        ],
    )

    assert inserted == 2
    assert calls == [
        (
            "POST",
            "rpc/enqueue_run_units",
            {
                "p_run_id": "run-1",
                "p_units": [
                    {
                        "unit_key": "request:1",
                        "unit_payload": {"mode": "request", "seen": "2025-07-01"},
                    },
                    {"unit_key": "request:2", "unit_payload": {"mode": "request"}},
                ],
            },
        )
    ]


def test_finish_units_batches_mixed_outcomes_in_one_rpc_call() -> None:
    repository = SupabaseRepository.__new__(SupabaseRepository)
    calls: list[tuple[str, str, Any]] = []
    updates = [
        {"id": "unit-1", "status": "completed", "result_count": 3},
        {"id": "unit-2", "status": "failed", "error_message": "source error"},
    ]

    def fake_rest(method: str, path: str, **kwargs: Any) -> FakeResponse:
        calls.append((method, path, kwargs["json"]))
        return FakeResponse(2)

    repository._rest = fake_rest  # type: ignore[method-assign]

    assert repository.finish_units(updates) == 2
    assert calls == [("POST", "rpc/finish_run_units", {"p_updates": updates})]
