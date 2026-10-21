from datetime import date
from io import BytesIO
from unittest.mock import Mock

import pytest
from openpyxl import load_workbook

from heterscan import runner
from heterscan.check_run import check_run
from heterscan.outcome import collection_outcome


def test_partial_results_are_not_described_as_complete_or_as_no_permits():
    results = [{"details_available": False, "raw_data": {
        "source_diagnostics": {"classification": "detail_unavailable"},
    }}, {"details_available": True, "is_permit_issued": True}]
    outcome = collection_outcome({"status": "requires_review"}, results, [{"status": "requires_review"}])
    assert outcome["partial_details"] == 1
    assert outcome["full_details"] == 1
    assert outcome["source_issues"] == {"detail_unavailable": 1}
    assert "מצב ההיתר בבקשות ללא פרטים אינו ידוע" in outcome["message"]
    assert "מהאפס" not in outcome["message"]


def test_summary_mode_is_not_misdiagnosed_as_a_failed_detail_request():
    outcome = collection_outcome({"status": "requires_review", "configuration_snapshot": {
        "collectionMode": "public_summary",
    }}, [{"details_available": False}], [])
    assert "נבחר איסוף סיכומים בלבד" in outcome["message"]
    assert "איסוף פרטי הבקשות לא הושלם" not in outcome["message"]


def test_full_details_with_discovery_gaps_still_reports_unverified_coverage():
    outcome = collection_outcome({"status": "requires_review"}, [{"details_available": True}], [
        {"status": "requires_review"}, {"status": "failed"},
    ])
    assert "כיסוי החיפוש לא אומת" in outcome["message"]
    assert outcome["failed_units"] == 1 and outcome["review_units"] == 1


def test_finalizer_publishes_same_collection_warning_to_database_and_workbook(monkeypatch):
    repository = Mock()
    repository.get_run.return_value = {
        "id": "r", "status": "running", "city_name": "אילת",
        "date_from": "2026-01-01", "date_to": "2026-01-31",
    }
    repository.run_results.return_value = [{"application_number": "20260001", "details_available": False}]
    repository.run_units.return_value = [{"status": "requires_review"}]
    repository.progress_counts.return_value = {"applications_found": 1, "permits_found": 0}
    repository.finalize_run.return_value = True
    assert runner._finalize_report(repository, "r", "2600", date(2026, 1, 1), date(2026, 1, 31), "requires_review") == 0
    saved = repository.finalize_run.call_args.args[1]
    assert saved["status"] == "requires_review"
    workbook = load_workbook(BytesIO(repository.upload_report.call_args.args[1]))
    summary = dict(zip(*(list(row) for row in workbook["סיכום"].values)))
    assert summary["מגבלות האיסוף"] == saved["error_message"]
    assert summary["בקשות ללא פרטים מלאים"] == 1
    assert summary["בקשות עם פרטים מלאים"] == 0
    assert summary["היתרים שנמצאו"] == 0


@pytest.mark.parametrize("status,report,count,exit_code", [
    ("completed", "r/report.xlsx", 1, 0),
    ("completed", None, 1, 2),
    ("completed", "r/report.xlsx", 0, 2),
    ("requires_review", "r/report.xlsx", 183, 2),
    ("completed_with_errors", "r/report.xlsx", 5, 2),
    ("cancelled", "r/report.xlsx", 5, 2),
    ("failed", None, 0, 2),
])
def test_workflow_gate_separates_published_partial_report_from_success(tmp_path, monkeypatch, status, report, count, exit_code):
    path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    assert check_run({"status": status, "report_path": report, "applications_found": count}) == exit_code
    assert status in path.read_text(encoding="utf-8")
