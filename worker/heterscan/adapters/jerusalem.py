from __future__ import annotations

from datetime import date

from ..domain import ApplicationRecord, SearchUnit
from ..http import PublicHttpClient
from ..normalize import clean_text, in_range, normalized_key, parse_date
from .base import Adapter


class JerusalemAdapter(Adapter):
    name = "jerusalem"
    api_url = "https://jerbasicserviceapi.jerusalem.muni.il/api/Db/ExecuteGetJSON"
    system_id = "26400046"

    def _call(self, client: PublicHttpClient, procedure: int, parameters: dict) -> list[dict]:
        return client.request(
            "POST", self.api_url,
            json={"ProcName": procedure, "Cnn": "cnnGisYk", "Parameters": parameters},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        ).json() or []

    def collect(self, unit: SearchUnit, date_from: date, date_to: date) -> list[ApplicationRecord]:
        client = PublicHttpClient(delay_seconds=0.7)
        output: list[ApplicationRecord] = []
        street_code = clean_text(unit.payload.get("streetCode"))
        street_name = clean_text(unit.payload.get("streetName")) or None
        try:
            candidates = self._call(
                client, 242700437,
                {"misparTik": None, "gush": None, "helka": None, "rehovCode": street_code,
                 "mispBait": None, "mezahe": None, "migrash": None, "systemId": self.system_id},
            )
            for candidate in candidates:
                application_number = clean_text(candidate.get("tik_num"))
                if not application_number:
                    continue
                detail_rows = self._call(client, 242700447, {"tikNum": application_number, "systemCode": self.system_id})
                process_rows = self._call(client, 242700451, {"SystemID": self.system_id, "TikNum": application_number})
                detail = detail_rows[0] if detail_rows else {}
                detail.pop("baaleiInyanList", None)
                dates = [parse_date(row.get("execDateStr")) for row in process_rows]
                submitted = min((value for value in dates if value), default=None)
                if not in_range(submitted, date_from, date_to):
                    continue
                status = clean_text(detail.get("teurStatus") or candidate.get("teurStatus"))
                terminal_events = []
                for row in process_rows:
                    label = normalized_key(row.get("stepCodeText"))
                    event_date = parse_date(row.get("execDateStr"))
                    if event_date and "היתר" in label and any(term in label for term in ("הוצאת", "מסירת", "חתום")):
                        terminal_events.append((event_date, clean_text(row.get("stepCodeText"))))
                status_key = normalized_key(status)
                status_date = parse_date(detail.get("fullTaarihStatus") or candidate.get("taarih_status"))
                status_explicit = "היתר" in status_key and any(term in status_key for term in ("הופק", "הוצא", "בתוקף"))
                permit_date = min((item[0] for item in terminal_events), default=status_date if status_explicit else None)
                permit_number = clean_text(detail.get("misparHeter") or detail.get("heter_num")) or None
                issued = bool(permit_date and (terminal_events or status_explicit))
                approval_date = permit_date if issued else None
                source_url = f"https://ykpubdata.jerusalem.muni.il/#/Rishui/BakashalInfo?TikNum={application_number}&SystemCode={self.system_id}"
                output.append(
                    ApplicationRecord(
                        city_id=self.city_id,
                        application_number=application_number,
                        address=" ".join(part for part in [clean_text(detail.get("shemRehov")) or street_name or "", clean_text(detail.get("misparBait"))] if part) or None,
                        street_name=clean_text(detail.get("shemRehov")) or street_name,
                        house_number=clean_text(detail.get("misparBait")) or None,
                        application_type=clean_text(detail.get("teurSugbakashaCodeMulti") or candidate.get("teurSugbakasha")) or None,
                        work_description=clean_text(detail.get("mahutBakasha") or candidate.get("mahut_bakasha")) or None,
                        submission_date=submitted,
                        approval_date=approval_date,
                        is_approved=issued,
                        approval_confidence="high" if issued else None,
                        permit_number=permit_number,
                        permit_issue_date=permit_date,
                        permit_status_original=status or None,
                        is_permit_issued=issued,
                        permit_confidence="high" if permit_number and issued else ("medium" if issued else None),
                        source_url=source_url,
                        source_reference=application_number,
                        adapter_name=self.name,
                        adapter_version=self.version,
                        raw_data={"candidate": candidate, "detail": detail, "process": process_rows},
                        evidence=[{"type": "terminal_event", "events": terminal_events, "status": status}],
                    )
                )
        finally:
            client.close()
        return output
