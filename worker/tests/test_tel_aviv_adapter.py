from datetime import date
from types import SimpleNamespace

import pytest

from heterscan.adapters import tel_aviv
from heterscan.adapters.tel_aviv import TelAvivAdapter
from heterscan.domain import SearchUnit


@pytest.mark.parametrize("building_stage", ["בתהליך היתר", "קיים היתר"])
def test_tel_aviv_uses_human_readable_building_stage_and_preserves_unknown_permit(monkeypatch, building_stage):
    adapter = TelAvivAdapter("5000", "תל אביב-יפו", {})
    calls = []
    attributes = {
        "oid_permit": 35,
        "request_num": 20260371,
        "permission_date": None,
        "permission_num": 0,
        "open_request": 1777972380000,
        "building_num": 100,
        "sug_bakasha": "היתר בנייה",
        "tochen_bakasha": "תוספת בנייה",
        "request_stage": 1,
        "building_stage": building_stage,
        "ms_tik_binyan": 12345,
        "addresses": "בורמה 20",
        "sivug_makor": "מגורים",
    }

    class FakeClient:
        def request(self, _method, _url, *, params):
            calls.append(params)
            return SimpleNamespace(json=lambda: {"features": [{"attributes": attributes}]})

        def close(self):
            pass

    monkeypatch.setattr(tel_aviv, "PublicHttpClient", lambda **_kwargs: FakeClient())
    records = adapter.collect(
        SearchUnit("unit", "run", 1, "city-wide", {}), date(2026, 1, 1), date(2026, 6, 1)
    )

    [record] = records
    assert "building_stage" in calls[0]["outFields"].split(",")
    assert record.permit_status_original == building_stage
    assert record.raw_data["request_stage"] == 1
    assert record.raw_data["building_stage"] == building_stage
    assert not record.is_permit_issued
    assert record.to_database(run_id="run", identity_key="application", content_hash="content")[
        "permit_verification"
    ] == "unknown"
