from datetime import date
from urllib.parse import parse_qs, urlparse

from heterscan.adapters import complot as complot_module
from heterscan.adapters.complot import ComplotAdapter
from heterscan.domain import SearchUnit


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class _SharedFakeClient:
    instances = []

    def __init__(self, **_kwargs) -> None:
        self.calls: list[str] = []
        self.closed = False
        self.__class__.instances.append(self)

    def close(self) -> None:
        self.closed = True

    def request(self, _method: str, url: str, **_kwargs) -> _Response:
        self.calls.append(url)
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
          <table>
            <tr><td>מספר היתר</td><td>H-{request_number}</td></tr>
            <tr><td>תאריך היתר</td><td>20/07/2025</td></tr>
            <tr><td>סטטוס</td><td>היתר בתוקף</td></tr>
          </table>
        """)


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
