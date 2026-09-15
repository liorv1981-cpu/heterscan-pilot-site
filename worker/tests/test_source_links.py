from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from openpyxl import load_workbook
from heterscan.reporting import build_report
from heterscan.source_links import stable_source_url, tel_aviv_source_url

OLD = "https://gisn.tel-aviv.gov.il/ArcGIS/rest/services/IView2/MapServer/772/4223"


def test_recycled_oid_resolves_by_snapshot_request_number():
    for number in ("20260016", "20260053"):
        url = urlsplit(stable_source_url(OLD, number))
        assert url.path.endswith("/query")
        assert parse_qs(url.query)["where"] == [f"request_num = {number}"]


def test_missing_or_injectable_identity_never_links_wrong_record():
    for number in (None, "", "1 OR 1=1"):
        assert tel_aviv_source_url(number) == ""


def test_unrelated_and_malformed_urls_preserved():
    for url in ("https://example.test/4223", "https://[bad", OLD.replace(".gov.il/", ".gov.il.evil.test/")):
        assert stable_source_url(url, "20260016") == url


def test_report_corrects_link_without_mutating_historical_input():
    row = {"application_number": "20260016", "source_url": OLD}
    run = {"city_name": "תל אביב-יפו", "date_from": "2026-01-01", "date_to": "2026-01-31", "status": "completed"}
    payload, _ = build_report(run, [row], [])
    book = load_workbook(BytesIO(payload))
    for sheet in ("בקשות והיתרים", "כל התוצאות"):
        assert book[sheet]["O2"].hyperlink.target == tel_aviv_source_url("20260016")
    assert row["source_url"] == OLD
