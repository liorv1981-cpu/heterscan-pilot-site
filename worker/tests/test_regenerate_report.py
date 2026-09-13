from unittest.mock import Mock

import pytest

import heterscan.regenerate_report as regeneration


def test_regeneration_preserves_the_previous_storage_object(monkeypatch):
    repository = Mock()
    repository.get_run.return_value = {
        "status": "completed", "city_id": "3000", "city_name": "ירושלים",
        "date_from": "2026-01-01", "date_to": "2026-01-31", "report_path": "run/original.xlsx",
    }
    repository.run_results.return_value = []
    repository.run_units.return_value = []
    monkeypatch.setattr(regeneration, "SupabaseRepository", lambda: repository)
    path = regeneration.regenerate_report("run")
    assert path != "run/original.xlsx"
    assert path.startswith("run/") and path.endswith(".xlsx")
    assert repository.upload_report.call_args.args[0] == path
    assert repository.log.call_args.args[3]["previous_report_path"] == "run/original.xlsx"
    repository.close.assert_called_once()


@pytest.mark.parametrize("status", ["created", "dispatching", "running", "safely_stopped"])
def test_active_scan_is_never_regenerated(monkeypatch, status):
    repository = Mock()
    repository.get_run.return_value = {"status": status}
    monkeypatch.setattr(regeneration, "SupabaseRepository", lambda: repository)
    with pytest.raises(ValueError, match="active scan"):
        regeneration.regenerate_report("run")
    repository.upload_report.assert_not_called()
    repository.close.assert_called_once()
