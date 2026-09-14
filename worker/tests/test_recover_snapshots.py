from heterscan.recover_published_snapshots import prepare_recovery
from heterscan.reporting import build_report


def test_published_snapshot_restores_old_status_instead_of_current_mutable_record():
    run = {"city_name": "ירושלים", "date_from": "2026-01-01", "date_to": "2026-01-31", "status": "completed"}
    published = {"application_number": "123", "address": "original", "submission_date": "2026-01-04", "is_approved": True, "is_permit_issued": False}
    payload, _ = build_report(run, [published], [])
    links = [{"application_id": "id", "result_snapshot_source": "legacy_current", "result_snapshot": {
        "id": "id", "city_id": "3000", "application_number": "123", "address": "changed", "is_permit_issued": True,
    }}]
    rows, count, issued = prepare_recovery(payload, links, "run/report.xlsx")
    assert (count, issued) == (1, 0)
    assert rows[0]["snapshot"]["address"] == "original"
    assert rows[0]["snapshot"]["is_permit_issued"] is False
    assert rows[0]["snapshot"]["is_approved"] is True
    assert rows[0]["snapshot"]["permit_number"] is None


def test_new_captured_observations_are_never_overwritten_by_recovery():
    run = {"city_name": "ירושלים", "date_from": "2026-01-01", "date_to": "2026-01-31", "status": "completed"}
    payload, _ = build_report(run, [{"application_number": "123"}], [])
    rows, _, _ = prepare_recovery(payload, [{"result_snapshot_source": "captured"}], "run/report.xlsx")
    assert rows == []
