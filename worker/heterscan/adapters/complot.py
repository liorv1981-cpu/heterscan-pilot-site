from __future__ import annotations

import re
import threading
from datetime import date
from urllib.parse import urlencode

from lxml import html

from ..domain import ApplicationRecord, SearchUnit
from ..http import AdaptiveRateLimiter, PublicHttpClient
from ..normalize import clean_text, in_range, normalized_key, parse_date
from .base import Adapter


class ComplotAdapter(Adapter):
    name = "complot"

    def __init__(self, city_id: str, city_name: str, config: dict) -> None:
        super().__init__(city_id, city_name, config)
        self.maximum_parallelism = max(1, min(6, int(config.get("max_parallelism", 4))))
        self._parallelism = self.maximum_parallelism
        self._clean_waves = 0
        self._tuning_lock = threading.Lock()
        initial_rate = float(config.get("initial_requests_per_second", 1.0))
        self.rate_limiter = AdaptiveRateLimiter(
            requests_per_second=initial_rate,
            target_requests_per_second=float(config.get("target_requests_per_second", 2.0)),
            minimum_requests_per_second=float(config.get("minimum_requests_per_second", 0.25)),
            maximum_requests_per_second=float(config.get("maximum_requests_per_second", 2.0)),
        )
        self.client = PublicHttpClient(
            delay_seconds=0,
            timeout_seconds=float(config.get("timeout_seconds", 60)),
            rate_limiter=self.rate_limiter,
            max_connections=max(8, self.maximum_parallelism * 3),
        )

    def close(self) -> None:
        self.client.close()

    def parallelism(self) -> int:
        with self._tuning_lock:
            return self._parallelism

    def observe_wave(self, *, errors: int, elapsed_seconds: float, units: int) -> None:
        average_seconds = elapsed_seconds / max(1, units)
        with self._tuning_lock:
            if errors >= max(2, units // 2):
                self._parallelism = max(1, self._parallelism // 2)
                self._clean_waves = 0
            elif errors or average_seconds > 45:
                self._parallelism = max(1, self._parallelism - 1)
                self._clean_waves = 0
            else:
                self._clean_waves += 1
                if self._clean_waves >= 3 and self._parallelism < self.maximum_parallelism:
                    self._parallelism += 1
                    self._clean_waves = 0

    def performance_snapshot(self) -> dict[str, float | int]:
        return {"parallelism": self.parallelism(), **self.rate_limiter.snapshot()}

    @staticmethod
    def _text(node) -> str:
        return clean_text(" ".join(node.itertext()) if node is not None else "")

    def _list_url(self, street_code: str) -> str:
        query = urlencode(
            {
                "appname": "cixpa", "prgname": "GetBakashotByAddress", "siteid": self.config["site_id"],
                "grp": "0", "t": "1", "c": self.config.get("locality_code", self.city_id),
                "s": street_code, "h": "", "l": "false", "arguments": "siteId,grp,t,c,s,h,l",
            }
        )
        return f"https://handasi.complot.co.il/magicscripts/mgrqispi.dll?{query}"

    def _detail_url(self, request_number: str) -> str:
        query = urlencode(
            {
                "appname": "cixpa", "prgname": "GetBakashaFile", "siteid": self.config["site_id"],
                "b": request_number, "arguments": "siteid,b",
            }
        )
        return f"https://handasi.complot.co.il/magicscripts/mgrqispi.dll?{query}"

    def _list_rows(self, markup: str) -> list[dict[str, str]]:
        document = html.fromstring(markup)
        rows: list[dict[str, str]] = []
        for tr in document.xpath("//tbody/tr"):
            row_html = html.tostring(tr, encoding="unicode")
            number_match = re.search(r"getRequest\((\d+)\)", row_html)
            if not number_match:
                continue
            cells = [self._text(cell) for cell in tr.xpath("./td")]
            rows.append(
                {
                    "request_number": number_match.group(1),
                    "licensing_number": (cells[1].replace(number_match.group(1), "").strip() if len(cells) > 1 else ""),
                    "building_file": cells[2] if len(cells) > 2 else "",
                    "submission_date": cells[3] if len(cells) > 3 else "",
                    "address": cells[5] if len(cells) > 5 else "",
                    "block": cells[6] if len(cells) > 6 else "",
                    "parcel": cells[7] if len(cells) > 7 else "",
                }
            )
        return rows

    def _detail_fields(self, markup: str) -> dict[str, str]:
        document = html.fromstring(markup)
        fields: dict[str, str] = {}
        sections = document.xpath("//div[@id='info-main']//tr") or document.xpath("//table//tr")
        for tr in sections:
            cells = [self._text(cell) for cell in tr.xpath("./td")]
            if len(cells) >= 2 and cells[0]:
                fields[cells[0]] = " | ".join(cell for cell in cells[1:] if cell)
        return fields

    @staticmethod
    def _field(fields: dict[str, str], *terms: str) -> str:
        normalized = [(normalized_key(key), value) for key, value in fields.items()]
        for term in terms:
            key_term = normalized_key(term)
            for key, value in normalized:
                if key_term in key:
                    return value
        return ""

    def collect(self, unit: SearchUnit, date_from: date, date_to: date) -> list[ApplicationRecord]:
        street_code = clean_text(unit.payload.get("streetCode"))
        street_name = clean_text(unit.payload.get("streetName")) or None
        list_url = self._list_url(street_code)
        output: list[ApplicationRecord] = []
        markup = self.client.request("GET", list_url).text
        for row in self._list_rows(markup):
            submitted = parse_date(row["submission_date"])
            if not in_range(submitted, date_from, date_to):
                continue
            detail_url = self._detail_url(row["request_number"])
            detail_markup = self.client.request("GET", detail_url).text
            fields = self._detail_fields(detail_markup)
            permit_number = clean_text(self._field(fields, "מספר היתר")) or None
            permit_date = parse_date(self._field(fields, "תאריך הפקת היתר", "תאריך היתר"))
            permit_status = clean_text(self._field(fields, "סטטוס", "מצב בקשה")) or None
            explicit_status = normalized_key(permit_status)
            issued = bool(
                (permit_number and permit_date)
                or (permit_date and "היתר" in explicit_status and any(term in explicit_status for term in ("הופק", "הוצא", "בתוקף")))
            )
            approval_date = parse_date(self._field(fields, "תאריך אישור", "תאריך החלטה"))
            is_approved = issued or bool(approval_date and "אושר" in explicit_status)
            raw_data = {"list": row, "detail": fields}
            output.append(
                ApplicationRecord(
                    city_id=self.city_id,
                    application_number=row["request_number"],
                    building_file_number=row["building_file"] or None,
                    address=row["address"] or None,
                    street_name=street_name,
                    block_number=row["block"] or None,
                    parcel_number=row["parcel"] or None,
                    application_type=clean_text(self._field(fields, "סוג בקשה")) or None,
                    work_description=clean_text(self._field(fields, "תיאור הבקשה", "מהות הבקשה")) or None,
                    submission_date=submitted,
                    approval_date=approval_date,
                    is_approved=is_approved,
                    approval_confidence="high" if approval_date else ("medium" if is_approved else None),
                    permit_number=permit_number,
                    permit_issue_date=permit_date,
                    permit_status_original=permit_status,
                    is_permit_issued=issued,
                    permit_confidence="high" if permit_number and permit_date else ("medium" if issued else None),
                    source_url=detail_url,
                    source_reference=row["request_number"],
                    adapter_name=self.name,
                    adapter_version=self.version,
                    raw_data=raw_data,
                    evidence=[{"type": "detail_fields", "permit_number": permit_number, "permit_issue_date": str(permit_date or ""), "status": permit_status}],
                )
            )
        return output
