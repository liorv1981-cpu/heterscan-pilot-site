from __future__ import annotations

import argparse
from uuid import uuid4

from .reporting import build_report
from .supabase import SupabaseRepository


def regenerate_report(run_id: str) -> str:
    repository = SupabaseRepository()
    try:
        run = repository.get_run(run_id)
        if run["status"] in {"created", "dispatching", "running", "safely_stopped"}:
            raise ValueError("Cannot regenerate the report of an active scan")
        results = repository.run_results(run_id)
        units = repository.run_units(run_id)
        payload, checksum = build_report(run, results, units)
        # Keep the previous object recoverable; change only the current-report pointer.
        storage_path = (
            f"{run_id}/HETERSCAN_{run['city_id']}_{run['date_from']}_{run['date_to']}"
            f"_{run_id}_v{uuid4().hex[:12]}.xlsx"
        )
        repository.upload_report(storage_path, payload)
        repository.save_report_metadata(run_id, storage_path, checksum, len(payload))
        repository.update_run(run_id, {"report_path": storage_path})
        repository.log(
            run_id,
            "info",
            "report_regenerated",
            {"applications": len(results), "bytes": len(payload), "previous_report_path": run.get("report_path"), "report_path": storage_path},
        )
        return storage_path
    finally:
        repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate a HETERSCAN XLSX report")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    regenerate_report(args.run_id)


if __name__ == "__main__":
    main()
