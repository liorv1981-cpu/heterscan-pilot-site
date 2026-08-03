from __future__ import annotations

from typing import Any

from heterscan.supabase import SupabaseRepository


class FakeResponse:
    def __init__(self, data: Any) -> None:
        self.data = data

    def json(self) -> Any:
        return self.data


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
        return FakeResponse([{
            "units_completed": 4383,
            "applications_found": 12,
            "permits_found": 4,
            "units_failed": 0,
            "units_requires_review": 0,
        }])

    repository._rest = fake_rest  # type: ignore[method-assign]

    assert repository.progress_counts("run-1") == {
        "units_completed": 4383,
        "applications_found": 12,
        "permits_found": 4,
    }
