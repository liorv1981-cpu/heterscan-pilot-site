import threading
import time
from datetime import date
from types import SimpleNamespace

from heterscan.domain import AdapterReviewRequired, DiscoveredUnit, DiscoveryResult, SearchUnit
from heterscan.runner import _claim_limit, _collect_wave, _coverage_verification, _expand_discovery, _final_status, _wait_for_source_cooldown


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


def test_collection_preserves_discovered_work_units() -> None:
    discovered = DiscoveryResult(units=[DiscoveredUnit("request:20260001", {"mode": "request"})])

    class FakeAdapter:
        name = "complot"

        def parallelism(self):
            return 1

        def collect(self, _unit, _date_from, _date_to):
            return discovered

    unit = SearchUnit("1", "run-1", 1, "discover-prefix:2026", {})
    [(returned_unit, result, error)] = _collect_wave(
        FakeAdapter(), [unit], date(2026, 1, 1), date(2026, 12, 31)
    )

    assert returned_unit is unit
    assert result is discovered
    assert error is None


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


def test_empty_run_cannot_complete_as_verified_zero() -> None:
    assert _final_status({"units_requires_review": 0, "units_failed": 0, "applications_found": 0}) == "requires_review"
    assert _final_status({"units_requires_review": 0, "units_failed": 0, "applications_found": 1}) == "completed"
    assert _coverage_verification("requires_review", 0) == "zero_not_verified"
    assert _coverage_verification("completed", 1) == "not_verified"


def test_uncertain_discovery_queues_candidates_before_review() -> None:
    class Repository:
        def __init__(self):
            self.units = []

        def enqueue_units(self, _run_id, units):
            self.units.extend(units)
            return len(units)

    repository = Repository()
    unit = SearchUnit("u", "r", 1, "discover-prefix:2026", {})
    result = DiscoveryResult(
        units=[DiscoveredUnit("request:20260005", {"mode": "request"})],
        review_reason="unexpected request-number length",
    )
    inserted, (returned_unit, records, error) = _expand_discovery(repository, "r", unit, result)
    assert inserted == 1 and repository.units == result.units
    assert returned_unit is unit and records == []
    assert isinstance(error, AdapterReviewRequired)
