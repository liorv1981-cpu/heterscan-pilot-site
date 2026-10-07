import json
from datetime import date
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest

from heterscan.adapters.complot import ComplotAdapter
from heterscan.domain import AdapterReviewRequired, DiscoveryResult, SearchUnit
from heterscan.normalize import parse_date
from heterscan.runner import _expand_discovery
from heterscan.validator import validate_records

CASES = json.loads((Path(__file__).parent / "fixtures/complot_recovery.json").read_text(encoding="utf-8"))["cases"]
JANUARY = (date(2026, 1, 1), date(2026, 1, 31))


def detail_markup(case):
    fields = "".join(f"<tr><td>{escape(k)}</td><td>{escape(v)}</td></tr>" for k, v in case["fields"].items())
    events = "".join("<tr>" + "".join(f"<td>{escape(v)}</td>" for v in row) + "</tr>" for row in case["events"])
    return (f'<div id="result-title-div-id">מספר הבקשה: {case["number"]} '
            f'כתובת: {escape(case["address"])} תאריך הגשה: {case["submission_date"]}</div>'
            f'<div id="info-main"><table>{fields}</table></div>'
            f'<table id="table-events">{events}</table>')


def summary_markup(case):
    return (f'<table><tbody><tr><td></td><td><a href="javascript:getRequest({case["number"]})">'
            f'{case["number"]}</a></td><td>{case["fields"].get("מספר תיק בניין", "")}</td>'
            f'<td>{case["submission_date"]}</td><td></td><td>{escape(case["address"])}</td>'
            '<td></td><td></td></tr></tbody></table>')


@pytest.mark.parametrize("case", CASES, ids=lambda c: f'{c["city_id"]}-{c["number"]}')
def test_preserved_missed_permits_and_negative_controls_through_collector_and_validator(case, monkeypatch):
    adapter = ComplotAdapter(case["city_id"], case["city_name"], {"site_id": case["site_id"]})
    unit = SearchUnit("u", "offline-replay", 1, f'request:{case["number"]}',
                      {"mode": "request", "requestNumber": case["number"]})
    calls = []

    def request(method, url):
        calls.append(url)
        return SimpleNamespace(text=summary_markup(case) if "GetBakashotByNumber" in url else detail_markup(case))

    monkeypatch.setattr(adapter.client, "request", request)
    try:
        records = adapter.collect(unit, *JANUARY)
        checked = validate_records(records, unit, adapter, *JANUARY)
        assert checked.issues == []
        [record] = checked.records
        assert record.permit_number == case["expected_permit"]
        assert record.permit_issue_date == parse_date(case["expected_issue_date"])
        assert record.is_permit_issued == bool(case["expected_permit"])
        assert record.raw_data["verification_scope"]["permit"] == (
            "verified_issued" if case["expected_permit"] else "unknown")
        assert len(calls) == 2
        if case["number"] == "20260011":
            assert any("הפקת היתר" in row.get("תיאור אירוע", "") for row in record.raw_data["events"])
            assert not record.is_permit_issued
    finally:
        adapter.close()


@pytest.mark.parametrize("fields", [
    {"מספר היתר": "", "תאריך הפקת היתר": "29/01/2026", "סטטוס": "היתר הופק"},
    {"מספר היתר": "0", "תאריך הפקת היתר": "29/01/2026", "סטטוס": "היתר בתוקף"},
    {"מספר היתר קודם": "123", "תאריך היתר קודם": "29/01/2026", "סטטוס": "אושר בתנאים"},
    {"מספר היתר": "", "תאריך הפקת היתר": "", "סטטוס": "תשלום פיקדון"},
])
def test_complot_status_and_previous_permit_fields_cannot_prove_issuance(fields):
    case = {**CASES[0], "fields": fields, "events": []}
    adapter = ComplotAdapter("6400", "הרצליה", {"site_id": "121"})
    try:
        record = adapter._record_from_detail(case["number"], detail_markup(case))
        assert not record.is_permit_issued
        assert record.to_database(run_id="r", identity_key="fixture", content_hash="fixture")["permit_verification"] == "unknown"
    finally:
        adapter.close()


def test_capped_long_identifiers_continue_past_configured_last_digit(monkeypatch):
    adapter = ComplotAdapter("1200", "מודיעין", {"site_id": "82", "request_number_length": 8})
    labels = [f"2026183{i:03d}" for i in range(10)]
    monkeypatch.setattr(adapter.client, "request", lambda *a, **kw: SimpleNamespace(json=lambda: {"d": [{"label": n} for n in labels]}))
    try:
        result = adapter.collect(SearchUnit("u", "r", 1, "prefix", {"mode": "discover-prefix", "prefix": "2026183"}), *JANUARY)
        assert isinstance(result, DiscoveryResult)
        assert [u.payload["requestNumber"] for u in result.units if u.payload["mode"] == "request"] == labels
        assert [u.payload["prefix"] for u in result.units if u.payload["mode"] == "discover-prefix"] == [f"2026183{i}" for i in range(10)]
        assert result.diagnostics["observed_labels"] == labels
        repository = SimpleNamespace(enqueue_units=lambda run, units: len(units))
        inserted, (_, _, error) = _expand_discovery(repository, "r", None, result)
        assert inserted == 20 and error.diagnostics["observed_labels"] == labels
    finally:
        adapter.close()


def route_adapter(**overrides):
    # Reserved example host: this verifies routing only, not an actual city endpoint.
    return ComplotAdapter("6400", "הרצליה", {"site_id": "121",
        "public_search_url": "https://municipality.example.invalid/search/",
        "public_detail_url_template": "https://municipality.example.invalid/detail?b={request_number}",
        "public_detail_route_evidence": "fixture-only", **overrides})


def test_documented_public_endpoint_is_used_for_collection_without_shared_detail_fallback(monkeypatch):
    adapter = route_adapter()
    calls = []
    case = CASES[0]
    def request(method, url):
        calls.append(url)
        return SimpleNamespace(text=summary_markup(case) if "GetBakashotByNumber" in url else detail_markup(case))
    monkeypatch.setattr(adapter.client, "request", request)
    try:
        unit = SearchUnit("u", "r", 1, "request", {"mode": "request", "requestNumber": case["number"]})
        [record] = adapter.collect(unit, *JANUARY)
        assert calls[1] == "https://municipality.example.invalid/detail?b=20260010"
        assert record.source_url.endswith("/#request/20260010")
        assert validate_records([record], unit, adapter, *JANUARY).issues == []
        assert record.raw_data["field_provenance"]["permit_number"]["source_url"] == calls[1]
    finally:
        adapter.close()


@pytest.mark.parametrize("overrides", [
    {"public_detail_route_evidence": ""},
    {"public_detail_url_template": "https://municipality.example.invalid/search/#request/{request_number}"},
    {"public_detail_url_template": "https://unrelated.example.invalid/detail?b={request_number}"},
    {"public_detail_url_template": "https://municipality.example.invalid:8080/detail?b={request_number}"},
    {"public_detail_url_template": "https://municipality.example.invalid/detail?b={request_number}&missing={}"},
])
def test_unverified_route_keeps_summary_with_provenance_without_requesting_detail(overrides, monkeypatch):
    adapter = route_adapter(**overrides)
    calls = []
    def request(method, url):
        calls.append(url)
        return SimpleNamespace(text=summary_markup(CASES[0]))
    monkeypatch.setattr(adapter.client, "request", request)
    try:
        with pytest.raises(AdapterReviewRequired) as failure:
            adapter.collect(SearchUnit("u", "r", 1, "request", {"mode": "request", "requestNumber": "20260010"}), *JANUARY)
        [record] = failure.value.partial_records
        assert record.application_number == "20260010" and not record.details_available
        assert failure.value.diagnostics["detail_state"] == "route_unverified"
        assert record.raw_data["field_provenance"]["address"]["source_url"] == calls[0]
        assert len(calls) == 1
    finally:
        adapter.close()


def test_january_issued_permit_on_older_application_is_outside_submission_range(monkeypatch):
    adapter = ComplotAdapter("6400", "הרצליה", {"site_id": "121"})
    calls = []
    case = {**CASES[0], "submission_date": "2025-12-31"}
    def request(method, url):
        calls.append(url)
        return SimpleNamespace(text=summary_markup(case))
    monkeypatch.setattr(adapter.client, "request", request)
    try:
        assert adapter.collect(SearchUnit("u", "r", 1, "request", {"mode": "request", "requestNumber": case["number"]}), *JANUARY) == []
        assert len(calls) == 1
    finally:
        adapter.close()


def test_short_self_label_is_verified_as_candidate_instead_of_silently_lost(monkeypatch):
    adapter = ComplotAdapter("8600", "רמת גן", {"site_id": "3", "request_number_length": 9})
    monkeypatch.setattr(adapter.client, "request", lambda *a, **kw: SimpleNamespace(json=lambda: {"d": [{"label": "20261"}]}))
    try:
        result = adapter.collect(SearchUnit("u", "r", 1, "prefix", {"mode": "discover-prefix", "prefix": "20261"}), *JANUARY)
        assert [u.unit_key for u in result.units] == ["request:20261"]
        assert result.units[0].payload["discoveryEvidence"]["identityVerified"] is False
        assert result.diagnostics["coverage_verified"] is False
    finally:
        adapter.close()


def test_conflicting_duplicate_permit_values_require_review_and_preserve_both():
    adapter = ComplotAdapter("6400", "הרצליה", {"site_id": "121"})
    try:
        markup = detail_markup(CASES[0]).replace("</table></div>",
            '<tr><td>מספר היתר</td><td>9999</td></tr></table></div>', 1)
        with pytest.raises(AdapterReviewRequired) as failure:
            adapter._record_from_detail("20260010", markup)
        assert failure.value.diagnostics["observed_values"] == ["20260010", "9999"]
    finally:
        adapter.close()
