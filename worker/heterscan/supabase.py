from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import httpx

from .domain import ApplicationRecord, SearchUnit
from .normalize import content_hash, record_identity


class SupabaseRepository:
    def __init__(self, url: str | None = None, service_key: str | None = None) -> None:
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.service_key = service_key or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.client = httpx.Client(
            timeout=60,
            headers={
                "apikey": self.service_key,
                "Authorization": f"Bearer {self.service_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self.client.close()

    def _rest(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self.client.request(method, f"{self.url}/rest/v1/{path}", **kwargs)
        response.raise_for_status()
        return response

    def get_run(self, run_id: str) -> dict[str, Any]:
        rows = self._rest("GET", f"run_overview?id=eq.{quote(run_id)}&select=*").json()
        if not rows:
            raise RuntimeError(f"Run {run_id} not found")
        return rows[0]

    def update_run(self, run_id: str, values: dict[str, Any]) -> None:
        self._rest("PATCH", f"runs?id=eq.{quote(run_id)}", json=values)

    def claim_units(self, run_id: str, worker_id: str, limit: int = 20) -> list[SearchUnit]:
        rows = self._rest(
            "POST", "rpc/claim_run_units", json={"p_run_id": run_id, "p_worker_id": worker_id, "p_limit": limit}
        ).json()
        return [
            SearchUnit(
                id=row["id"], run_id=row["run_id"], sequence=row["sequence"],
                unit_key=row["unit_key"], payload=row["unit_payload"],
            )
            for row in rows
        ]

    def complete_unit(self, unit_id: str, result_count: int) -> None:
        self._rest(
            "PATCH", f"run_units?id=eq.{quote(unit_id)}",
            json={"status": "completed", "result_count": result_count, "completed_at": "now"},
        )

    def fail_unit(self, unit_id: str, message: str, *, review: bool = False) -> None:
        self._rest(
            "PATCH", f"run_units?id=eq.{quote(unit_id)}",
            json={"status": "requires_review" if review else "failed", "error_message": message[:2000], "completed_at": "now"},
        )

    def save_application(self, run_id: str, record: ApplicationRecord) -> str:
        fallback = {
            "address": record.address,
            "submission_date": str(record.submission_date or ""),
            "application_type": record.application_type,
            "building_file_number": record.building_file_number,
        }
        identity = record_identity(record.city_id, record.application_number, fallback)
        database_record = record.to_database(run_id=run_id, identity_key=identity, content_hash=content_hash(record.raw_data))
        response = self._rest(
            "POST", "applications?on_conflict=city_id,identity_key&select=id,content_hash",
            headers={"Prefer": "resolution=merge-duplicates,return=representation"}, json=database_record,
        )
        application = response.json()[0]
        self._rest(
            "POST", "run_applications?on_conflict=run_id,application_id",
            headers={"Prefer": "resolution=ignore-duplicates"},
            json={"run_id": run_id, "application_id": application["id"]},
        )
        self._rest(
            "POST", "application_versions?on_conflict=application_id,content_hash",
            headers={"Prefer": "resolution=ignore-duplicates"},
            json={"application_id": application["id"], "run_id": run_id, "content_hash": application["content_hash"], "snapshot": record.raw_data},
        )
        events = []
        if record.is_approved:
            events.append({"event_type": "approval", "event_date": str(record.approval_date or "") or None})
        if record.is_permit_issued:
            events.append({"event_type": "permit_issued", "event_date": str(record.permit_issue_date or "") or None})
        for event in events:
            self._rest(
                "POST", "application_events?on_conflict=application_id,run_id,event_type",
                headers={"Prefer": "resolution=ignore-duplicates"},
                json={
                    "application_id": application["id"], "run_id": run_id, **event,
                    "original_status": record.permit_status_original, "evidence": record.evidence,
                },
            )
        return application["id"]

    def progress_counts(self, run_id: str) -> dict[str, int]:
        units = self._rest("GET", f"run_units?run_id=eq.{quote(run_id)}&select=status").json()
        results = self._rest(
            "GET", f"run_applications?run_id=eq.{quote(run_id)}&select=application:applications(is_permit_issued)"
        ).json()
        return {
            "units_completed": sum(row["status"] in ("completed", "failed", "requires_review") for row in units),
            "applications_found": len(results),
            "permits_found": sum(bool(row.get("application", {}).get("is_permit_issued")) for row in results),
        }

    def run_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._rest(
            "GET", f"run_applications?run_id=eq.{quote(run_id)}&select=discovered_at,application:applications(*)"
        ).json()
        return [{**row["application"], "discovered_at": row["discovered_at"]} for row in rows]

    def run_units(self, run_id: str) -> list[dict[str, Any]]:
        return self._rest("GET", f"run_units?run_id=eq.{quote(run_id)}&select=*&order=sequence").json()

    def log(self, run_id: str, level: str, event: str, context: dict[str, Any] | None = None) -> None:
        self._rest("POST", "run_logs", json={"run_id": run_id, "level": level, "event": event, "context": context or {}})

    def upload_report(self, storage_path: str, content: bytes) -> None:
        response = self.client.post(
            f"{self.url}/storage/v1/object/reports/{storage_path}", content=content,
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "x-upsert": "true"},
        )
        response.raise_for_status()

    def save_report_metadata(self, run_id: str, storage_path: str, checksum: str, size: int) -> None:
        self._rest(
            "POST", "reports?on_conflict=run_id",
            headers={"Prefer": "resolution=merge-duplicates"},
            json={"run_id": run_id, "storage_path": storage_path, "checksum_sha256": checksum, "file_size": size},
        )

    def upsert_many(self, table: str, rows: Iterable[dict[str, Any]], *, conflict: str, batch_size: int = 500) -> int:
        batch: list[dict[str, Any]] = []
        count = 0
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                self._upsert_batch(table, batch, conflict)
                count += len(batch)
                batch.clear()
        if batch:
            self._upsert_batch(table, batch, conflict)
            count += len(batch)
        return count

    def _upsert_batch(self, table: str, rows: list[dict[str, Any]], conflict: str) -> None:
        self._rest(
            "POST", f"{table}?on_conflict={conflict}",
            headers={"Prefer": "resolution=merge-duplicates"}, json=rows,
        )
