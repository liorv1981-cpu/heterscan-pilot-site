"""Check collected records against source payloads already fetched by adapters.

This stage never requests a municipal source. A mismatch keeps the candidate
visible as partial information and makes its work unit require review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from urllib.parse import parse_qs, unquote, urlsplit

from .domain import ApplicationRecord, SearchUnit
from .normalize import clean_text, in_range, normalized_key, parse_date

VERSION = "0.2.0"
TERMINAL_PERMIT_EVENTS = {
    normalized_key("הוצאת היתר בניה"),
    normalized_key("הוצאת היתר בנייה"),
    normalized_key("מסירת היתר בניה"),
    normalized_key("מסירת היתר בנייה"),
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    application_number: str | None


@dataclass(slots=True)
class ValidationResult:
    records: list[ApplicationRecord]
    issues: list[ValidationIssue]


def _number(value: object) -> str:
    return re.sub(r"\D", "", clean_text(value))


def _permit_number(value: object) -> str:
    number = clean_text(value)
    return "" if number in {"0", "-", "—"} else number


def _address(value: object, city_name: str) -> str:
    address = normalized_key(value)
    city = normalized_key(city_name)
    return address[: -len(city)].strip() if city and address.endswith(city) else address


def _field(fields: dict, *terms: str) -> str:
    for term in terms:
        target = normalized_key(term)
        for key, value in fields.items():
            if target in normalized_key(key):
                return clean_text(value)
    return ""


def _complot_address_evidence(record: ApplicationRecord, unit: SearchUnit, city_name: str) -> dict | None:
    """Corroborate a coarse summary address without discarding detail-only components."""
    raw = record.raw_data
    summary, metadata, fields = (raw.get(key) for key in ("public_summary", "metadata", "detail"))
    parcels = raw.get("parcels")
    if (not record.details_available or not all(isinstance(value, dict) for value in (summary, metadata, fields))
            or not isinstance(parcels, list) or len(parcels) != 1 or not isinstance(parcels[0], dict)):
        return None
    expected = _number(record.application_number)
    requested = _number(unit.payload.get("requestNumber"))
    if (not expected or (requested and requested != expected)
            or _number(summary.get("request_number")) != expected
            or _number(metadata.get("request_number")) != expected
            or record.submission_date is None
            or parse_date(summary.get("submission_date")) != record.submission_date
            or parse_date(metadata.get("submission_date")) != record.submission_date):
        return None
    summary_address = _address(summary.get("address"), city_name)
    detail_address = _address(metadata.get("address"), city_name)
    if any(re.search(r"[0-9]\s*(?:[^\w\s]|_)+\s*[0-9]", clean_text(value))
           for value in (summary.get("address"), metadata.get("address"))):
        return None
    # This rule only accepts a single explicit detail component after the same
    # street and positive house number. Ranges, fractions and other numbers
    # are not folded together. A suffix disagreement remains a conflict.
    pattern = r"(.+?)\s+([1-9][0-9]*)(?:\s*([א-ת]))?(?:\s+(0))?"
    coarse = re.fullmatch(pattern, summary_address)
    precise = re.fullmatch(pattern, detail_address)
    if (not coarse or not precise or coarse.group(3) or coarse.group(4)
            or coarse.group(1, 2) != precise.group(1, 2)
            or bool(precise.group(3)) + bool(precise.group(4)) != 1
            or _address(record.address, city_name) not in {summary_address, detail_address}):
        return None
    building = clean_text(summary.get("building_file"))
    block, parcel = clean_text(summary.get("block")), clean_text(summary.get("parcel"))
    land = parcels[0]
    if (not all(re.fullmatch(r"[0-9]+", value) for value in (building, block, parcel))
            or building != clean_text(_field(fields, "מספר תיק בניין"))
            or building != clean_text(record.building_file_number)
            or block != clean_text(land.get("מספר גוש"))
            or parcel != clean_text(land.get("מספר חלקה"))
            or block != clean_text(record.block_number) or parcel != clean_text(record.parcel_number)):
        return None
    return {"comparison": "summary_less_specific", "verified_scope": "street_and_house_number",
            "corroborating_fields": ["building_file_number", "block_number", "parcel_number"],
            "detail_extra_component": precise.group(3) or precise.group(4),
            "detail_extra_component_corroborated": False,
            "summary_address": summary.get("address"), "detail_address": metadata.get("address")}


def _issued_status(value: object) -> bool:
    status = normalized_key(value)
    return "היתר" in status and any(term in status for term in ("הופק", "הוצא", "בתוקף"))


def _valid_host(record: ApplicationRecord, adapter) -> bool:
    try:
        host = (urlsplit(record.source_url).hostname or "").lower()
        if record.adapter_name == "complot":
            public_url = adapter.config.get("public_search_url") if hasattr(adapter, "config") else None
            public_host = (urlsplit(str(public_url)).hostname or "").lower() if public_url else ""
            return host in {"handasi.complot.co.il", "yavne.complot.co.il", public_host}
        if record.adapter_name == "jerusalem":
            return host == "ykpubdata.jerusalem.muni.il"
        if record.adapter_name == "tel_aviv":
            return host == "gisn.tel-aviv.gov.il"
    except ValueError:
        return False
    return False


def _link_identifies_record(record: ApplicationRecord) -> bool:
    number = clean_text(record.application_number)
    if not number:
        return False
    try:
        parsed = urlsplit(record.source_url)
        if record.adapter_name == "complot":
            source_number = (parse_qs(parsed.query).get("b") or parse_qs(parsed.fragment).get("b") or [""])[0]
            if not source_number and parsed.fragment.startswith("request/"):
                source_number = parsed.fragment.removeprefix("request/").split("/", 1)[0]
            return _number(source_number) == _number(number)
        if record.adapter_name == "jerusalem":
            match = re.search(r"(?:\?|&)TikNum=([^&]+)", parsed.fragment)
            return bool(match and clean_text(unquote(match.group(1))) == number)
        if record.adapter_name == "tel_aviv":
            where = (parse_qs(parsed.query).get("where") or [""])[0]
            match = re.fullmatch(r"\s*request_num\s*=\s*(\d+)\s*", where)
            return bool(match and match.group(1) == number)
    except ValueError:
        return False
    return False


def _complot_issues(record: ApplicationRecord, unit: SearchUnit, city_name: str) -> tuple[list[str], dict | None]:
    raw = record.raw_data
    summary = raw.get("public_summary") if isinstance(raw.get("public_summary"), dict) else None
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None
    detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else {}
    issues = []
    compatible_address = _complot_address_evidence(record, unit, city_name) is not None
    expected = _number(record.application_number)
    requested = _number(unit.payload.get("requestNumber"))
    if requested and requested != expected:
        issues.append("candidate_number_mismatch")
    if summary is None:
        issues.append("public_summary_missing")
    else:
        if _number(summary.get("request_number")) != expected:
            issues.append("summary_number_mismatch")
        summary_date = parse_date(summary.get("submission_date"))
        if summary_date is None or summary_date != record.submission_date:
            issues.append("summary_date_mismatch")
        if (summary.get("address") and record.address
                and _address(summary["address"], city_name) != _address(record.address, city_name)
                and not compatible_address):
            issues.append("summary_address_mismatch")
    if record.details_available:
        if metadata is None or _number(metadata.get("request_number")) != expected:
            issues.append("detail_number_mismatch")
        if metadata is None or parse_date(metadata.get("submission_date")) != record.submission_date:
            issues.append("detail_date_mismatch")
        if metadata and metadata.get("address") and summary and summary.get("address"):
            if (_address(metadata["address"], city_name) != _address(summary["address"], city_name)
                    and not compatible_address):
                issues.append("detail_address_mismatch")
        raw_permit = _permit_number(_field(detail, "מספר היתר"))
        raw_date = parse_date(_field(detail, "תאריך הפקת היתר", "תאריך היתר"))
        raw_status = _field(detail, "סטטוס", "מצב בקשה") or record.permit_status_original
        explicit_issued = bool(raw_date and (raw_permit or _issued_status(raw_status)))
        if bool(record.is_permit_issued) != explicit_issued:
            issues.append("permit_issuance_mismatch")
        if record.permit_number and _permit_number(record.permit_number) != raw_permit:
            issues.append("permit_number_mismatch")
        if record.permit_issue_date and record.permit_issue_date != raw_date:
            issues.append("permit_date_mismatch")
        if (raw_permit and not raw_date) or (raw_date and not explicit_issued):
            issues.append("permit_evidence_incomplete")
    return issues, summary


def _jerusalem_issues(record: ApplicationRecord) -> list[str]:
    raw = record.raw_data
    candidate = raw.get("candidate") if isinstance(raw.get("candidate"), dict) else {}
    detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else {}
    process = raw.get("process") if isinstance(raw.get("process"), list) else []
    issues = []
    if clean_text(candidate.get("tik_num")) != clean_text(record.application_number):
        issues.append("candidate_number_mismatch")
    dates = {
        parsed for row in process if isinstance(row, dict)
        if (parsed := parse_date(row.get("execDateStr"))) is not None
    }
    if record.submission_date not in dates:
        issues.append("submission_event_missing")
    street = clean_text(detail.get("shemRehov"))
    if street and street not in clean_text(record.address):
        issues.append("detail_address_mismatch")
    house_number = clean_text(detail.get("misparBait"))
    if house_number and house_number not in clean_text(record.address):
        issues.append("detail_house_number_mismatch")
    status = detail.get("teurStatus") or candidate.get("teurStatus")
    status_date = parse_date(candidate.get("taarih_status") or detail.get("fullTaarihStatus"))
    terminal_dates = {
        event_date for row in process if isinstance(row, dict)
        if (event_date := parse_date(row.get("execDateStr"))) is not None
        and (normalized_key(row.get("stepCodeText")) in TERMINAL_PERMIT_EVENTS
             or "הוצאת היתר דיגיטלי חתום" in normalized_key(row.get("stepCodeText")))
    }
    source_issued = bool(terminal_dates or (status_date and _issued_status(status)))
    if bool(record.is_permit_issued) != source_issued:
        issues.append("permit_issuance_mismatch")
    if record.is_permit_issued and (not record.permit_issue_date or not (
        record.permit_issue_date in terminal_dates
        or (_issued_status(status) and record.permit_issue_date == status_date)
    )):
        issues.append("permit_evidence_missing")
    raw_permit_number = _permit_number(detail.get("misparHeter") or detail.get("heter_num"))
    if record.permit_number and _permit_number(record.permit_number) != raw_permit_number:
        issues.append("permit_number_mismatch")
    return issues


def _tel_aviv_issues(record: ApplicationRecord, city_name: str) -> list[str]:
    raw = record.raw_data
    issues = []
    if clean_text(raw.get("request_num")) != clean_text(record.application_number):
        issues.append("source_number_mismatch")
    if parse_date(raw.get("open_request")) != record.submission_date:
        issues.append("source_date_mismatch")
    if raw.get("addresses") and record.address and _address(raw["addresses"], city_name) != _address(record.address, city_name):
        issues.append("source_address_mismatch")
    raw_permit = _permit_number(raw.get("permission_num"))
    raw_date = parse_date(raw.get("permission_date"))
    explicit_issued = bool(raw_permit and raw_date and raw_date.year > 2000)
    if bool(record.is_permit_issued) != explicit_issued:
        issues.append("permit_issuance_mismatch")
    if record.permit_number and _permit_number(record.permit_number) != raw_permit:
        issues.append("permit_number_mismatch")
    if record.permit_issue_date and record.permit_issue_date != raw_date:
        issues.append("permit_date_mismatch")
    return issues


def _partial(record: ApplicationRecord, summary: dict | None, issues: list[str], adapter) -> ApplicationRecord:
    source_url = record.source_url
    if summary and record.adapter_name == "complot" and hasattr(adapter, "_summary_source_url"):
        source_url = adapter._summary_source_url(clean_text(summary.get("request_number")))
    safe = replace(
        record,
        address=clean_text(summary.get("address")) or None if summary else record.address,
        submission_date=parse_date(summary.get("submission_date")) if summary else record.submission_date,
        building_file_number=clean_text(summary.get("building_file")) or None if summary else record.building_file_number,
        application_type=None,
        work_description=None,
        approval_date=None,
        is_approved=False,
        approval_confidence=None,
        permit_number=None,
        permit_issue_date=None,
        permit_status_original=None,
        is_permit_issued=False,
        permit_confidence=None,
        details_available=False,
        source_url=source_url,
    )
    safe.raw_data = {**record.raw_data, "validator": {"version": VERSION, "status": "requires_review", "issues": issues}}
    return safe


def validate_records(
    records: list[ApplicationRecord], unit: SearchUnit, adapter, date_from: date, date_to: date
) -> ValidationResult:
    """Cross-check source payloads and return only safe records for persistence."""
    safe_records: list[ApplicationRecord] = []
    issues: list[ValidationIssue] = []
    city_id = getattr(adapter, "city_id", None)
    city_name = getattr(adapter, "city_name", "")
    for record in records:
        record_issues = []
        summary = None
        if city_id and record.city_id != city_id:
            record_issues.append("city_mismatch")
        if getattr(adapter, "name", record.adapter_name) != record.adapter_name:
            record_issues.append("adapter_mismatch")
        if not clean_text(record.application_number):
            record_issues.append("application_number_missing")
        if not _valid_host(record, adapter):
            record_issues.append("source_url_mismatch")
        elif not _link_identifies_record(record):
            record_issues.append("source_link_number_mismatch")
        if not record.details_available:
            record_issues.append("partial_record")
        if record.adapter_name == "complot":
            family_issues, summary = _complot_issues(record, unit, city_name)
            record_issues.extend(family_issues)
        elif record.adapter_name == "jerusalem":
            record_issues.extend(_jerusalem_issues(record))
        elif record.adapter_name == "tel_aviv":
            record_issues.extend(_tel_aviv_issues(record, city_name))
        else:
            record_issues.append("adapter_unknown")
        safe = _partial(record, summary, record_issues, adapter) if record_issues else record
        if safe.submission_date is None or not in_range(safe.submission_date, date_from, date_to):
            record_issues.append("submission_out_of_range")
        if record_issues:
            issues.extend(ValidationIssue(code, record.application_number) for code in dict.fromkeys(record_issues))
            unsafe_identity = {"city_mismatch", "adapter_mismatch", "application_number_missing",
                               "candidate_number_mismatch", "summary_number_mismatch",
                               "source_number_mismatch", "source_date_mismatch",
                               "submission_event_missing", "submission_out_of_range"}
            link_issue = {"source_url_mismatch", "source_link_number_mismatch"}.intersection(record_issues)
            link_repaired = bool(summary and record.adapter_name == "complot"
                                 and _valid_host(safe, adapter) and _link_identifies_record(safe))
            if (not unsafe_identity.intersection(record_issues)
                    and (not link_issue or link_repaired)
                    and safe.application_number and in_range(safe.submission_date, date_from, date_to)):
                safe.raw_data["validator"] = {"version": VERSION, "status": "requires_review", "issues": list(dict.fromkeys(record_issues))}
                safe_records.append(safe)
        else:
            level = "single_source_payload" if record.adapter_name == "tel_aviv" else "cross_source_payloads"
            checked_fields = ["application_number", "submission_date"]
            address_evidence = (_complot_address_evidence(record, unit, city_name)
                                if record.adapter_name == "complot" else None)
            if address_evidence:
                checked_fields.extend(["base_address", "building_file_number", "block_number", "parcel_number"])
            elif record.address:
                checked_fields.append("address")
            if record.is_permit_issued:
                checked_fields.append("permit_issued")
            record.raw_data = {**record.raw_data, "validator": {
                "version": VERSION, "status": "passed_consistency_checks", "level": level,
                "checked_fields": checked_fields,
                **({"address_evidence": address_evidence} if address_evidence else {}),
            }}
            safe_records.append(record)
    return ValidationResult(safe_records, issues)
