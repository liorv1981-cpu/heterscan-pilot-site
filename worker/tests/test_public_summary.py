from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from heterscan.adapters.complot import ComplotAdapter
from heterscan.domain import AdapterRateLimited, AdapterReviewRequired, SearchUnit
from heterscan.reporting import build_report
from heterscan.runner import _collect_wave

SUMMARY = '<table><tbody><tr><td></td><td><a href="javascript:getRequest(20260001)">20260001</a></td><td>F1</td><td>04/01/2026</td><td></td><td>כתובת פומבית</td><td>1</td><td>2</td></tr></tbody></table>'


def test_out_of_range_public_summary_never_requests_restricted_details(monkeypatch):
    adapter = ComplotAdapter("8400", "רחובות", {"site_id": "22"})
    calls = []
    def request(_method, url):
        calls.append(url)
        return SimpleNamespace(text=SUMMARY)
    monkeypatch.setattr(adapter.client, "request", request)
    try:
        rows = adapter.collect(SearchUnit("u", "r", 1, "request", {"mode": "request", "requestNumber": "20260001"}), date(2026, 2, 1), date(2026, 2, 28))
        assert rows == []
        assert len(calls) == 1 and "GetBakashotByNumber" in calls[0]
    finally:
        adapter.close()


def test_unavailable_detail_retains_only_public_summary_and_requires_review(monkeypatch):
    adapter = ComplotAdapter("8400", "רחובות", {"site_id": "22"})
    def request(_method, url):
        if "GetBakashotByNumber" in url:
            return SimpleNamespace(text=SUMMARY)
        return SimpleNamespace(text='<p>לא ניתן להציג את המידע המבוקש בהתאם לשלב הסטטוטורי.</p>')
    monkeypatch.setattr(adapter.client, "request", request)
    unit = SearchUnit("u", "r", 1, "request", {"mode": "request", "requestNumber": "20260001"})
    try:
        [(_, rows, error)] = _collect_wave(adapter, [unit], date(2026, 1, 1), date(2026, 1, 31))
        assert isinstance(error, AdapterReviewRequired)
        assert len(rows) == 1 and rows[0].address == "כתובת פומבית"
        assert rows[0].details_available is False
        assert rows[0].permit_number is None and not rows[0].is_permit_issued
        assert "GetBakashotByNumber" in rows[0].source_url
        record = rows[0].to_database(run_id="r", identity_key="a", content_hash="h")
        payload, _ = build_report({"city_name": "רחובות", "date_from": "2026-01-01", "date_to": "2026-01-31", "status": "requires_review"}, [record], [])
        sheet = load_workbook(BytesIO(payload))["בקשות והיתרים"]
        assert sheet["J2"].value == "לא ידוע"
        assert sheet["L2"].value == "פרטים חלקיים — נדרשת בדיקה"
    finally:
        adapter.close()


def test_rate_limit_is_not_converted_to_a_permanent_summary_failure(monkeypatch):
    adapter = ComplotAdapter("8400", "רחובות", {"site_id": "22"})
    def request(_method, url):
        if "GetBakashotByNumber" in url:
            return SimpleNamespace(text=SUMMARY)
        raise AdapterRateLimited("429", retry_after_seconds=60)
    monkeypatch.setattr(adapter.client, "request", request)
    try:
        with pytest.raises(AdapterRateLimited):
            adapter.collect(SearchUnit("u", "r", 1, "request", {"mode": "request", "requestNumber": "20260001"}), date(2026, 1, 1), date(2026, 1, 31))
    finally:
        adapter.close()
