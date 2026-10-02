from datetime import date, datetime, timezone

from heterscan.domain import AdapterReviewRequired, ApplicationRecord, SearchUnit
from heterscan.runner import _collect_wave
from heterscan.validator import validate_records


class ComplotSource:
    name = "complot"
    city_id = "8400"
    city_name = "רחובות"
    config = {"site_id": "22", "public_search_url": "https://rechovot.complot.co.il/iturbakashot/"}

    def parallelism(self):
        return 1

    def _summary_source_url(self, number):
        return f"https://rechovot.complot.co.il/iturbakashot/#search/GetBakashotByNumber&siteid=22&b={number}"


def complot_record(*, detail_date: str = "01/01/2026", issued: bool = False) -> ApplicationRecord:
    detail = {"מספר היתר": "20260005", "תאריך הפקת היתר": "01/06/2026"} if issued else {}
    return ApplicationRecord(
        city_id="8400", application_number="20260005", address="בר-לב חיים 8 רחובות",
        submission_date=date(2026, 1, int(detail_date[:2])),
        source_url="https://rechovot.complot.co.il/iturbakashot/#request/20260005",
        source_reference="20260005", adapter_name="complot", adapter_version="0.3.0",
        permit_number="20260005" if issued else None,
        permit_issue_date=date(2026, 6, 1) if issued else None,
        is_permit_issued=issued,
        raw_data={
            "public_summary": {"request_number": "20260005", "submission_date": "01/01/2026",
                               "address": "בר-לב חיים 8 רחובות", "building_file": "90270490"},
            "metadata": {"request_number": "20260005", "submission_date": detail_date,
                         "address": "בר-לב חיים 8 רחובות"},
            "detail": detail,
        },
    )


def test_known_rehovot_application_cross_checks_without_new_source_request() -> None:
    unit = SearchUnit("u", "r", 1, "request:20260005", {"mode": "request", "requestNumber": "20260005"})
    outcome = validate_records([complot_record()], unit, ComplotSource(), date(2026, 1, 1), date(2026, 1, 31))
    assert outcome.issues == []
    assert outcome.records[0].raw_data["validator"]["status"] == "passed_consistency_checks"
    assert outcome.records[0].raw_data["validator"]["level"] == "cross_source_payloads"


def test_detail_date_disagreement_keeps_public_summary_and_unknown_permit() -> None:
    unit = SearchUnit("u", "r", 1, "request:20260005", {"mode": "request", "requestNumber": "20260005"})
    outcome = validate_records([complot_record(detail_date="02/01/2026", issued=True)], unit, ComplotSource(),
                               date(2026, 1, 1), date(2026, 1, 31))
    assert {issue.code for issue in outcome.issues} >= {"summary_date_mismatch"}
    [safe] = outcome.records
    assert safe.submission_date == date(2026, 1, 1)
    assert safe.details_available is False and safe.permit_number is None
    assert safe.is_permit_issued is False
    assert safe.raw_data["validator"]["status"] == "requires_review"


def test_missed_explicit_permit_is_flagged_before_persistence() -> None:
    unit = SearchUnit("u", "r", 1, "request:20260005", {"mode": "request", "requestNumber": "20260005"})
    record = complot_record(issued=True)
    record.is_permit_issued = False
    record.permit_number = None
    record.permit_issue_date = None
    outcome = validate_records([record], unit, ComplotSource(), date(2026, 1, 1), date(2026, 1, 31))
    assert "permit_issuance_mismatch" in {issue.code for issue in outcome.issues}
    assert outcome.records[0].details_available is False
    assert outcome.records[0].to_database(run_id="r", identity_key="application:20260005", content_hash="h")["permit_verification"] == "unknown"


def test_explicit_complot_permit_keeps_verified_issue_fields() -> None:
    unit = SearchUnit("u", "r", 1, "request:20260005", {"mode": "request", "requestNumber": "20260005"})
    outcome = validate_records([complot_record(issued=True)], unit, ComplotSource(), date(2026, 1, 1), date(2026, 1, 31))
    assert outcome.issues == []
    assert outcome.records[0].permit_number == "20260005"
    assert outcome.records[0].permit_issue_date == date(2026, 6, 1)


def test_runner_preserves_other_records_when_one_complot_record_disagrees() -> None:
    class Adapter(ComplotSource):
        def collect(self, *_args):
            valid = complot_record()
            conflicting = complot_record(detail_date="02/01/2026")
            conflicting.application_number = "20260006"
            conflicting.source_url = "https://rechovot.complot.co.il/iturbakashot/#request/20260006"
            conflicting.raw_data = {
                **conflicting.raw_data,
                "public_summary": {**conflicting.raw_data["public_summary"], "request_number": "20260006"},
                "metadata": {**conflicting.raw_data["metadata"], "request_number": "20260006"},
            }
            return [valid, conflicting]

    unit = SearchUnit("u", "r", 1, "street:1", {"streetCode": "1"})
    [(returned_unit, records, error)] = _collect_wave(Adapter(), [unit], date(2026, 1, 1), date(2026, 1, 31))
    assert returned_unit is unit
    assert isinstance(error, AdapterReviewRequired)
    assert len(records) == 2
    assert records[0].details_available is True
    assert records[1].details_available is False
    assert records[1].submission_date == date(2026, 1, 1)


def test_out_of_range_detail_cannot_erase_an_in_range_public_summary() -> None:
    class Adapter(ComplotSource):
        def collect(self, *_args):
            record = complot_record(detail_date="01/02/2026")
            record.submission_date = date(2026, 2, 1)
            return [record]

    unit = SearchUnit("u", "r", 1, "request:20260005", {"mode": "request", "requestNumber": "20260005"})
    [(_, records, error)] = _collect_wave(Adapter(), [unit], date(2026, 1, 1), date(2026, 1, 31))
    assert isinstance(error, AdapterReviewRequired)
    assert len(records) == 1
    assert records[0].submission_date == date(2026, 1, 1)
    assert records[0].details_available is False


def test_source_link_to_another_application_retains_a_reviewable_public_summary() -> None:
    unit = SearchUnit("u", "r", 1, "request:20260005", {"mode": "request", "requestNumber": "20260005"})
    record = complot_record()
    record.source_url = "https://rechovot.complot.co.il/iturbakashot/#request/20260006"
    outcome = validate_records([record], unit, ComplotSource(), date(2026, 1, 1), date(2026, 1, 31))
    assert "source_link_number_mismatch" in {issue.code for issue in outcome.issues}
    assert len(outcome.records) == 1
    assert outcome.records[0].details_available is False
    assert "b=20260005" in outcome.records[0].source_url


def test_jerusalem_and_tel_aviv_payloads_use_their_own_identifiers() -> None:
    class Jerusalem:
        name, city_id, city_name, config = "jerusalem", "3000", "ירושלים", {}

    jerusalem = ApplicationRecord(
        city_id="3000", application_number="2026/0059.00", address="הרצל 8",
        submission_date=date(2026, 1, 27), source_url="https://ykpubdata.jerusalem.muni.il/#/Rishui/BakashalInfo?TikNum=2026/0059.00",
        source_reference="2026/0059.00", adapter_name="jerusalem", adapter_version="0.1.0",
        raw_data={"candidate": {"tik_num": "2026/0059.00"}, "detail": {"shemRehov": "הרצל"},
                  "process": [{"execDateStr": "27/01/2026", "stepCodeText": "קליטת בקשה"}]},
    )
    jerusalem_result = validate_records([jerusalem], SearchUnit("u", "r", 1, "street:1", {}), Jerusalem(),
                                        date(2026, 1, 1), date(2026, 1, 31))
    assert jerusalem_result.issues == []

    class TelAviv:
        name, city_id, city_name, config = "tel_aviv", "5000", "תל אביב-יפו", {}

    opened = int(datetime(2026, 1, 7, tzinfo=timezone.utc).timestamp() * 1000)
    tel_aviv = ApplicationRecord(
        city_id="5000", application_number="20260016", address="דיזנגוף 8",
        submission_date=date(2026, 1, 7),
        source_url="https://gisn.tel-aviv.gov.il/ArcGIS/rest/services/IView2/MapServer/772/query?where=request_num%3D20260016",
        source_reference="42", adapter_name="tel_aviv", adapter_version="0.2.0",
        raw_data={"request_num": "20260016", "open_request": opened,
                  "permission_num": 0, "permission_date": None},
    )
    tel_aviv_result = validate_records([tel_aviv], SearchUnit("u", "r", 1, "city-wide", {}), TelAviv(),
                                       date(2026, 1, 1), date(2026, 1, 31))
    assert tel_aviv_result.issues == []


def test_explicit_jerusalem_and_tel_aviv_permits_remain_issued() -> None:
    class Jerusalem:
        name, city_id, city_name, config = "jerusalem", "3000", "ירושלים", {}

    jerusalem = ApplicationRecord(
        city_id="3000", application_number="2026/0059.00", address="הרצל 8",
        submission_date=date(2026, 1, 27), permit_issue_date=date(2026, 7, 1),
        is_permit_issued=True, permit_status_original="הופק-הוצא היתר בניה",
        source_url="https://ykpubdata.jerusalem.muni.il/#/Rishui/BakashalInfo?TikNum=2026/0059.00",
        source_reference="2026/0059.00", adapter_name="jerusalem", adapter_version="0.1.0",
        raw_data={"candidate": {"tik_num": "2026/0059.00"},
                  "detail": {"shemRehov": "הרצל", "teurStatus": "הופק-הוצא היתר בניה"},
                  "process": [{"execDateStr": "27/01/2026", "stepCodeText": "קליטת בקשה"},
                              {"execDateStr": "01/07/2026", "stepCodeText": "חתימה אלקטרונית על היתר בניה"}]},
    )
    outcome = validate_records([jerusalem], SearchUnit("u", "r", 1, "street:1", {}), Jerusalem(),
                               date(2026, 1, 1), date(2026, 1, 31))
    assert outcome.issues == []

    class TelAviv:
        name, city_id, city_name, config = "tel_aviv", "5000", "תל אביב-יפו", {}

    opened = int(datetime(2026, 1, 11, tzinfo=timezone.utc).timestamp() * 1000)
    issued = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
    tel_aviv = ApplicationRecord(
        city_id="5000", application_number="20260022", address="דיזנגוף 8",
        submission_date=date(2026, 1, 11), permit_number="20260546",
        permit_issue_date=date(2026, 2, 1), is_permit_issued=True,
        source_url="https://gisn.tel-aviv.gov.il/ArcGIS/rest/services/IView2/MapServer/772/query?where=request_num%3D20260022",
        source_reference="43", adapter_name="tel_aviv", adapter_version="0.2.0",
        raw_data={"request_num": "20260022", "open_request": opened,
                  "permission_num": "20260546", "permission_date": issued},
    )
    outcome = validate_records([tel_aviv], SearchUnit("u", "r", 1, "city-wide", {}), TelAviv(),
                               date(2026, 1, 1), date(2026, 1, 31))
    assert outcome.issues == []
