from datetime import date

from heterscan.adapters import jerusalem as jerusalem_module
from heterscan.adapters.jerusalem import JerusalemAdapter
from heterscan.domain import SearchUnit


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    instances = []

    def __init__(self, **_kwargs):
        self.calls = []
        self.__class__.instances.append(self)

    def close(self):
        pass

    def request(self, _method, _url, *, json, **_kwargs):
        procedure = json["ProcName"]
        parameters = json["Parameters"]
        self.calls.append((procedure, parameters))
        if procedure == 242700437:
            return _Response([
                {"tik_num": "2020/0001.00"},
                {"tik_num": "2023/0042.01"},
                {"tik_num": "2025/0123.00"},
            ])
        if procedure == 242700447:
            return _Response([{
                "shemRehov": "מסילת ישרים",
                "misparBait": "18",
                "teurStatus": "הוכנה טיוטת היתר בניה",
            }])
        if procedure == 242700451:
            rows = [
                {"execDateStr": "15/07/2025", "stepCodeText": "פתיחת תיק"},
                {"execDateStr": "11/06/2026", "stepCodeText": "הפקת תצהירים לקראת הוצאת היתר"},
            ]
            if parameters["TikNum"] == "2025/0123.00":
                rows.append({"execDateStr": "20/06/2026", "stepCodeText": "הוצאת היתר בניה"})
            return _Response(rows)
        raise AssertionError(f"Unexpected procedure {procedure}")


def test_skips_case_years_outside_requested_window(monkeypatch):
    _FakeClient.instances.clear()
    monkeypatch.setattr(jerusalem_module, "PublicHttpClient", _FakeClient)
    adapter = JerusalemAdapter("3000", "ירושלים", {})
    unit = SearchUnit(
        id="unit-1",
        run_id="run-1",
        sequence=1,
        unit_key="municipal-street:16700689",
        payload={"streetCode": "16700689", "streetName": "מסילת ישרים"},
    )

    records = adapter.collect(unit, date(2025, 7, 1), date(2025, 7, 31))

    assert [record.application_number for record in records] == ["2023/0042.01", "2025/0123.00"]
    assert [record.is_permit_issued for record in records] == [False, True]
    detail_case_numbers = [
        parameters.get("tikNum") or parameters["TikNum"]
        for procedure, parameters in _FakeClient.instances[0].calls
        if procedure in (242700447, 242700451)
    ]
    assert detail_case_numbers == [
        "2023/0042.01", "2023/0042.01",
        "2025/0123.00", "2025/0123.00",
    ]
