from io import BytesIO

from openpyxl import load_workbook

from heterscan.reporting import build_report, report_filename, report_storage_filename


def test_hebrew_report_name_is_separate_from_the_storage_key():
    run = {"id": "run", "city_id": "8300", "city_name": "ראשון לציון",
           "date_from": "2026-01-01", "date_to": "2026-01-31"}
    assert "ראשון-לציון" in report_filename(run)
    assert report_storage_filename(run) == "HETERSCAN_8300_2026-01-01_2026-01-31_run.xlsx"


def test_report_includes_pending_applications_with_source_link() -> None:
    results = [
        {
            "application_number": "20250001",
            "permit_number": "2025-100",
            "permit_issue_date": "2025-12-15",
            "permit_status_original": "היתר הופק",
            "is_approved": True,
            "is_permit_issued": True,
            "source_url": "https://example.test/issued",
        },
        {
            "application_number": "20250002",
            "is_approved": False,
            "is_permit_issued": False,
            "source_url": "https://example.test/pending",
        },
    ]
    run = {
        "city_name": "פתח תקווה",
        "date_from": "2025-12-01",
        "date_to": "2025-12-31",
        "status": "completed",
    }

    payload, _ = build_report(run, results, [])
    workbook = load_workbook(BytesIO(payload))
    sheet = workbook["בקשות והיתרים"]
    headers = {cell.value: cell.column for cell in sheet[1]}

    assert sheet.max_row == 3
    assert sheet.cell(3, headers["סטטוס"]).value == "סטטוס לא אומת"
    assert sheet.cell(3, headers["מספר היתר"]).value == "לא ידוע"
    source_cell = sheet.cell(3, headers["קישור מקור"])
    assert source_cell.value == "https://example.test/pending"
    assert source_cell.hyperlink.target == "https://example.test/pending"
    assert workbook["היתרים שנמצאו"].max_row == 2


def test_approved_without_permit_stays_separate_from_issued() -> None:
    run = {"city_name": "ירושלים", "date_from": "2026-01-01", "date_to": "2026-01-31", "status": "completed"}
    results = [{"application_number": "123", "is_approved": True, "is_permit_issued": False}]
    payload, _ = build_report(run, results, [])
    workbook = load_workbook(BytesIO(payload))
    assert workbook["בקשות שאושרו"].max_row == 2
    assert workbook["היתרים שנמצאו"].max_row == 1
    assert workbook["בקשות והיתרים"]["J2"].value == "לא ידוע"
    assert workbook["בקשות והיתרים"]["L2"].value == "אושר — מצב היתר לא אומת"


def test_zero_report_explicitly_says_zero_is_not_verified() -> None:
    run = {"city_name": "חולון", "date_from": "2026-01-01", "date_to": "2026-01-31", "status": "requires_review"}
    payload, _ = build_report(run, [], [])
    sheet = load_workbook(BytesIO(payload))["סיכום"]
    assert "אפס לא אומת" in [cell.value for cell in sheet[2]]


def test_source_text_cannot_become_an_excel_formula() -> None:
    run = {"city_name": "ירושלים", "date_from": "2026-01-01", "date_to": "2026-01-31", "status": "completed"}
    expression = '=HYPERLINK("https://example.test/", "external")'
    payload, _ = build_report(run, [{"address": expression, "source_url": expression}], [])
    workbook = load_workbook(BytesIO(payload))
    for cell in (workbook["בקשות והיתרים"]["A2"], workbook["בקשות והיתרים"]["O2"]):
        assert cell.value == expression
        assert cell.data_type == "s"
        assert cell.hyperlink is None


def test_malformed_source_url_is_preserved_without_breaking_report() -> None:
    run = {"city_name": "ירושלים", "date_from": "2026-01-01", "date_to": "2026-01-31", "status": "requires_review"}
    payload, _ = build_report(run, [{"source_url": "https://[malformed"}], [])
    cell = load_workbook(BytesIO(payload))["בקשות והיתרים"]["O2"]
    assert cell.value == "https://[malformed"
    assert cell.hyperlink is None
