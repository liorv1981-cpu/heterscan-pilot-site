from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from heterscan.adapters import complot as complot_module
from heterscan.adapters.complot import ComplotAdapter
from heterscan.domain import AdapterReviewRequired, DiscoveryResult, SearchUnit


class _Response:
    def __init__(self, text: str = "", data=None) -> None:
        self.text = text
        self._data = data

    def json(self):
        return self._data


class _SharedFakeClient:
    instances = []
    request_number_length = 8

    def __init__(self, **_kwargs) -> None:
        self.calls: list[str] = []
        self.closed = False
        self.__class__.instances.append(self)

    def close(self) -> None:
        self.closed = True

    def request(self, _method: str, url: str, **_kwargs) -> _Response:
        self.calls.append(url)
        if url == ComplotAdapter.autocomplete_url:
            prefix = str(_kwargs["json"]["prefix"])
            remaining_digits = self.request_number_length - len(prefix)
            return _Response(
                data={"d": [{"label": f"{prefix}{index:0{remaining_digits}d}"} for index in range(10)]}
            )
        query = parse_qs(urlparse(url).query)
        if query["prgname"] == ["GetBakashotByAddress"]:
            return _Response("""
              <table><tbody>
                <tr><td></td><td><a href="javascript:getRequest(1001)">1001</a></td><td>F1</td><td>01/07/2025</td><td></td><td>רחוב 1</td><td>1</td><td>2</td></tr>
                <tr><td></td><td><a href="javascript:getRequest(1002)">1002</a></td><td>F2</td><td>15/07/2025</td><td></td><td>רחוב 2</td><td>3</td><td>4</td></tr>
                <tr><td></td><td><a href="javascript:getRequest(999)">999</a></td><td>F0</td><td>01/06/2025</td><td></td><td>רחוב 0</td><td>5</td><td>6</td></tr>
              </tbody></table>
            """)
        request_number = query["b"][0]
        return _Response(f"""
          <div id="result-title-div-id">
            מספר הבקשה: {request_number} כתובת: רחוב הבדיקה 7 תאריך הגשה: 10/07/2025
          </div>
          <div id="info-main"><table>
            <tr><td>מספר תיק בניין</td><td>F-{request_number}</td></tr>
            <tr><td>מספר היתר</td><td>H-{request_number}</td></tr>
            <tr><td>תאריך היתר</td><td>20/07/2025</td></tr>
          </table></div>
          <table id="table-events">
            <tr><th>סוג אירוע</th><th>תיאור אירוע</th></tr>
            <tr><td>נוכחי</td><td>היתר בתוקף</td></tr>
          </table>
        """)


class _TenDigitFakeClient(_SharedFakeClient):
    instances = []
    request_number_length = 10


class _PrefixHintFakeClient(_SharedFakeClient):
    instances = []

    def request(self, _method: str, url: str, **_kwargs) -> _Response:
        self.calls.append(url)
        prefix = str(_kwargs["json"]["prefix"])
        return _Response(
            data={"d": [{"label": prefix}, *({"label": f"{prefix}{index}"} for index in range(9))]}
        )


def test_collect_returns_every_in_range_application_and_reuses_one_client(monkeypatch) -> None:
    _SharedFakeClient.instances.clear()
    monkeypatch.setattr(complot_module, "PublicHttpClient", _SharedFakeClient)
    adapter = ComplotAdapter("7900", "פתח תקווה", {"site_id": "84", "locality_code": "7900"})
    unit = SearchUnit(
        id="unit-1",
        run_id="run-1",
        sequence=1,
        unit_key="street:101",
        payload={"streetCode": "101", "streetName": "אבן גבירול"},
    )

    records = adapter.collect(unit, date(2025, 7, 1), date(2025, 7, 31))

    assert [record.application_number for record in records] == ["1001", "1002"]
    assert [record.permit_number for record in records] == ["H-1001", "H-1002"]
    assert len(_SharedFakeClient.instances) == 1
    assert len(_SharedFakeClient.instances[0].calls) == 3
    adapter.close()
    assert _SharedFakeClient.instances[0].closed is True


def test_yavne_records_link_to_the_public_search_result() -> None:
    adapter = ComplotAdapter("2660", "יבנה", {"site_id": "87", "locality_code": "2660"})

    assert adapter._public_source_url("20260008") == (
        "https://yavne.complot.co.il/iturbakashot2/"
        "#search/GetBakashotByNumber&siteid=87&grp=0&t=0"
        "&b=20260008&l=true&arguments=siteId,grp,t,b,l"
    )


def test_full_discovery_prefix_creates_requests_and_durable_child_prefixes(monkeypatch) -> None:
    _SharedFakeClient.instances.clear()
    monkeypatch.setattr(complot_module, "PublicHttpClient", _SharedFakeClient)
    adapter = ComplotAdapter("7900", "פתח תקווה", {"site_id": "84"})
    unit = SearchUnit(
        id="unit-1",
        run_id="run-1",
        sequence=1,
        unit_key="discover-prefix:2026",
        payload={"mode": "discover-prefix", "prefix": "2026", "year": "2026"},
    )

    result = adapter.collect(unit, date(2026, 1, 1), date(2026, 12, 31))

    assert isinstance(result, DiscoveryResult)
    assert len(result.units) == 20
    assert result.units[0].unit_key == "request:20260000"
    assert result.units[9].unit_key == "request:20260009"
    assert [item.unit_key for item in result.units[10:]] == [
        f"discover-prefix:2026{digit}" for digit in range(10)
    ]
    assert len(_SharedFakeClient.instances[0].calls) == 1


def test_ten_digit_request_numbers_are_discovered_when_configured(monkeypatch) -> None:
    _TenDigitFakeClient.instances.clear()
    monkeypatch.setattr(complot_module, "PublicHttpClient", _TenDigitFakeClient)
    adapter = ComplotAdapter("4000", "חיפה", {"site_id": "16", "request_number_length": 10})
    unit = SearchUnit(
        id="unit-1",
        run_id="run-1",
        sequence=1,
        unit_key="discover-prefix:2026",
        payload={"mode": "discover-prefix", "prefix": "2026", "year": "2026"},
    )

    result = adapter.collect(unit, date(2026, 1, 1), date(2026, 12, 31))

    assert isinstance(result, DiscoveryResult)
    assert result.units[0].unit_key == "request:2026000000"
    assert result.units[9].unit_key == "request:2026000009"
    assert len(result.units) == 20


def test_unexpected_request_number_length_requires_review(monkeypatch) -> None:
    _TenDigitFakeClient.instances.clear()
    monkeypatch.setattr(complot_module, "PublicHttpClient", _TenDigitFakeClient)
    adapter = ComplotAdapter("4000", "חיפה", {"site_id": "16", "request_number_length": 8})
    unit = SearchUnit(
        id="unit-1",
        run_id="run-1",
        sequence=1,
        unit_key="discover-prefix:2026",
        payload={"mode": "discover-prefix", "prefix": "2026", "year": "2026"},
    )

    with pytest.raises(AdapterReviewRequired, match="הוגדר 8, התקבל 10"):
        adapter.collect(unit, date(2026, 1, 1), date(2026, 12, 31))


def test_shorter_autocomplete_hints_continue_prefix_discovery(monkeypatch) -> None:
    _PrefixHintFakeClient.instances.clear()
    monkeypatch.setattr(complot_module, "PublicHttpClient", _PrefixHintFakeClient)
    adapter = ComplotAdapter("6200", "בת ים", {"site_id": "81", "request_number_length": 8})
    unit = SearchUnit(
        id="unit-1",
        run_id="run-1",
        sequence=1,
        unit_key="discover-prefix:2026",
        payload={"mode": "discover-prefix", "prefix": "2026", "year": "2026"},
    )

    result = adapter.collect(unit, date(2026, 1, 1), date(2026, 12, 31))

    assert isinstance(result, DiscoveryResult)
    assert [item.unit_key for item in result.units] == [
        f"discover-prefix:2026{digit}" for digit in range(10)
    ]


def test_direct_request_refresh_reads_latest_status_without_street_scan(monkeypatch) -> None:
    _SharedFakeClient.instances.clear()
    monkeypatch.setattr(complot_module, "PublicHttpClient", _SharedFakeClient)
    adapter = ComplotAdapter("7900", "פתח תקווה", {"site_id": "84"})
    unit = SearchUnit(
        id="unit-1",
        run_id="run-1",
        sequence=1,
        unit_key="request:20260843",
        payload={
            "mode": "request",
            "requestNumber": "20260843",
            "address": "כתובת ישנה",
            "submissionDate": "2025-07-10",
        },
    )

    records = adapter.collect(unit, date(2025, 1, 1), date(2025, 12, 31))

    assert len(records) == 1
    assert records[0].application_number == "20260843"
    assert records[0].address == "רחוב הבדיקה 7"
    assert records[0].submission_date == date(2025, 7, 10)
    assert records[0].building_file_number == "F-20260843"
    assert records[0].permit_status_original == "היתר בתוקף"
    assert len(_SharedFakeClient.instances[0].calls) == 1
    assert "GetBakashaFile" in _SharedFakeClient.instances[0].calls[0]


def test_seven_digit_prefix_does_not_repeat_complete_request_numbers(monkeypatch) -> None:
    _SharedFakeClient.instances.clear()
    monkeypatch.setattr(complot_module, "PublicHttpClient", _SharedFakeClient)
    adapter = ComplotAdapter("7900", "פתח תקווה", {"site_id": "84"})
    unit = SearchUnit(
        id="unit-1",
        run_id="run-1",
        sequence=1,
        unit_key="discover-prefix:2026000",
        payload={"mode": "discover-prefix", "prefix": "2026000", "year": "2026"},
    )

    result = adapter.collect(unit, date(2026, 1, 1), date(2026, 12, 31))

    assert isinstance(result, DiscoveryResult)
    assert len(result.units) == 10
    assert all(item.unit_key.startswith("request:") for item in result.units)
