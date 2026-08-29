import threading
import time
from datetime import date
from types import SimpleNamespace

from heterscan.domain import SearchUnit
from heterscan.runner import _claim_limit, _collect_wave, _wait_for_source_cooldown


def test_complot_claims_twenty_units_for_batched_parallel_work() -> None:
    assert _claim_limit("complot") == 20


def test_city_wide_adapter_claims_one_unit() -> None:
    assert _claim_limit("tel_aviv") == 1


def test_jerusalem_keeps_its_parallel_batch() -> None:
    assert _claim_limit("jerusalem") == 20


def test_collection_drops_records_outside_the_requested_range() -> None:
    class FakeAdapter:
        name = "tel_aviv"

        def collect(self, _unit, _date_from, _date_to):
            return [
                SimpleNamespace(submission_date=date(2025, 6, 30)),
                SimpleNamespace(submission_date=date(2025, 7, 1)),
                SimpleNamespace(submission_date=date(2025, 7, 31)),
                SimpleNamespace(submission_date=date(2025, 8, 1)),
                SimpleNamespace(submission_date=None),
            ]

    unit = SearchUnit("1", "run-1", 1, "city-wide", {})
    [(returned_unit, records, error)] = _collect_wave(
        FakeAdapter(), [unit], date(2025, 7, 1), date(2025, 7, 31)
    )

    assert returned_unit is unit
    assert error is None
    assert [record.submission_date for record in records] == [date(2025, 7, 1), date(2025, 7, 31)]


def test_complot_collection_respects_adaptive_parallelism() -> None:
    class FakeAdapter:
        name = "complot"

        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0
            self.lock = threading.Lock()

        def parallelism(self) -> int:
            return 2

        def collect(self, unit, _date_from, _date_to):
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return [SimpleNamespace(submission_date=date(2025, 7, 15), value=unit.unit_key)]

    adapter = FakeAdapter()
    units = [SearchUnit(str(index), "run-1", index, f"street:{index}", {}) for index in range(4)]

    results = _collect_wave(adapter, units, date(2025, 7, 1), date(2025, 7, 31))

    assert len(results) == 4
    assert adapter.maximum_active == 2


def test_source_cooldown_stops_immediately_when_cancelled() -> None:
    class FakeRepository:
        def cancellation_requested(self, _run_id):
            return True

        def update_run(self, _run_id, _fields):
            raise AssertionError("cancelled cooldown must not write a heartbeat")

    assert not _wait_for_source_cooldown(FakeRepository(), "run-1", 60, poll_seconds=0.001)
