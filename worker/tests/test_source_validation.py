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


def test_challenge_diagnostics_do_not_bypass_detection_or_reveal_script_values():
    body = '<title>Source</title><script>const secret="never log"; recaptcha()</script><div id="info-main"></div><div id="result-title-div-id"></div>'
    client = PublicHttpClient(delay_seconds=0)
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body, request=request)))
    try:
        with pytest.raises(AdapterReviewRequired) as caught:
            client.request("GET", "https://example.test/source")
        assert caught.value.diagnostics["request_detail_markup"] is True
        assert caught.value.diagnostics["captcha_in_rendered_text"] is False
        assert "never log" not in str(caught.value.diagnostics)
    finally:
        client.close()
