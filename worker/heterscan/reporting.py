from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .source_links import stable_source_url

HEADER_FILL = PatternFill("solid", fgColor="123B70")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def report_filename(run: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    """Build a readable report name with its city, requested period and issue date."""
    raw_city_name = str(run.get("city_name") or "").strip()
    if not raw_city_name:
        raise ValueError("Cannot create a report filename without a city name")
    city_name = re.sub(r"[^A-Za-z0-9א-ת_-]+", "-", raw_city_name).strip("-_")
    if not city_name:
        raise ValueError("Cannot create a report filename without a usable city name")
    issued_at = generated_at or datetime.now(timezone.utc)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    issued_on = issued_at.astimezone(timezone.utc).date().isoformat()
    return (
        f"HETERSCAN_{city_name}_{run['date_from']}_{run['date_to']}"
        f"_הופק-{issued_on}_{run['id']}.xlsx"
    )


def _display_status(row: dict[str, Any]) -> str:
    if row.get("details_available") is False:
        if (row.get("raw_data") or {}).get("source_diagnostics", {}).get("collection_mode") == "public_summary":
            return "סיכום בקשה בלבד — מצב היתר לא ידוע"
        return "פרטים חלקיים — נדרשת בדיקה"
    if row.get("is_permit_issued"):
        return row.get("permit_status_original") or "היתר הופק"
    if row.get("is_approved"):
        return row.get("permit_status_original") or "אושר — מצב היתר לא אומת"
    return row.get("permit_status_original") or "סטטוס לא אומת"


def _display(value: Any) -> Any:
    if value is None or value == "":
        return "לא ידוע"
    if isinstance(value, (dict, list)):
        return str(value)
    return value


def _is_web_link(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def _sheet(
    workbook: Workbook, title: str, rows: list[dict[str, Any]], headers: list[tuple[str, str]]
) -> None:
    sheet = workbook.create_sheet(title)
    sheet.sheet_view.rightToLeft = True
    sheet.append([label for _, label in headers])
    for row in rows:
        sheet.append([_display(row.get(key)) for key, _ in headers])
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            # Municipal content is data, never an executable spreadsheet formula.
            if cell.data_type == "f":
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True, readingOrder=2)
        source_cell = row[-1] if row else None
        if source_cell and _is_web_link(source_cell.value):
            source_cell.hyperlink = source_cell.value
            source_cell.style = "Hyperlink"
    for index, (_, label) in enumerate(headers, 1):
        sheet.column_dimensions[get_column_letter(index)].width = min(55, max(14, len(label) + 5))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions


def build_report(
    run: dict[str, Any], results: list[dict[str, Any]], units: list[dict[str, Any]]
) -> tuple[bytes, str]:
    workbook = Workbook()
    workbook.remove(workbook.active)
    coverage_status = run.get("coverage_verification") or (
        "zero_not_verified" if not results else "not_verified"
    )
    collection_mode = (run.get("configuration_snapshot") or {}).get("collectionMode", "full_details")
    unknown_permits = [row for row in results if not row.get("is_permit_issued")
                       and row.get("permit_verification") != "verified_not_issued"]
    summary = [
        {
            "city_name": run["city_name"],
            "date_from": run["date_from"],
            "date_to": run["date_to"],
            "status": run["status"],
            "applications_found": len(results),
            "permits_found": sum(bool(row.get("is_permit_issued")) for row in results),
            "coverage_verification": {
                "verified_zero": "אפס אומת",
                "verified_nonzero": "כיסוי אומת",
                "zero_not_verified": "אפס לא אומת",
                "partial": "כיסוי חלקי — נדרשת בדיקה",
            }.get(coverage_status, "כיסוי טרם אומת בעת הפקת הדוח"),
            "permit_count_meaning": "נספרו רק היתרים שאומתו; היתר שלא אומת אינו היתר שלא הופק",
            "units_total": len(units),
            "units_completed": sum(row["status"] == "completed" for row in units),
            "collection_mode": "סיכומי בקשות בלבד" if collection_mode == "public_summary" else "בקשות ופרטים זמינים",
            "unknown_permits": len(unknown_permits),
        }
    ]
    _sheet(
        workbook,
        "סיכום",
        summary,
        [
            ("city_name", "עיר"),
            ("date_from", "מתאריך"),
            ("date_to", "עד תאריך"),
            ("status", "סטטוס"),
            ("applications_found", "בקשות שנמצאו"),
            ("permits_found", "היתרים שנמצאו"),
            ("coverage_verification", "אימות כיסוי"),
            ("permit_count_meaning", "משמעות ספירת היתרים"),
            ("units_total", "יחידות חיפוש"),
            ("units_completed", "יחידות שהושלמו"),
            ("collection_mode", "היקף הסריקה"),
            ("unknown_permits", "בקשות שמצב ההיתר שלהן לא ידוע"),
        ],
    )
    report_results = [
        {
            **row,
            "source_url": stable_source_url(row.get("source_url"), row.get("application_number")),
            "display_status": _display_status(row),
            "permit_number": row.get("permit_number") or "לא ידוע",
        }
        for row in results
    ]
    common_headers = [
        ("address", "כתובת"),
        ("application_number", "מספר בקשה"),
        ("building_file_number", "מספר תיק בניין"),
        ("block_number", "גוש"),
        ("parcel_number", "חלקה"),
        ("application_type", "סוג בקשה"),
        ("work_description", "תיאור עבודה"),
        ("submission_date", "תאריך הגשה"),
        ("approval_date", "תאריך אישור"),
        ("permit_number", "מספר היתר"),
        ("permit_issue_date", "תאריך הפקת היתר"),
        ("display_status", "סטטוס"),
        ("permit_status_original", "סטטוס מקורי במקור"),
        ("permit_confidence", "רמת אמינות"),
        ("source_url", "קישור מקור"),
    ]
    permits = [row for row in report_results if row.get("is_permit_issued")]
    approvals = [row for row in report_results if row.get("is_approved")]
    _sheet(workbook, "בקשות והיתרים", report_results, common_headers)
    _sheet(workbook, "היתרים שנמצאו", permits, common_headers)
    _sheet(workbook, "בקשות שאושרו", approvals, common_headers)
    _sheet(workbook, "כל התוצאות", report_results, common_headers)
    if collection_mode == "public_summary":
        field_labels = {"application_number": "מספר בקשה", "address": "כתובת", "submission_date": "תאריך הגשה",
                        "building_file_number": "מספר תיק בניין", "block_number": "גוש", "parcel_number": "חלקה"}
        provenance_rows = [
            {"application_number": row.get("application_number"), "field": field_labels.get(field, field),
             "value": row.get(field),
             "origin": "סיכום החיפוש הציבורי", "detail_state": "לא התבקשו פרטים",
             "source_url": evidence.get("source_url")}
            for row in results
            for field, evidence in (row.get("raw_data") or {}).get("field_provenance", {}).items()
        ]
        _sheet(workbook, "מקור שדות הסיכום", provenance_rows, [
            ("application_number", "מספר בקשה"), ("field", "שדה"), ("value", "ערך"), ("origin", "מקור המידע"),
            ("detail_state", "מצב פרטים"), ("source_url", "קישור מקור"),
        ])
    _sheet(
        workbook,
        "יחידות חיפוש",
        units,
        [
            ("sequence", "מספר"),
            ("unit_key", "יחידה"),
            ("status", "סטטוס"),
            ("attempts", "ניסיונות"),
            ("result_count", "תוצאות"),
            ("completed_at", "זמן סיום"),
            ("error_message", "שגיאה"),
        ],
    )
    errors = [row for row in units if row["status"] in ("failed", "requires_review")]
    _sheet(
        workbook,
        "שגיאות",
        errors,
        [
            ("sequence", "מספר"),
            ("unit_key", "יחידה"),
            ("status", "סטטוס"),
            ("attempts", "ניסיונות"),
            ("error_message", "פירוט"),
        ],
    )
    stream = BytesIO()
    workbook.save(stream)
    payload = stream.getvalue()
    return payload, hashlib.sha256(payload).hexdigest()
