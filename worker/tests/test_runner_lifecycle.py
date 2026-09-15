from datetime import date
from unittest.mock import Mock
import pytest

from heterscan import runner


def test_cancelled_before_start_gets_a_report_without_claim_or_adapter(monkeypatch):
    repository = Mock()
    repository.get_run.return_value = {"status": "cancelled", "city_id": "5000", "date_from": "2026-01-01", "date_to": "2026-01-31"}
    finalize = Mock(return_value=0)
    monkeypatch.setattr(runner, "SupabaseRepository", lambda: repository)
    monkeypatch.setattr(runner, "_finalize_report", finalize)
    assert runner.run("run") == 0
    assert finalize.call_args.args[-1] == "cancelled"
    repository._rest.assert_not_called()
    repository.update_owned_run.assert_not_called()


def test_duplicate_worker_does_not_fail_or_unlock_the_owners_run(monkeypatch):
    repository = Mock()
    repository.get_run.return_value = {"status": "running"}
    repository._rest.return_value.json.return_value = False
    monkeypatch.setattr(runner, "SupabaseRepository", lambda: repository)
    assert runner.run("run") == 0
    repository.update_owned_run.assert_not_called()
    repository.update_run.assert_not_called()


def test_terminal_run_is_left_unchanged(monkeypatch):
    repository = Mock()
    repository.get_run.return_value = {"status": "completed"}
    monkeypatch.setattr(runner, "SupabaseRepository", lambda: repository)
    assert runner.run("run") == 0
    repository._rest.assert_not_called()


def test_cancellation_during_report_upload_wins_and_matches_workbook(monkeypatch):
    repository = Mock()
    repository.get_run.side_effect = [{"status": "running"}, {"status": "cancelled"}]
    repository.run_results.return_value = []
    repository.run_units.return_value = []
    repository.progress_counts.return_value = {}
    repository.finalize_run.side_effect = [False, True]
    monkeypatch.setattr(runner, "build_report", lambda run, *_: (run["status"].encode(), "hash"))
    assert runner._finalize_report(repository, "run", "5000", date(2026, 1, 1), date(2026, 1, 31), "completed") == 0
    assert repository.upload_report.call_args.args[1] == b"cancelled"
    assert repository.finalize_run.call_args.args[1]["status"] == "cancelled"


@pytest.mark.parametrize("summary_only", [False, True])
def test_complete_worker_path_publishes_report_and_updates_only_owned_progress(monkeypatch, summary_only):
    from heterscan.domain import AdapterReviewRequired, ApplicationRecord, SearchUnit
    partial = ApplicationRecord(city_id="5000", application_number="20260001", address="public summary",
                                source_url="https://example.test", source_reference="20260001",
                                adapter_name="tel_aviv", adapter_version="test", raw_data={},
                                submission_date=date(2026, 1, 4), details_available=False)

    repository = Mock()
    repository.get_run.return_value = {
        "status": "running", "city_id": "5000", "city_name": "תל אביב-יפו",
        "date_from": "2026-01-01", "date_to": "2026-01-31",
        "configuration_snapshot": {"city": {"id": "5000", "name_he": "תל אביב-יפו", "adapter_name": "tel_aviv"}},
    }
    claim, remaining = Mock(), Mock()
    claim.json.return_value, remaining.json.return_value = True, []
    repository._rest.side_effect = [claim, remaining]
    repository.claim_units.side_effect = [[SearchUnit("unit", "run", 1, "city-wide", {})], []]
    repository.cancellation_requested.return_value = False
    repository.finish_units.return_value = 1
    repository.update_owned_run.return_value = True
    repository.progress_counts.return_value = {"units_completed": 1, "applications_found": int(summary_only), "permits_found": 0}
    repository.progress_summary.return_value = {"units_requires_review": int(summary_only), "units_failed": 0}
    repository.run_results.return_value = [{"application_number": "20260001", "details_available": False}] if summary_only else []
    repository.run_units.return_value = [{"status": "requires_review" if summary_only else "completed"}]
    repository.finalize_run.return_value = True

    class Adapter:
        name = "tel_aviv"
        def __init__(self, *_args): pass
        def collect(self, *_args):
            if summary_only:
                raise AdapterReviewRequired("restricted", partial_records=[partial])
            return []
        def close(self): pass

    monkeypatch.setattr(runner, "SupabaseRepository", lambda: repository)
    monkeypatch.setattr(runner, "ADAPTERS", {"tel_aviv": Adapter})
    assert runner.run("run") == 0
    assert repository.finalize_run.call_args.args[1]["status"] == ("requires_review" if summary_only else "completed")
    assert len(repository.save_applications.call_args.args[1]) == int(summary_only)
    assert repository.finish_units.call_args.args[0][0]["result_count"] == int(summary_only)
    repository.update_owned_run.assert_called_once()
    repository.update_run.assert_not_called()
