import threading
import time
from datetime import date

from heterscan.domain import SearchUnit
from heterscan.runner import _claim_limit, _collect_wave


def test_complot_claims_twenty_units_for_batched_parallel_work() -> None:
    assert _claim_limit("complot") == 20


def test_city_wide_adapter_claims_one_unit() -> None:
    assert _claim_limit("tel_aviv") == 1


def test_jerusalem_keeps_its_parallel_batch() -> None:
    assert _claim_limit("jerusalem") == 20


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
            return [unit.unit_key]

    adapter = FakeAdapter()
    units = [SearchUnit(str(index), "run-1", index, f"street:{index}", {}) for index in range(4)]

    results = _collect_wave(adapter, units, date(2025, 7, 1), date(2025, 7, 31))

    assert len(results) == 4
    assert adapter.maximum_active == 2
