from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from datetime import date, datetime, timedelta, timezone

from .adapters import ComplotAdapter, JerusalemAdapter, TelAvivAdapter
from .domain import AdapterReviewRequired
from .reporting import build_report
from .supabase import SupabaseRepository

ADAPTERS = {"jerusalem": JerusalemAdapter, "tel_aviv": TelAvivAdapter, "complot": ComplotAdapter}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def run(run_id: str) -> int:
    repository = SupabaseRepository()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    started = time.monotonic()
    max_seconds = int(os.environ.get("MAX_WORKER_SECONDS", "19800"))
    review_count = 0
    error_count = 0
    try:
        claimed = repository._rest(
            "POST", "rpc/claim_run", json={"p_run_id": run_id, "p_worker_id": worker_id, "p_ttl_minutes": 10}
        ).json()
        if not claimed:
            raise RuntimeError("Run is locked by another worker or is no longer active")
        run_row = repository.get_run(run_id)
        snapshot = run_row["configuration_snapshot"]
        city = snapshot["city"]
        adapter_class = ADAPTERS.get(city["adapter_name"])
        if not adapter_class:
            raise RuntimeError(f"Unknown adapter {city['adapter_name']}")
        adapter = adapter_class(city["id"], city["name_he"], city.get("adapter_config") or {})
        date_from, date_to = _parse_date(run_row["date_from"]), _parse_date(run_row["date_to"])
        repository.log(run_id, "info", "worker_started", {"worker_id": worker_id, "adapter": adapter.name})

        while time.monotonic() - started < max_seconds:
            units = repository.claim_units(run_id, worker_id, limit=20)
            if not units:
                break
            for unit in units:
                try:
                    records = adapter.collect(unit, date_from, date_to)
                    for record in records:
                        repository.save_application(run_id, record)
                    repository.complete_unit(unit.id, len(records))
                except AdapterReviewRequired as error:
                    review_count += 1
                    repository.fail_unit(unit.id, str(error), review=True)
                    repository.log(run_id, "warning", "unit_requires_review", {"unit": unit.unit_key, "error": str(error)})
                except Exception as error:  # A single street must not erase the rest of the run.
                    error_count += 1
                    repository.fail_unit(unit.id, str(error))
                    repository.log(run_id, "error", "unit_failed", {"unit": unit.unit_key, "error": str(error)[:1000]})
                counts = repository.progress_counts(run_id)
                repository.update_run(
                    run_id,
                    {**counts, "heartbeat_at": _iso_now(), "lock_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()},
                )

        remaining = repository._rest(
            "GET", f"run_units?run_id=eq.{run_id}&status=in.(pending,processing)&select=id"
        ).json()
        if remaining:
            repository.update_run(
                run_id,
                {"status": "safely_stopped", "heartbeat_at": _iso_now(), "lock_expires_at": None, "lock_owner": None},
            )
            repository.log(run_id, "info", "worker_timebox_reached", {"remaining_units": len(remaining)})
            return 75

        results = repository.run_results(run_id)
        units = repository.run_units(run_id)
        final_status = "requires_review" if review_count else "completed_with_errors" if error_count else "completed"
        report_run = {**repository.get_run(run_id), "status": final_status}
        report_bytes, checksum = build_report(report_run, results, units)
        safe_city = city["name_he"].replace(" ", "_").replace("־", "-")
        storage_path = f"{run_id}/HETERSCAN_{safe_city}_{date_from}_{date_to}_{run_id}.xlsx"
        repository.upload_report(storage_path, report_bytes)
        repository.save_report_metadata(run_id, storage_path, checksum, len(report_bytes))
        counts = repository.progress_counts(run_id)
        repository.update_run(
            run_id,
            {
                **counts, "status": final_status, "report_path": storage_path,
                "completed_at": _iso_now(), "heartbeat_at": _iso_now(), "lock_owner": None, "lock_expires_at": None,
            },
        )
        repository.log(run_id, "info", "worker_completed", {"status": final_status, **counts})
        return 0
    except Exception as error:
        try:
            repository.update_run(
                run_id,
                {"status": "failed", "error_message": str(error)[:2000], "completed_at": _iso_now(), "lock_owner": None, "lock_expires_at": None},
            )
            repository.log(run_id, "error", "worker_failed", {"error": str(error)[:1000]})
        finally:
            repository.close()
        raise
    finally:
        repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one manually-created HETERSCAN scan")
    parser.add_argument("--run-id", default=os.environ.get("RUN_ID"), required="RUN_ID" not in os.environ)
    args = parser.parse_args()
    sys.exit(run(args.run_id))


if __name__ == "__main__":
    main()
