from __future__ import annotations

import argparse
import concurrent.futures
import os
import socket
import sys
import time
from datetime import date, datetime, timedelta, timezone

from .adapters import ComplotAdapter, JerusalemAdapter, TelAvivAdapter
from .domain import AdapterRateLimited, AdapterReviewRequired, ApplicationRecord, DiscoveryResult
from .reporting import build_report, report_storage_filename
from .supabase import SupabaseRepository
from .validator import validate_records

ADAPTERS = {"jerusalem": JerusalemAdapter, "tel_aviv": TelAvivAdapter, "complot": ComplotAdapter}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _claim_limit(adapter_name: str) -> int:
    return 20 if adapter_name in ("jerusalem", "complot") else 1


def _final_status(summary: dict[str, int]) -> str:
    """An unverified empty result can never be published as a successful zero."""
    if summary["units_requires_review"] or summary["applications_found"] == 0:
        return "requires_review"
    if summary["units_failed"]:
        return "completed_with_errors"
    return "completed"


def _coverage_verification(final_status: str, result_count: int) -> str:
    if final_status not in {"completed", "requires_review", "completed_with_errors"}:
        return "partial"
    if result_count == 0:
        return "zero_not_verified"
    return "partial" if final_status != "completed" else "not_verified"


def _parallelism(adapter) -> int:
    if adapter.name == "jerusalem":
        return 8
    if adapter.name == "complot":
        return adapter.parallelism()
    return 1


def _records_in_requested_range(records, date_from: date, date_to: date):
    """Final guard against adapters returning stale or out-of-range applications."""
    if isinstance(records, DiscoveryResult):
        return records
    return [
        record
        for record in records
        if record.submission_date is not None and date_from <= record.submission_date <= date_to
    ]


def _validate_collection(adapter, unit, records, date_from: date, date_to: date):
    if isinstance(records, DiscoveryResult):
        return records, None
    if not isinstance(records, list):
        raise AdapterReviewRequired("המקור החזיר תוצאות במבנה לא צפוי.")
    if not records:
        return [], None
    # Non-domain fixture records retain the old range guard. Production
    # ApplicationRecord values always pass through the source validator.
    if not all(isinstance(record, ApplicationRecord) for record in records):
        return _records_in_requested_range(records, date_from, date_to), None
    checked = validate_records(records, unit, adapter, date_from, date_to)
    if not checked.issues:
        return checked.records, None
    codes = list(dict.fromkeys(issue.code for issue in checked.issues))
    error = AdapterReviewRequired(
        "אימות הרשומה מול נתוני המקור לא הושלם: " + ", ".join(codes[:8]),
        diagnostics={"validator_issues": [
            {"code": issue.code, "application_number": issue.application_number}
            for issue in checked.issues[:30]
        ]},
        partial_records=checked.records,
    )
    return checked.records, error


def _collect_one(adapter, unit, date_from: date, date_to: date):
    try:
        return _validate_collection(adapter, unit, adapter.collect(unit, date_from, date_to), date_from, date_to)
    except Exception as error:
        partial = getattr(error, "partial_records", [])
        if not partial:
            return [], error
        checked, validator_error = _validate_collection(adapter, unit, partial, date_from, date_to)
        if validator_error and isinstance(error, AdapterReviewRequired):
            error.diagnostics = {**error.diagnostics, **validator_error.diagnostics}
            error.partial_records = checked
        return checked, error


def _collect_wave(adapter, units, date_from: date, date_to: date):
    collected = []
    workers = min(len(units), _parallelism(adapter))
    if workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_unit = {
                executor.submit(_collect_one, adapter, unit, date_from, date_to): unit for unit in units
            }
            for future in concurrent.futures.as_completed(future_to_unit):
                unit = future_to_unit[future]
                try:
                    records, error = future.result()
                    collected.append((unit, records, error))
                except Exception as error:
                    collected.append((unit, [], error))
    else:
        unit = units[0]
        try:
            records, error = _collect_one(adapter, unit, date_from, date_to)
            collected.append((unit, records, error))
        except Exception as error:
            collected.append((unit, [], error))
    return collected


def _expand_discovery(repository, run_id: str, unit, result: DiscoveryResult):
    """Queue observable candidates before recording uncertainty in their discovery."""
    inserted = repository.enqueue_units(run_id, result.units)
    review = AdapterReviewRequired(result.review_reason) if result.review_reason else None
    return inserted, (unit, [], review)


def _wait_for_source_cooldown(
    repository: SupabaseRepository,
    run_id: str,
    seconds: float,
    *,
    poll_seconds: float = 5.0,
) -> bool:
    """Keep cancellation responsive while a public source cools down."""
    deadline = time.monotonic() + max(0.0, seconds)
    next_heartbeat = time.monotonic()
    while time.monotonic() < deadline:
        if repository.cancellation_requested(run_id):
            return False
        now = time.monotonic()
        if now >= next_heartbeat:
            repository.update_run(run_id, {"heartbeat_at": _iso_now()})
            next_heartbeat = now + 30
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
    return True


def _finalize_report(
    repository: SupabaseRepository,
    run_id: str,
    city_id: str,
    date_from: date,
    date_to: date,
    final_status: str,
) -> int:
    results = repository.run_results(run_id)
    units = repository.run_units(run_id)
    current = repository.get_run(run_id)
    if current["status"] == "cancelled" or current.get("cancel_requested_at"):
        final_status = "cancelled"
    coverage_verification = _coverage_verification(final_status, len(results))
    city_snapshot = (current.get("configuration_snapshot") or {}).get("city") or {}
    report_run = {
        **current,
        "id": current.get("id") or run_id,
        "city_id": current.get("city_id") or city_id,
        "city_name": current.get("city_name") or city_snapshot.get("name_he"),
        "date_from": current.get("date_from") or date_from.isoformat(),
        "date_to": current.get("date_to") or date_to.isoformat(),
        "status": final_status,
        "coverage_verification": coverage_verification,
    }
    report_bytes, checksum = build_report(report_run, results, units)
    storage_path = f"{run_id}/{report_storage_filename(report_run)}"
    repository.upload_report(storage_path, report_bytes)
    repository.save_report_metadata(run_id, storage_path, checksum, len(report_bytes))
    counts = repository.progress_counts(run_id)
    finalized = repository.finalize_run(
        run_id,
        {
            **counts,
            "status": final_status,
            "coverage_verification": coverage_verification,
            "report_path": storage_path,
            "completed_at": _iso_now(),
            "heartbeat_at": _iso_now(),
            "lock_owner": None,
            "lock_expires_at": None,
        },
    )
    if not finalized:
        if final_status == "cancelled":
            raise RuntimeError("Cancelled run disappeared while publishing its report")
        # The server accepted cancellation during upload. Rebuild the artifact
        # with the truthful terminal status before exposing the download.
        return _finalize_report(repository, run_id, city_id, date_from, date_to, "cancelled")
    event = "worker_cancelled" if final_status == "cancelled" else "worker_completed"
    repository.log(run_id, "info", event, {"status": final_status, **counts})
    return 0


def run(run_id: str) -> int:
    repository = SupabaseRepository()
    adapter = None
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    started = time.monotonic()
    max_seconds = int(os.environ.get("MAX_WORKER_SECONDS", "19800"))
    claimed = False
    try:
        initial = repository.get_run(run_id)
        if initial["status"] == "cancelled":
            if initial.get("report_path"):
                return 0
            return _finalize_report(repository, run_id, initial["city_id"],
                                    _parse_date(initial["date_from"]), _parse_date(initial["date_to"]), "cancelled")
        if initial["status"] not in {"created", "dispatching", "running", "safely_stopped"}:
            return 0
        claimed = repository._rest(
            "POST", "rpc/claim_run", json={"p_run_id": run_id, "p_worker_id": worker_id, "p_ttl_minutes": 10}
        ).json()
        if not claimed:
            current = repository.get_run(run_id)
            if current["status"] == "cancelled" and not current.get("report_path"):
                return _finalize_report(repository, run_id, current["city_id"],
                                        _parse_date(current["date_from"]), _parse_date(current["date_to"]), "cancelled")
            repository.log(run_id, "info", "worker_skipped", {"reason": "locked or terminal"})
            return 0
        run_row = repository.get_run(run_id)
        snapshot = run_row["configuration_snapshot"]
        city = snapshot["city"]
        adapter_class = ADAPTERS.get(city["adapter_name"])
        if not adapter_class:
            raise RuntimeError(f"Unknown adapter {city['adapter_name']}")
        adapter_config = city.get("adapter_config") or {}
        adapter = (adapter_class(city["id"], city["name_he"], adapter_config, coordinator=repository)
                   if city["adapter_name"] == "complot"
                   else adapter_class(city["id"], city["name_he"], adapter_config))
        date_from, date_to = _parse_date(run_row["date_from"]), _parse_date(run_row["date_to"])
        repository.log(run_id, "info", "worker_started", {"worker_id": worker_id, "adapter": adapter.name})

        if repository.cancellation_requested(run_id):
            return _finalize_report(repository, run_id, city["id"], date_from, date_to, "cancelled")

        rate_limited_windows = 0
        finalized_since_cooldown = 0
        while time.monotonic() - started < max_seconds:
            if repository.cancellation_requested(run_id):
                return _finalize_report(repository, run_id, city["id"], date_from, date_to, "cancelled")
            units = repository.claim_units(run_id, worker_id, limit=_claim_limit(adapter.name))
            if not units:
                break
            collected = []
            unprocessed = list(units)
            cancel_after_batch = False
            cooldown_after_batch = 0.0
            rate_limit_details = []
            batch_started = time.monotonic()
            while unprocessed:
                workers = min(len(unprocessed), _parallelism(adapter))
                wave, unprocessed = unprocessed[:workers], unprocessed[workers:]
                before = adapter.performance_snapshot() if adapter.name == "complot" else {}
                wave_started = time.monotonic()
                wave_results = _collect_wave(adapter, wave, date_from, date_to)
                wave_elapsed = time.monotonic() - wave_started
                rate_limited = [
                    (unit, error) for unit, _, error in wave_results if isinstance(error, AdapterRateLimited)
                ]
                collected.extend(
                    result for result in wave_results if not isinstance(result[2], AdapterRateLimited)
                )
                if adapter.name == "complot":
                    after = adapter.performance_snapshot()
                    rate_penalties = int(after["penalties"]) - int(before["penalties"])
                    adapter.observe_wave(
                        errors=sum(1 for _, _, error in wave_results if error) + max(0, rate_penalties),
                        elapsed_seconds=wave_elapsed,
                        units=len(wave),
                    )
                if rate_limited:
                    rate_limit_details.extend({
                        "origin": error.origin,
                        "endpoint": error.endpoint,
                        "retry_after_kind": error.retry_after_kind,
                        "retry_after_seconds": round(error.retry_after_seconds, 2),
                    } for _, error in rate_limited)
                    released = [unit.id for unit, _ in rate_limited] + [unit.id for unit in unprocessed]
                    repository.release_units(released)
                    cooldown_after_batch = max(error.retry_after_seconds for _, error in rate_limited)
                    repository.log(
                        run_id,
                        "warning",
                        "source_rate_limited",
                        {
                            "released_units": len(released),
                            "retry_after_seconds": round(cooldown_after_batch, 1),
                            "origin": "handasi.complot.co.il" if adapter.name == "complot" else None,
                            "responses": rate_limit_details,
                        },
                    )
                    unprocessed = []
                    break
                if unprocessed and repository.cancellation_requested(run_id):
                    repository.release_units([unit.id for unit in unprocessed])
                    cancel_after_batch = True
                    break

            discovered_units = 0
            expanded = []
            for unit, result, collection_error in collected:
                if collection_error is None and isinstance(result, DiscoveryResult):
                    try:
                        inserted, expanded_result = _expand_discovery(repository, run_id, unit, result)
                        discovered_units += inserted
                        expanded.append(expanded_result)
                    except Exception as expansion_error:
                        expanded.append((unit, None, expansion_error))
                else:
                    expanded.append((unit, result, collection_error))
            collected = expanded

            successful = [(unit, records or []) for unit, records, error in collected
                          if error is None or (isinstance(error, AdapterReviewRequired) and records)]
            all_records = [record for _, records in successful for record in records]
            persistence_errors: dict[str, Exception] = {}
            try:
                repository.save_applications(run_id, all_records)
            except Exception as batch_error:
                repository.log(
                    run_id,
                    "warning",
                    "bulk_persistence_fallback",
                    {"records": len(all_records), "error": str(batch_error)[:1000]},
                )
                for unit, records in successful:
                    try:
                        repository.save_applications(run_id, records)
                    except Exception as unit_error:
                        persistence_errors[unit.id] = unit_error

            unit_updates = []
            failure_context = []
            for unit, records, collection_error in collected:
                error = persistence_errors.get(unit.id) or collection_error
                if error is None:
                    unit_updates.append(
                        {
                            "id": unit.id,
                            "status": "completed",
                            "result_count": len(records or []),
                            "error_message": None,
                        }
                    )
                    continue
                review = isinstance(error, AdapterReviewRequired)
                unit_updates.append(
                    {
                        "id": unit.id,
                        "status": "requires_review" if review else "failed",
                        "result_count": len(records or []) if unit.id not in persistence_errors else 0,
                        "error_message": str(error)[:2000],
                    }
                )
                failure_context.append({"unit": unit.unit_key, "review": review, "error": str(error)[:1000],
                                        "diagnostics": getattr(error, "diagnostics", {})})
            try:
                finished = repository.finish_units(unit_updates)
                if finished != len(unit_updates):
                    raise RuntimeError(
                        f"Bulk unit completion updated {finished} of {len(unit_updates)} units"
                    )
            except Exception as batch_finish_error:
                repository.log(
                    run_id,
                    "warning",
                    "bulk_unit_completion_fallback",
                    {"units": len(unit_updates), "error": str(batch_finish_error)[:1000]},
                )
                for update in unit_updates:
                    if update["status"] == "completed":
                        repository.complete_unit(update["id"], update["result_count"])
                    else:
                        repository.fail_unit(
                            update["id"],
                            update["error_message"] or "Unit failed",
                            review=update["status"] == "requires_review",
                        )
            if failure_context:
                repository.log(
                    run_id,
                    "warning" if all(item["review"] for item in failure_context) else "error",
                    "unit_batch_failures",
                    {"failures": failure_context},
                )
            finalized_since_cooldown += len(unit_updates)
            counts = repository.progress_counts(run_id)
            still_owned = repository.update_owned_run(
                run_id,
                worker_id,
                {
                    **counts,
                    "heartbeat_at": _iso_now(),
                    "lock_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                },
            )
            if not still_owned:
                if repository.cancellation_requested(run_id):
                    return _finalize_report(repository, run_id, city["id"], date_from, date_to, "cancelled")
                repository.log(run_id, "warning", "worker_ownership_changed", {"worker_id": worker_id})
                return 0
            performance = (
                adapter.performance_snapshot()
                if adapter.name == "complot"
                else {"parallelism": _parallelism(adapter)}
            )
            repository.log(
                run_id,
                "info",
                "worker_batch_completed",
                {
                    "claimed_units": len(units),
                    "processed_units": len(collected),
                    "discovered_units": discovered_units,
                    "records": len(all_records),
                    "finalized_since_previous_cooldown": finalized_since_cooldown,
                    "elapsed_seconds": round(time.monotonic() - batch_started, 3),
                    **performance,
                },
            )

            if cancel_after_batch or repository.cancellation_requested(run_id):
                return _finalize_report(repository, run_id, city["id"], date_from, date_to, "cancelled")
            if rate_limit_details:
                rate_limited_windows = 0 if unit_updates else rate_limited_windows + 1
                if rate_limited_windows >= 3 or cooldown_after_batch >= max_seconds - (time.monotonic() - started):
                    repository.mark_unfinished_rate_limited(run_id)
                    repository.log(run_id, "warning", "source_rate_limit_breaker", {
                        "origin": "handasi.complot.co.il" if adapter.name == "complot" else None,
                        "consecutive_windows_without_progress": rate_limited_windows,
                        "cooldown_seconds": round(cooldown_after_batch, 2),
                        "reason": "repeated_429" if rate_limited_windows >= 3 else "cooldown_exceeds_worker_timebox",
                    })
                    return _finalize_report(repository, run_id, city["id"], date_from, date_to, "requires_review")
                if not _wait_for_source_cooldown(repository, run_id, cooldown_after_batch):
                    return _finalize_report(repository, run_id, city["id"], date_from, date_to, "cancelled")
                finalized_since_cooldown = 0
            else:
                rate_limited_windows = 0

        if repository.cancellation_requested(run_id):
            return _finalize_report(repository, run_id, city["id"], date_from, date_to, "cancelled")

        remaining = repository._rest(
            "GET", f"run_units?run_id=eq.{run_id}&status=in.(pending,processing)&select=id&limit=1"
        ).json()
        if remaining:
            checkpointed = repository.update_owned_run(
                run_id,
                worker_id,
                {
                    "status": "safely_stopped",
                    "heartbeat_at": _iso_now(),
                    "lock_expires_at": None,
                    "lock_owner": None,
                },
            )
            if not checkpointed:
                if repository.cancellation_requested(run_id):
                    return _finalize_report(repository, run_id, city["id"], date_from, date_to, "cancelled")
                return 0
            repository.log(run_id, "info", "worker_timebox_reached", {"remaining_units": len(remaining)})
            return 75

        summary = repository.progress_summary(run_id)
        final_status = _final_status(summary)
        return _finalize_report(repository, run_id, city["id"], date_from, date_to, final_status)
    except Exception as error:
        try:
            if claimed:
                repository.update_owned_run(
                    run_id,
                    worker_id,
                    {
                        "status": "failed",
                        "error_message": str(error)[:2000],
                        "completed_at": _iso_now(),
                        "lock_owner": None,
                        "lock_expires_at": None,
                    },
                )
            repository.log(run_id, "error", "worker_failed", {"error": str(error)[:1000]})
        except Exception as reporting_error:
            print(
                f"Could not persist worker failure: {reporting_error}; original error: {error}",
                file=sys.stderr,
            )
        raise
    finally:
        if adapter is not None:
            adapter.close()
        repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one manually-created HETERSCAN scan")
    parser.add_argument("--run-id", default=os.environ.get("RUN_ID"), required="RUN_ID" not in os.environ)
    args = parser.parse_args()
    sys.exit(run(args.run_id))


if __name__ == "__main__":
    main()
