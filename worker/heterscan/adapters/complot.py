from __future__ import annotations

import re
import threading
from datetime import date
from urllib.parse import urlencode

from lxml import html

from ..domain import ApplicationRecord, DiscoveredUnit, DiscoveryResult, SearchUnit
from ..http import AdaptiveRateLimiter, PublicHttpClient
from ..normalize import clean_text, in_range, normalized_key, parse_date
from .base import Adapter


class ComplotAdapter(Adapter):
    name = "complot"
    version = "0.2.0"
    autocomplete_url = "https://handasi.complot.co.il/wsComplotPublicData/ComplotPublicData.asmx/GetBakashot"

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
                "appname": "cixpa",
                "prgname": "GetBakashotByAddress",
                "siteid": self.config["site_id"],
                "grp": "0",
                "t": "1",
                "c": self.config.get("locality_code", self.city_id),
                "s": street_code,
                "h": "",
                "l": "false",
                "arguments": "siteId,grp,t,c,s,h,l",
            }
        )
        return f"https://handasi.complot.co.il/magicscripts/mgrqispi.dll?{query}"

    def _detail_url(self, request_number: str) -> str:
        query = urlencode(
            {
                "appname": "cixpa",
                "prgname": "GetBakashaFile",
                "siteid": self.config["site_id"],
                "b": request_number,
                "arguments": "siteid,b",
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
                    "licensing_number": (
                        cells[1].replace(number_match.group(1), "").strip() if len(cells) > 1 else ""
                    ),
                    "building_file": cells[2] if len(cells) > 2 else "",
                    "submission_date": cells[3] if len(cells) > 3 else "",
                    "address": cells[5] if len(cells) > 5 else "",
                    "block": cells[6] if len(cells) > 6 else "",
                    "parcel": cells[7] if len(cells) > 7 else "",
                }
            )
        return rows

    def _detail_fields(self, document_or_markup) -> dict[str, str]:
        document = (
            html.fromstring(document_or_markup) if isinstance(document_or_markup, str) else document_or_markup
        )
        fields: dict[str, str] = {}
        sections = document.xpath("//div[@id='info-main']//tr") or document.xpath("//table//tr")
        for tr in sections:
            cells = [self._text(cell) for cell in tr.xpath("./td")]
            if len(cells) >= 2 and cells[0]:
                fields[cells[0]] = " | ".join(cell for cell in cells[1:] if cell)
        return fields

    def _table_rows(self, document, table_id: str) -> list[dict[str, str]]:
        rows = document.xpath(f"//*[@id='{table_id}']//tr")
        if not rows:
            return []
        headers = [self._text(cell) for cell in rows[0].xpath("./th|./td")]
        output: list[dict[str, str]] = []
        for tr in rows[1:]:
            cells = [self._text(cell) for cell in tr.xpath("./th|./td")]
            if len(cells) != len(headers):
                continue
            row = {header: value for header, value in zip(headers, cells) if header}
            if any(row.values()):
                output.append(row)
        return output

    def _detail_metadata(self, document) -> dict[str, str]:
        nodes = document.xpath("//*[@id='result-title-div-id']")
        title = self._text(nodes[0]) if nodes else ""
        number_match = re.search(r"מספר הבקשה:\s*(\d+)", title)
        address_match = re.search(r"כתובת:\s*(.*?)\s*תאריך הגשה:", title)
        date_match = re.search(r"תאריך הגשה:\s*(\d{1,2}/\d{1,2}/\d{4})", title)
        return {
            "request_number": number_match.group(1) if number_match else "",
            "address": clean_text(address_match.group(1)) if address_match else "",
            "submission_date": date_match.group(1) if date_match else "",
        }

    @staticmethod
    def _field(fields: dict[str, str], *terms: str) -> str:
        normalized = [(normalized_key(key), value) for key, value in fields.items()]
        for term in terms:
            key_term = normalized_key(term)
            for key, value in normalized:
                if key_term in key:
                    return value
        return ""

    @staticmethod
    def _joined_values(rows: list[dict[str, str]], key: str) -> str | None:
        values = list(dict.fromkeys(clean_text(row.get(key)) for row in rows if clean_text(row.get(key))))
        return ", ".join(values) or None

    def _discover_prefix(self, unit: SearchUnit) -> DiscoveryResult:
        prefix = clean_text(unit.payload.get("prefix"))
        year = clean_text(unit.payload.get("year")) or prefix[:4]
        request_number_length = max(5, int(self.config.get("request_number_length", 8)))
        response = self.client.request(
            "POST",
            self.autocomplete_url,
            json={"site_id": int(self.config["site_id"]), "key": "0", "prefix": int(prefix)},
        )
        items = response.json().get("d") or []
        labels = list(
            dict.fromkeys(
                clean_text(item.get("label"))
                for item in items
                if isinstance(item, dict) and clean_text(item.get("label")).isdigit()
            )
        )
        units = [
            DiscoveredUnit(
                unit_key=f"request:{number}",
                payload={"mode": "request", "requestNumber": number},
            )
            for number in labels
            if len(number) == request_number_length and number.startswith(year)
        ]
        # The autocomplete returns at most ten rows. Split a full page into
        # durable child prefixes, so cancellation or 429 never repeats a year.
        # With one digit left there are at most ten possible request numbers,
        # all already present in this response. Splitting that final digit
        # would only repeat one request per child prefix.
        if len(items) >= 10 and len(prefix) < request_number_length - 1:
            units.extend(
                DiscoveredUnit(
                    unit_key=f"discover-prefix:{prefix}{digit}",
                    payload={"mode": "discover-prefix", "prefix": f"{prefix}{digit}", "year": year},
                )
                for digit in range(10)
            )
        return DiscoveryResult(units=units)

    def _record_from_detail(
        self, request_number: str, markup: str, *, cached: dict | None = None
    ) -> ApplicationRecord:
        cached = cached or {}
        document = html.fromstring(markup)
        metadata = self._detail_metadata(document)
        fields = self._detail_fields(document)
        events = self._table_rows(document, "table-events")
        requirements = self._table_rows(document, "table-requirments")
        parcels = self._table_rows(document, "table-gushim-helkot")
        meetings = self._table_rows(document, "table-meetings")
        current_event = next(
            (row for row in events if normalized_key(row.get("סוג אירוע")) == normalized_key("נוכחי")),
            None,
        )

        submitted = parse_date(metadata.get("submission_date") or cached.get("submissionDate"))
        permit_number = clean_text(self._field(fields, "מספר היתר")) or None
        permit_date = parse_date(self._field(fields, "תאריך הפקת היתר", "תאריך היתר"))
        explicit_status = clean_text(self._field(fields, "סטטוס", "מצב בקשה"))
        current_status = clean_text((current_event or {}).get("תיאור אירוע"))
        permit_status = explicit_status or current_status or None
        status_key = normalized_key(permit_status)
        issued = bool(
            (permit_number and permit_date)
            or (
                permit_date
                and "היתר" in status_key
                and any(term in status_key for term in ("הופק", "הוצא", "בתוקף"))
            )
        )
        approval_date = parse_date(self._field(fields, "תאריך אישור", "תאריך החלטה"))
        is_approved = issued or bool(approval_date and "אושר" in status_key)
        detail_url = self._detail_url(request_number)
        mahut_nodes = document.xpath("//*[@id='mahut']")
        mahut = self._text(mahut_nodes[0]) if mahut_nodes else ""
        if mahut.startswith("מהות הבקשה"):
            mahut = clean_text(mahut[len("מהות הבקשה") :])

        raw_data = {
            "metadata": metadata,
            "detail": fields,
            "events": events,
            "requirements": requirements,
            "parcels": parcels,
            "meetings": meetings,
        }
        return ApplicationRecord(
            city_id=self.city_id,
            application_number=request_number,
            building_file_number=(
                clean_text(self._field(fields, "מספר תיק בניין"))
                or clean_text(cached.get("buildingFile"))
                or None
            ),
            address=clean_text(metadata.get("address") or cached.get("address")) or None,
            street_name=clean_text(cached.get("streetName")) or None,
            block_number=(
                self._joined_values(parcels, "מספר גוש") or clean_text(cached.get("block")) or None
            ),
            parcel_number=(
                self._joined_values(parcels, "מספר חלקה") or clean_text(cached.get("parcel")) or None
            ),
            application_type=clean_text(self._field(fields, "סוג בקשה")) or None,
            work_description=(mahut or clean_text(self._field(fields, "תיאור הבקשה", "מהות הבקשה")) or None),
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
            source_reference=request_number,
            adapter_name=self.name,
            adapter_version=self.version,
            raw_data=raw_data,
            evidence=[
                {
                    "type": "direct_application_refresh",
                    "permit_number": permit_number,
                    "permit_issue_date": str(permit_date or ""),
                    "status": permit_status,
                    "current_event": current_event,
                }
            ],
        )

    def collect(
        self, unit: SearchUnit, date_from: date, date_to: date
    ) -> list[ApplicationRecord] | DiscoveryResult:
        mode = clean_text(unit.payload.get("mode"))
        if mode == "discover-prefix":
            return self._discover_prefix(unit)
        if mode == "request":
            request_number = clean_text(unit.payload.get("requestNumber"))
            markup = self.client.request("GET", self._detail_url(request_number)).text
            record = self._record_from_detail(request_number, markup, cached=unit.payload)
            return [record] if in_range(record.submission_date, date_from, date_to) else []

        # Backward compatibility for runs created by the former street strategy.
        street_code = clean_text(unit.payload.get("streetCode"))
        street_name = clean_text(unit.payload.get("streetName")) or None
        markup = self.client.request("GET", self._list_url(street_code)).text
        output: list[ApplicationRecord] = []
        for row in self._list_rows(markup):
            submitted = parse_date(row["submission_date"])
            if not in_range(submitted, date_from, date_to):
                continue
            detail_markup = self.client.request("GET", self._detail_url(row["request_number"])).text
            output.append(
                self._record_from_detail(
                    row["request_number"],
                    detail_markup,
                    cached={
                        "submissionDate": row["submission_date"],
                        "buildingFile": row["building_file"],
                        "address": row["address"],
                        "streetName": street_name,
                        "block": row["block"],
                        "parcel": row["parcel"],
                    },
                )
            )
        return output
