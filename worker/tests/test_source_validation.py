from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from heterscan.adapters.complot import ComplotAdapter
from heterscan.domain import AdapterReviewRequired, SearchUnit
from heterscan.http import PublicHttpClient
from heterscan.normalize import parse_date


@pytest.mark.parametrize("value", ["31/02/2026", "99.99.2026"])
def test_invalid_source_date_is_unknown_not_an_uncaught_exception(value):
    assert parse_date(value) is None


def test_dotted_source_date_is_parsed():
    assert parse_date("04.01.2026") == date(2026, 1, 4)


def test_missing_date_cannot_be_reported_as_an_empty_success():
    adapter = ComplotAdapter("7900", "פתח תקווה", {"site_id": "84"})
    try:
        with pytest.raises(AdapterReviewRequired, match="חסר תאריך"):
            adapter._record_from_detail("20260001", '<div id="result-title-div-id">מספר הבקשה: 20260001 כתובת: בדיקה</div>')
    finally:
        adapter.close()


def test_mismatched_detail_is_rejected():
    adapter = ComplotAdapter("7900", "פתח תקווה", {"site_id": "84"})
    try:
        with pytest.raises(AdapterReviewRequired, match="אינם מזהים"):
            adapter._record_from_detail("20260001", '<div id="result-title-div-id">מספר הבקשה: 20260002 תאריך הגשה: 01/01/2026</div>')
    finally:
        adapter.close()


def test_invalid_discovery_shape_is_not_an_empty_result(monkeypatch):
    adapter = ComplotAdapter("7900", "פתח תקווה", {"site_id": "84"})
    monkeypatch.setattr(adapter.client, "request", lambda *_args, **_kwargs: SimpleNamespace(json=lambda: {"error": "unavailable"}))
    try:
        with pytest.raises(AdapterReviewRequired, match="מבנה תשובת"):
            adapter.collect(SearchUnit("unit", "run", 1, "prefix", {"mode": "discover-prefix", "prefix": "2026"}), date(2026, 1, 1), date(2026, 1, 31))
    finally:
        adapter.close()


def test_script_only_leaves_empty_detail_for_parser_without_revealing_values():
    body = '<title>Source</title><script>const secret="never log"; recaptcha()</script><div id="info-main"></div><div id="result-title-div-id"></div>'
    client = PublicHttpClient(delay_seconds=0)
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body, request=request)))
    try:
        response = client.request("GET", "https://example.test/source")
        diagnostics = response.extensions["source_diagnostics"]
        assert diagnostics["request_detail_markup"] is True
        assert diagnostics["captcha_in_rendered_text"] is False
        assert diagnostics["challenge_script_marker"] is True
        assert diagnostics["visible_challenge"] is False
        assert "never log" not in str(diagnostics)
        adapter = ComplotAdapter("8400", "רחובות", {"site_id": "22"})
        try:
            with pytest.raises(AdapterReviewRequired) as caught:
                adapter._record_from_detail("20260001", response.text)
            assert caught.value.diagnostics["parser_result"] == "parser_mismatch"
        finally:
            adapter.close()
    finally:
        client.close()
