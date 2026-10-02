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
    from heterscan.source_links import tel_aviv_source_url
    partial = ApplicationRecord(city_id="5000", application_number="20260001", address="public summary",
                                source_url=tel_aviv_source_url("20260001"), source_reference="20260001",
                                adapter_name="tel_aviv", adapter_version="test",
                                raw_data={"request_num": "20260001", "open_request": "2026-01-04",
                                          "permission_num": 0, "permission_date": None},
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
    repository.progress_summary.return_value = {"units_requires_review": int(summary_only), "units_failed": 0, "applications_found": int(summary_only)}
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
    assert repository.finalize_run.call_args.args[1]["status"] == "requires_review"
    assert repository.finalize_run.call_args.args[1]["coverage_verification"] == ("partial" if summary_only else "zero_not_verified")
    assert len(repository.save_applications.call_args.args[1]) == int(summary_only)
    assert repository.finish_units.call_args.args[0][0]["result_count"] == int(summary_only)
    repository.update_owned_run.assert_called_once()
    repository.update_run.assert_not_called()


@pytest.mark.parametrize("cooldown", [0.0, 0.01])
def test_repeated_429_marks_unchecked_units_for_review(monkeypatch, cooldown):
    from heterscan.domain import AdapterRateLimited, SearchUnit

    repository = Mock()
    repository.get_run.return_value = {
        "status": "running", "city_id": "8400", "date_from": "2026-01-01", "date_to": "2026-01-31",
        "configuration_snapshot": {"city": {"id": "8400", "name_he": "רחובות",
                                            "adapter_name": "complot", "adapter_config": {"site_id": "22"}}},
    }
    repository._rest.return_value.json.return_value = True
    unit = SearchUnit("unit", "run", 1, "request:20260035", {"mode": "request"})
    repository.claim_units.side_effect = [[unit], [unit], [unit]]
    repository.cancellation_requested.return_value = False
    repository.update_owned_run.return_value = True
    repository.progress_counts.return_value = {"units_completed": 0, "applications_found": 0, "permits_found": 0}

    class Adapter:
        name = "complot"

        def __init__(self, *_args, coordinator=None):
            assert coordinator is repository

        def parallelism(self):
            return 1

        def performance_snapshot(self):
            return {"penalties": 0, "parallelism": 1}

        def observe_wave(self, **_kwargs):
            pass

        def collect(self, *_args):
            raise AdapterRateLimited("429", retry_after_seconds=cooldown,
                                     origin="handasi.complot.co.il", endpoint="detail",
                                     retry_after_kind="seconds")

        def close(self):
            pass

    finalize = Mock(return_value=0)
    monkeypatch.setattr(runner, "SupabaseRepository", lambda: repository)
    monkeypatch.setattr(runner, "ADAPTERS", {"complot": Adapter})
    monkeypatch.setattr(runner, "_wait_for_source_cooldown", lambda *_args: True)
    monkeypatch.setattr(runner, "_finalize_report", finalize)

    assert runner.run("run") == 0
    assert repository.release_units.call_count == 3
    repository.mark_unfinished_rate_limited.assert_called_once_with("run")
    assert finalize.call_args.args[-1] == "requires_review"


def test_worker_can_resume_pending_units_after_timebox_checkpoint(monkeypatch):
    from heterscan.domain import SearchUnit
    repository = Mock()
    repository.get_run.return_value = {
        "status": "safely_stopped", "city_id": "8400", "date_from": "2026-01-01", "date_to": "2026-01-31",
        "configuration_snapshot": {"city": {"id": "8400", "name_he": "רחובות",
                                            "adapter_name": "complot", "adapter_config": {"site_id": "22"}}},
    }
    claimed = Mock()
    claimed.json.return_value = True
    remaining = Mock()
    remaining.json.return_value = [{"id": "pending-unit"}]
    repository._rest.side_effect = [claimed, remaining]
    repository.cancellation_requested.return_value = False
    repository.update_owned_run.return_value = True

    class Adapter:
        name = "complot"
        def __init__(self, *_args, coordinator=None):
            assert coordinator is repository
        def parallelism(self):
            return 1
        def performance_snapshot(self):
            return {"penalties": 0, "parallelism": 1}
        def observe_wave(self, **_kwargs):
            pass
        def collect(self, *_args):
            return []
        def close(self):
            pass

    monkeypatch.setenv("MAX_WORKER_SECONDS", "0")
    monkeypatch.setattr(runner, "SupabaseRepository", lambda: repository)
    monkeypatch.setattr(runner, "ADAPTERS", {"complot": Adapter})

    assert runner.run("run") == 75
    assert repository.update_owned_run.call_args.args[2]["status"] == "safely_stopped"
    repository.mark_unfinished_rate_limited.assert_not_called()

    # The next worker claims the same pending unit and finishes it.
    monkeypatch.setenv("MAX_WORKER_SECONDS", "10")
    repository._rest.side_effect = [claimed, Mock(json=Mock(return_value=[]))]
    repository.claim_units.side_effect = [[SearchUnit("pending-unit", "run", 1, "request:20260035", {})], []]
    repository.finish_units.return_value = 1
    repository.progress_counts.return_value = {"units_completed": 1, "applications_found": 0, "permits_found": 0}
    repository.progress_summary.return_value = {"units_requires_review": 0, "units_failed": 0,
                                                "applications_found": 0}
    finalize = Mock(return_value=0)
    monkeypatch.setattr(runner, "_finalize_report", finalize)
    assert runner.run("run") == 0
    assert repository.finish_units.call_args.args[0][0]["id"] == "pending-unit"
    assert repository.finish_units.call_args.args[0][0]["status"] == "completed"
