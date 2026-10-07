from __future__ import annotations

import re
import threading
from datetime import date
from urllib.parse import quote, urlencode, urlsplit

from lxml import etree, html

from ..domain import AdapterRateLimited, AdapterReviewRequired, ApplicationRecord, DiscoveredUnit, DiscoveryResult, SearchUnit
from ..http import AdaptiveRateLimiter, PublicHttpClient, _challenge_diagnostics
from ..normalize import clean_text, in_range, normalized_key, parse_date
from .base import Adapter


class ComplotAdapter(Adapter):
    name = "complot"
    version = "0.4.1"
    autocomplete_url = "https://handasi.complot.co.il/wsComplotPublicData/ComplotPublicData.asmx/GetBakashot"

    def __init__(self, city_id: str, city_name: str, config: dict, *, coordinator=None) -> None:
        super().__init__(city_id, city_name, config)
        self.collection_mode = config.get("collection_mode", "full_details")
        if self.collection_mode not in {"full_details", "public_summary"}:
            raise ValueError("Unknown Complot collection mode")
        self.maximum_parallelism = 1
        self._parallelism = self.maximum_parallelism
        self._clean_waves = 0
        self._tuning_lock = threading.Lock()
        self._range_counts = {"parsed_requests": 0, "before_range": 0, "after_range": 0, "in_range": 0}
        initial_rate = min(0.25, float(config.get("initial_requests_per_second", 0.25)))
        self.rate_limiter = AdaptiveRateLimiter(
            requests_per_second=initial_rate,
            target_requests_per_second=min(1.0, float(config.get("target_requests_per_second", 1.0))),
            minimum_requests_per_second=min(0.25, float(config.get("minimum_requests_per_second", 0.25))),
            maximum_requests_per_second=min(1.0, float(config.get("maximum_requests_per_second", 1.0))),
            success_window=200,
            origin="handasi.complot.co.il",
            coordinator=coordinator,
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
        with self._tuning_lock:
            counts = dict(self._range_counts)
        traffic = self.client.statistics() if hasattr(self.client, "statistics") else {}
        return {"origin": "handasi.complot.co.il", "parallelism": self.parallelism(),
                **self.rate_limiter.snapshot(), "endpoints": traffic, **counts}

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
        # A display-only SPA hash is not an HTTP data endpoint. Use a municipal
        # endpoint only after its ordinary public request has been documented.
        template = self.config.get("public_detail_url_template")
        if template:
            try:
                target = str(template).format(
                    request_number=quote(request_number, safe=""),
                    site_id=quote(str(self.config["site_id"]), safe=""),
                )
                parsed = urlsplit(target)
                public_host = urlsplit(str(self.config.get("public_search_url", ""))).hostname
                if (not self.config.get("public_detail_route_evidence")
                        or "{request_number}" not in str(template)
                        or parsed.scheme != "https" or not public_host
                        or parsed.hostname != public_host or parsed.fragment
                        or parsed.port not in {None, 443}
                        or parsed.username or parsed.password):
                    raise ValueError("unverified public detail endpoint")
                return target
            except (KeyError, IndexError, ValueError) as error:
                raise AdapterReviewRequired(
                    "מסלול הפרטים הציבורי אינו מוגדר עם ראיה תקינה; מצב ההיתר לא ידוע.",
                    diagnostics={"detail_state": "route_unverified", "detail_requested": False},
                ) from error
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

    def _number_list_url(self, request_number: str) -> str:
        query = urlencode({
            "appname": "cixpa", "prgname": "GetBakashotByNumber", "siteid": self.config["site_id"],
            "grp": "0", "t": "0", "b": request_number, "l": "true", "arguments": "siteId,grp,t,b,l",
        })
        return f"https://handasi.complot.co.il/magicscripts/mgrqispi.dll?{query}"

    def _summary_source_url(self, request_number: str) -> str:
        public_url = self.config.get("public_search_url")
        if public_url:
            return (f"{str(public_url).rstrip('/')}/#search/GetBakashotByNumber"
                    f"&siteid={self.config['site_id']}&grp=0&t=0&b={request_number}"
                    "&l=true&arguments=siteId,grp,t,b,l")
        if str(self.config.get("site_id")) == "87":
            return self._public_source_url(request_number)
        return self._number_list_url(request_number)

    def _public_source_url(self, request_number: str) -> str:
        if self.config.get("public_detail_url_template") and self.config.get("public_search_url"):
            return f"{str(self.config['public_search_url']).rstrip('/')}/#request/{quote(request_number, safe='')}"
        if self.config.get("public_search_url"):
            return self._summary_source_url(request_number)
        if str(self.config.get("site_id")) == "87":
            return (
                "https://yavne.complot.co.il/iturbakashot2/"
                "#search/GetBakashotByNumber&siteid=87&grp=0&t=0"
                f"&b={request_number}&l=true&arguments=siteId,grp,t,b,l"
            )
        return self._detail_url(request_number)

    def _list_rows(self, markup: str) -> list[dict[str, str]]:
        try:
            document = html.fromstring(markup)
        except (etree.ParserError, ValueError) as error:
            raise AdapterReviewRequired(
                "דף החיפוש ריק או פגום; לא ניתן להסיק שאין בקשות.",
                diagnostics={**_challenge_diagnostics(markup), "parser_result": "parser_mismatch"},
            ) from error
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
        if not rows:
            # An HTML search with no identifiable rows is not an independently
            # verified zero, including legacy street units.
            raise AdapterReviewRequired(
                "לא זוהו שורות בקשה בדף החיפוש; תוצאת האפס לא אומתה.",
                diagnostics={**_challenge_diagnostics(markup), "parser_result": "parser_mismatch"},
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
                value = " | ".join(cell for cell in cells[1:] if cell)
                previous = fields.get(cells[0])
                if previous and value and previous != value:
                    raise AdapterReviewRequired(
                        "שדה בפרטי המקור מכיל ערכים סותרים; נדרשת בדיקה.",
                        diagnostics={"parser_result": "field_conflict", "field": cells[0],
                                     "observed_values": [previous, value]},
                    )
                fields[cells[0]] = previous or value
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
        number_match = re.search(r"מספר הבקשה:\s*([0-9/.]+)", title)
        address_match = re.search(r"כתובת:\s*(.*?)\s*תאריך הגשה:", title)
        date_match = re.search(r"תאריך הגשה:\s*([0-9./-]+)", title)
        return {
            "request_number": number_match.group(1) if number_match else "",
            "address": clean_text(address_match.group(1)) if address_match else "",
            "submission_date": date_match.group(1) if date_match else "",
        }

    @staticmethod
    def _field(fields: dict[str, str], *terms: str, exact: bool = False) -> str:
        normalized = [(normalized_key(key), value) for key, value in fields.items()]
        for term in terms:
            key_term = normalized_key(term)
            for key, value in normalized:
                if (key == key_term) if exact else (key_term in key):
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
        try:
            data = response.json()
        except ValueError as error:
            raise AdapterReviewRequired(
                "לא ניתן לפענח את תשובת החיפוש; לא ניתן להסיק שאין בקשות.",
                diagnostics={**getattr(response, "extensions", {}).get("source_diagnostics", {}),
                             "parser_result": "parser_mismatch"},
            ) from error
        if not isinstance(data, dict) or not isinstance(data.get("d"), list):
            raise AdapterReviewRequired("מבנה תשובת החיפוש אינו תקין; לא ניתן להסיק שאין בקשות.")
        items = data["d"]
        invalid_labels = any(
            not isinstance(item, dict) or not clean_text(item.get("label")).isdigit()
            for item in items
        )
        labels = list(
            dict.fromkeys(
                clean_text(item.get("label"))
                for item in items
                if isinstance(item, dict) and clean_text(item.get("label")).isdigit()
            )
        )
        too_long_lengths = sorted({len(number) for number in labels if len(number) > request_number_length})
        issues = []
        if invalid_labels:
            issues.append("תשובת החיפוש מכילה מזהי בקשה שלא ניתן לפענח")
        if any(not number.startswith(prefix) or not number.startswith(year) for number in labels):
            issues.append("תשובת החיפוש מכילה מזהים מחוץ לקידומת המבוקשת; הכיסוי דורש בדיקה")
        if too_long_lengths:
            observed = ", ".join(str(length) for length in too_long_lengths)
            issues.append(
                "אורך מספר הבקשה שהוגדר לרשות אינו תואם למקור: "
                f"הוגדר {request_number_length}, התקבל {observed}"
            )
        request_labels = [
            number
            for number in labels
            if len(number) >= 5
            and number.startswith(year)
            and number.startswith(prefix)
        ]
        units = [
            DiscoveredUnit(
                unit_key=f"request:{number}",
                payload={"mode": "request", "requestNumber": number,
                         "discoveryEvidence": {"prefix": prefix, "rawLabel": number,
                                               "configuredLength": request_number_length,
                                               "identityVerified": False}},
            )
            for number in request_labels
        ]
        returned_child_prefixes = [
            number
            for number in labels
            if number.startswith(prefix)
            and number.startswith(year)
            and len(prefix) < len(number) < request_number_length
        ]
        # The autocomplete returns at most ten rows. Split a full page into
        # durable child prefixes, so cancellation or 429 never repeats a year.
        # With one digit left there are at most ten possible request numbers,
        # all already present in this response. Splitting that final digit
        # would only repeat one request per child prefix.
        child_prefixes = list(dict.fromkeys(returned_child_prefixes))
        # A capped response containing longer identifiers can still hide their
        # siblings at the configured last digit. Continue to the observed depth.
        observed_length = max([request_number_length, *(len(number) for number in request_labels)])
        if len(items) >= 10 and len(prefix) < observed_length - 1:
            child_prefixes = list(
                dict.fromkeys([*child_prefixes, *(f"{prefix}{digit}" for digit in range(10))])
            )
        units.extend(
            DiscoveredUnit(
                unit_key=f"discover-prefix:{child_prefix}",
                payload={"mode": "discover-prefix", "prefix": child_prefix, "year": year},
            )
            for child_prefix in child_prefixes
        )
        if labels and not request_labels and not child_prefixes:
            observed = ", ".join(str(length) for length in sorted({len(number) for number in labels}))
            issues.append(
                "לא ניתן לזהות מספרי בקשה באורך שהוגדר לרשות: "
                f"הוגדר {request_number_length}, התקבל {observed}"
            )
        return DiscoveryResult(
            units=units, review_reason="; ".join(issues) or None,
            diagnostics={"prefix": prefix, "configured_length": request_number_length,
                         "observed_labels": [clean_text(item.get("label")) if isinstance(item, dict)
                                             else clean_text(item) for item in items],
                         "response_capped": len(items) >= 10,
                         "coverage_verified": False},
        )

    def _record_from_detail(
        self, request_number: str, markup: str, *, cached: dict | None = None
    ) -> ApplicationRecord:
        cached = cached or {}
        diagnostics = _challenge_diagnostics(markup)
        try:
            document = html.fromstring(markup)
        except (etree.ParserError, ValueError) as error:
            raise AdapterReviewRequired(
                "פרטי הבקשה ריקים או פגומים; מצב ההיתר לא ידוע.",
                diagnostics={**diagnostics, "parser_result": "detail_missing"},
            ) from error
        metadata = self._detail_metadata(document)
        observed_number = re.sub(r"\D", "", metadata.get("request_number", ""))
        if observed_number != re.sub(r"\D", "", request_number):
            raise AdapterReviewRequired(
                "פרטי המקור אינם מזהים את הבקשה שהתבקשה; נדרשת בדיקת מקור.",
                diagnostics={
                    **diagnostics,
                    "parser_result": ("identity_mismatch" if observed_number else
                                      "parser_mismatch" if document.xpath("//*[@id='result-title-div-id']")
                                      else "detail_missing"),
                    "requested_number": request_number, "observed_number": observed_number,
                    "title_container": bool(document.xpath("//*[@id='result-title-div-id']")),
                    # Public display text only: exclude scripts, styles and form values.
                    "source_excerpt": clean_text(" ".join(document.xpath(
                        ".//text()[not(ancestor::script or ancestor::style or ancestor::form)]"
                    )))[:300],
                },
            )
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
        if submitted is None:
            raise AdapterReviewRequired(
                "חסר תאריך הגשה תקין במקור; לא ניתן לבדוק את טווח התאריכים.",
                diagnostics={**diagnostics, "parser_result": "parser_mismatch",
                             "request_number": request_number, "date_text": metadata.get("submission_date"),
                             "date_field_labels": [key for key in fields if "תאריך" in key][:10]},
            )
        if not diagnostics["request_detail_markup"] or not (fields or events or requirements or parcels or meetings):
            raise AdapterReviewRequired(
                "מבנה פרטי הבקשה חסר; מצב ההיתר לא ידוע.",
                diagnostics={**diagnostics, "parser_result": "detail_missing"},
            )
        permit_number = clean_text(self._field(fields, "מספר היתר", exact=True)) or None
        if permit_number in {"0", "-", "—"}:
            permit_number = None
        permit_date = parse_date(self._field(fields, "תאריך הפקת היתר", "תאריך היתר", exact=True))
        explicit_status = clean_text(self._field(fields, "סטטוס", "מצב בקשה"))
        current_status = clean_text((current_event or {}).get("תיאור אירוע"))
        permit_status = explicit_status or current_status or None
        status_key = normalized_key(permit_status)
        # Complot has no independently verified event-only issuance rule.
        issued = bool(permit_number and permit_date)
        approval_date = parse_date(self._field(fields, "תאריך אישור", "תאריך החלטה"))
        is_approved = issued or bool(approval_date and "אושר" in status_key)
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
            "date_basis": "submission_date",
            "verification_scope": {
                "discovery_coverage": "not_verified", "request_identity": "matched",
                "details": "available", "status": "read" if permit_status else "unknown",
                "permit": "verified_issued" if issued else "unknown",
            },
        }
        if isinstance(cached.get("public_summary"), dict):
            raw_data["public_summary"] = cached["public_summary"]
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
            application_type=clean_text(self._field(fields, "סוג הבקשה", "סוג בקשה")) or None,
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
            source_url=self._public_source_url(request_number),
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
            summary_url = self._number_list_url(request_number)
            summary_response = self.client.request("GET", summary_url)
            summary_markup = summary_response.text
            matches = [row for row in self._list_rows(summary_markup) if row["request_number"] == request_number]
            if len(matches) != 1:
                raise AdapterReviewRequired("לא נמצא רישום פומבי חד־משמעי לבקשה בחיפוש העירוני.")
            row = matches[0]
            submitted = parse_date(row["submission_date"])
            if submitted is None:
                raise AdapterReviewRequired("חסר תאריך הגשה תקין בתוצאת החיפוש העירוני.")
            with self._tuning_lock:
                self._range_counts["parsed_requests"] += 1
                bucket = "before_range" if submitted < date_from else "after_range" if submitted > date_to else "in_range"
                self._range_counts[bucket] += 1
            if not in_range(submitted, date_from, date_to):
                return []
            summary = ApplicationRecord(
                city_id=self.city_id, application_number=request_number, address=row["address"] or None,
                submission_date=submitted, building_file_number=row["building_file"] or None,
                block_number=row["block"] or None, parcel_number=row["parcel"] or None,
                source_url=self._summary_source_url(request_number), source_reference=request_number,
                adapter_name=self.name, adapter_version=self.version,
                raw_data={"public_summary": row, "details_available": False,
                          "date_basis": "submission_date",
                          "verification_scope": {"discovery_coverage": "not_verified",
                              "request_identity": "summary_matched", "details": "unavailable",
                              "status": "unknown", "permit": "unknown"}}, details_available=False,
            )
            summary.raw_data["field_provenance"] = {
                field: {"kind": "public_search_summary", "source_url": summary_url,
                        "display_url": summary.source_url}
                for field, value in (("application_number", request_number), ("address", summary.address),
                                     ("submission_date", submitted),
                                     ("building_file_number", summary.building_file_number),
                                     ("block_number", summary.block_number), ("parcel_number", summary.parcel_number))
                if value
            }
            if self.collection_mode == "public_summary":
                diagnostics = {
                    **getattr(summary_response, "extensions", {}).get("source_diagnostics", {}),
                    "collection_mode": "public_summary", "detail_requested": False,
                    "parser_result": "summary_parsed", "detail_state": "not_requested",
                }
                summary.raw_data["source_diagnostics"] = diagnostics
                raise AdapterReviewRequired(
                    "נאסף סיכום הבקשה בלבד; פרטים ומצב היתר לא אומתו.",
                    diagnostics=diagnostics, partial_records=[summary],
                )
            response = None
            detail_url = None
            try:
                detail_url = self._detail_url(request_number)
                response = self.client.request("GET", detail_url)
                markup = response.text
                record = self._record_from_detail(request_number, markup, cached={
                    **unit.payload, "submissionDate": row["submission_date"], "address": row["address"],
                    "buildingFile": row["building_file"], "block": row["block"], "parcel": row["parcel"],
                    "public_summary": row,
                })
                record.raw_data["source_diagnostics"] = {
                    **getattr(response, "extensions", {}).get("source_diagnostics", {}),
                    "parser_result": "parsed", "detail_url": detail_url,
                    "detail_route": "documented_public_endpoint" if self.config.get("public_detail_url_template")
                                    else "legacy_shared_dll",
                    "detail_route_evidence": self.config.get("public_detail_route_evidence"),
                }
                record.raw_data["field_provenance"] = {
                    field: {"kind": "public_request_detail", "source_url": detail_url}
                    for field, value in (("application_number", request_number), ("address", record.address),
                                         ("submission_date", record.submission_date),
                                         ("permit_number", record.permit_number),
                                         ("permit_issue_date", record.permit_issue_date),
                                         ("permit_status_original", record.permit_status_original)) if value
                }
                for field, detail_value, record_value in (
                    ("building_file_number", self._field(record.raw_data["detail"], "מספר תיק בניין"),
                     record.building_file_number),
                    ("block_number", self._joined_values(record.raw_data["parcels"], "מספר גוש"), record.block_number),
                    ("parcel_number", self._joined_values(record.raw_data["parcels"], "מספר חלקה"), record.parcel_number),
                    ("address", record.raw_data["metadata"].get("address"), record.address),
                    ("submission_date", record.raw_data["metadata"].get("submission_date"), record.submission_date),
                ):
                    if record_value:
                        record.raw_data["field_provenance"][field] = {
                            "kind": "public_request_detail" if detail_value else "public_search_summary",
                            "source_url": detail_url if detail_value else summary_url,
                        }
                record.raw_data["raw_field_provenance"] = {
                    key: {"source_url": detail_url, "value": value}
                    for key, value in record.raw_data["detail"].items()
                }
                # The validator compares detail and public-search dates before
                # any record can be removed from the requested range.
                return [record]
            except AdapterReviewRequired as error:
                if response is not None:
                    error.diagnostics = {
                        **getattr(response, "extensions", {}).get("source_diagnostics", {}),
                        **error.diagnostics,
                    }
                error.diagnostics = {**error.diagnostics, "requested_number": request_number,
                                     "summary_url": summary_url, "detail_url": detail_url,
                                     "date_basis": "submission_date"}
                summary.raw_data["source_diagnostics"] = dict(error.diagnostics)
                error.partial_records = [summary]
                raise
            except AdapterRateLimited:
                raise
            except RuntimeError as error:
                diagnostics = {"detail_error": str(error)[:500], "detail_url": detail_url,
                               "requested_number": request_number, "summary_url": summary_url,
                               "detail_state": "unavailable"}
                summary.raw_data["source_diagnostics"] = diagnostics
                raise AdapterReviewRequired(
                    "פרטי הבקשה לא נטענו; נשמר המידע הפומבי מתוצאת החיפוש.",
                    diagnostics=diagnostics, partial_records=[summary],
                ) from error

        # Backward compatibility for runs created by the former street strategy.
        if self.collection_mode == "public_summary":
            raise AdapterReviewRequired("מצב סיכומי בקשות מחייב יחידות חיפוש לפי מספר בקשה.")
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
                        "public_summary": row,
                    },
                )
            )
        return output
