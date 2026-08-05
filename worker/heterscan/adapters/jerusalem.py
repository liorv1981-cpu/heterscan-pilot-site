from __future__ import annotations

import re
import threading
import time
from datetime import date

from ..domain import ApplicationRecord, SearchUnit
from ..http import PublicHttpClient
from ..normalize import clean_text, in_range, normalized_key, parse_date
from .base import Adapter


class JerusalemAdapter(Adapter):
    name = "jerusalem"
    api_url = "https://jerbasicserviceapi.jerusalem.muni.il/api/Db/ExecuteGetJSON"
    system_id = "26400046"
    _rate_lock = threading.Lock()
    _next_request_at = 0.0
    # A controlled eight-request probe completed without throttling at 0.6s.
    _request_interval_seconds = 0.6
    _terminal_permit_steps = {
        normalized_key("הוצאת היתר בניה"),
        normalized_key("הוצאת היתר בנייה"),
        normalized_key("מסירת היתר בניה"),
        normalized_key("מסירת היתר בנייה"),
    }

    def __init__(self, city_id: str, city_name: str, config: dict) -> None:
        super().__init__(city_id, city_name, config)
        self.client = PublicHttpClient(delay_seconds=0, max_connections=12)

    def close(self) -> None:
        self.client.close()

    def _call(self, client: PublicHttpClient, procedure: int, parameters: dict) -> list[dict]:
        with self._rate_lock:
            wait = self._next_request_at - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            type(self)._next_request_at = time.monotonic() + self._request_interval_seconds
        return (
            client.request(
                "POST",
                self.api_url,
                json={"ProcName": procedure, "Cnn": "cnnGisYk", "Parameters": parameters},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            ).json()
            or []
        )

    def collect(self, unit: SearchUnit, date_from: date, date_to: date) -> list[ApplicationRecord]:
        output: list[ApplicationRecord] = []
        street_code = clean_text(unit.payload.get("streetCode"))
        street_name = clean_text(unit.payload.get("streetName")) or None
        candidates = self._call(
            self.client,
            242700437,
            {
                "misparTik": None,
                "gush": None,
                "helka": None,
                "rehovCode": street_code,
                "mispBait": None,
                "mezahe": None,
                "migrash": None,
                "systemId": self.system_id,
            },
        )
        for candidate in candidates:
            application_number = clean_text(candidate.get("tik_num"))
            if not application_number:
                continue
            # Follow-up case numbers can retain the original file year for several
            # years. Keep a three-year lookback while avoiding decades of detail calls.
            year_match = re.match(r"^(\d{4})/", application_number)
            earliest_file_year = date_from.year - 2
            if year_match and not earliest_file_year <= int(year_match.group(1)) <= date_to.year:
                continue
            detail_rows = self._call(
                self.client, 242700447, {"tikNum": application_number, "systemCode": self.system_id}
            )
            process_rows = self._call(
                self.client, 242700451, {"SystemID": self.system_id, "TikNum": application_number}
            )
            detail = detail_rows[0] if detail_rows else {}
            detail.pop("baaleiInyanList", None)
            all_dates = []
            filing_dates = []
            for row in process_rows:
                event_date = parse_date(row.get("execDateStr"))
                if not event_date:
                    continue
                all_dates.append(event_date)
                process_label = normalized_key(
                    f"{clean_text(row.get('processText'))} {clean_text(row.get('stepCodeText'))}"
                )
                if any(term in process_label for term in ("הגשה", "קליטת בקשה", "פתיחת תיק")):
                    filing_dates.append(event_date)
            submitted = min(filing_dates or all_dates, default=None)
            if not in_range(submitted, date_from, date_to):
                continue
            status = clean_text(detail.get("teurStatus") or candidate.get("teurStatus"))
            terminal_events = []
            for row in process_rows:
                label = normalized_key(row.get("stepCodeText"))
                event_date = parse_date(row.get("execDateStr"))
                is_terminal_step = label in self._terminal_permit_steps or "הוצאת היתר דיגיטלי חתום" in label
                if event_date and is_terminal_step:
                    terminal_events.append((event_date, clean_text(row.get("stepCodeText"))))
            status_key = normalized_key(status)
            status_date = parse_date(candidate.get("taarih_status") or detail.get("fullTaarihStatus"))
            permit_status_explicit = "היתר" in status_key and any(
                term in status_key for term in ("הופק", "הוצא", "בתוקף")
            )
            approval_status_explicit = "אושר" in status_key and "מהנדס העיר" in status_key
            permit_date = min(
                (item[0] for item in terminal_events),
                default=status_date if permit_status_explicit else None,
            )
            permit_number = clean_text(detail.get("misparHeter") or detail.get("heter_num")) or None
            issued = bool(permit_date and (terminal_events or permit_status_explicit))
            approval_date = permit_date or (status_date if approval_status_explicit else None)
            approved = approval_date is not None
            source_url = f"https://ykpubdata.jerusalem.muni.il/#/Rishui/BakashalInfo?TikNum={application_number}&SystemCode={self.system_id}"
            output.append(
                ApplicationRecord(
                    city_id=self.city_id,
                    application_number=application_number,
                    address=" ".join(
                        part
                        for part in [
                            clean_text(detail.get("shemRehov")) or street_name or "",
                            clean_text(detail.get("misparBait")),
                        ]
                        if part
                    )
                    or None,
                    street_name=clean_text(detail.get("shemRehov")) or street_name,
                    house_number=clean_text(detail.get("misparBait")) or None,
                    application_type=clean_text(
                        detail.get("teurSugbakashaCodeMulti") or candidate.get("teurSugbakasha")
                    )
                    or None,
                    work_description=clean_text(detail.get("mahutBakasha") or candidate.get("mahut_bakasha"))
                    or None,
                    submission_date=submitted,
                    approval_date=approval_date,
                    is_approved=approved,
                    approval_confidence="high" if approved else None,
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
        return output
