from datetime import date

import pytest

from heterscan.domain import ApplicationRecord, SearchUnit
from heterscan.validator import validate_records


class Source:
    name = "complot"
    city_id = "8400"
    city_name = "רחובות"
    config = {"public_search_url": "https://rechovot.complot.co.il/iturbakashot/"}


def captured_record(number, summary_address, detail_address):
    # Confirmed, already-collected Rehovot payload fields; no HTTP access.
    is_gordon = number == "20260021"
    building, parcel, submitted = ("139900000", "651", "08/01/2026") if is_gordon else ("135660100", "1390", "14/01/2026")
    record = ApplicationRecord(city_id="8400", application_number=number, address=detail_address,
        submission_date=date(2026, 1, 8 if is_gordon else 14), building_file_number=building,
        block_number="3703", parcel_number=parcel,
        source_url=f"https://rechovot.complot.co.il/iturbakashot/#request/{number}",
        source_reference=number, adapter_name="complot", adapter_version="0.4.0",
        raw_data={"public_summary": {"request_number":number,"submission_date":submitted,
            "address":summary_address,"building_file":building,"block":"3703","parcel":parcel},
            "metadata":{"request_number":number,"submission_date":submitted,"address":detail_address},
            "detail":{"מספר תיק בניין":building},
            "parcels":[{"מספר גוש":"3703","מספר חלקה":parcel}]})
    unit = SearchUnit("u", "r", 1, f"request:{number}", {"mode":"request","requestNumber":number})
    return record, unit


def validate(record, unit):
    return validate_records([record], unit, Source(), date(2026, 1, 1), date(2026, 1, 31))


@pytest.mark.parametrize("number,coarse,precise,extra", [
    ("20260021","גורדון 38 רחובות","גורדון 38 0 רחובות","0"),
    ("20260034","טלר 9 רחובות","טלר 9 ב רחובות","ב"),
])
def test_confirmed_base_and_land_identity_keep_detail_component_without_claiming_it_is_corroborated(number, coarse, precise, extra):
    record, unit = captured_record(number, coarse, precise)
    outcome = validate(record, unit)
    assert outcome.issues == [] and outcome.records[0].details_available is True
    assert record.address == precise
    assert record.raw_data["metadata"]["address"] == precise
    assert record.raw_data["public_summary"]["address"] == coarse
    evidence = record.raw_data["validator"]["address_evidence"]
    assert evidence["verified_scope"] == "street_and_house_number"
    assert evidence["detail_extra_component"] == extra
    assert evidence["detail_extra_component_corroborated"] is False
    assert "address" not in record.raw_data["validator"]["checked_fields"]
    assert record.to_database(run_id="r",identity_key="fixture",content_hash="fixture")["permit_verification"] == "unknown"


@pytest.mark.parametrize("coarse,precise", [
    ("טלר 9 רחובות","טלר 10 ב רחובות"),
    ("טלר 9 רחובות","הרצל 9 ב רחובות"),
    ("טלר 9 א רחובות","טלר 9 ב רחובות"),
    ("טלר 9 רחובות","טלר 9 1 רחובות"),
    ("טלר 9 רחובות","טלר 9 10 רחובות"),
    ("טלר 9 רחובות","טלר 9 0 0 רחובות"),
    ("טלר 9 רחובות","טלר 9 ב 0 רחובות"),
    ("טלר 9 רחובות","טלר 9/1 רחובות"),
    ("טלר 9 רחובות","טלר 9/0 רחובות"),
    ("טלר 9 רחובות","טלר 9-0 רחובות"),
    ("טלר 9 רחובות","טלר 9.0 רחובות"),
    ("טלר 9 רחובות","טלר 9,0 רחובות"),
    ("טלר 9 רחובות","טלר 9–0 רחובות"),
    ("טלר 9 רחובות","טלר 9־0 רחובות"),
])
def test_real_or_ambiguous_address_differences_still_require_review(coarse, precise):
    record, unit = captured_record("20260034", coarse, precise)
    outcome = validate(record, unit)
    assert "detail_address_mismatch" in {issue.code for issue in outcome.issues}
    assert outcome.records[0].details_available is False


@pytest.mark.parametrize("mutation", ["building", "block", "parcel", "multiple_parcels", "missing_building", "normalized_land", "unrelated_record_address"])
def test_compatible_base_without_all_matching_corroboration_is_not_accepted(mutation):
    record, unit = captured_record("20260034", "טלר 9 רחובות", "טלר 9 ב רחובות")
    if mutation == "building":
        record.raw_data["detail"]["מספר תיק בניין"] = "999"
    elif mutation == "missing_building":
        record.raw_data["detail"] = {}
    elif mutation == "block":
        record.raw_data["parcels"][0]["מספר גוש"] = "999"
    elif mutation == "parcel":
        record.raw_data["parcels"][0]["מספר חלקה"] = "999"
    elif mutation == "multiple_parcels":
        record.raw_data["parcels"].append({"מספר גוש":"3703","מספר חלקה":"999"})
    elif mutation == "normalized_land":
        record.parcel_number = "999"
    else:
        record.address = "הרצל 9 רחובות"
    outcome = validate(record, unit)
    assert "detail_address_mismatch" in {issue.code for issue in outcome.issues}
    assert outcome.records[0].details_available is False


def test_address_precision_exception_does_not_relax_permit_evidence():
    record, unit = captured_record("20260034", "טלר 9 רחובות", "טלר 9 ב רחובות")
    record.is_permit_issued = True
    record.permit_number = "invented"
    outcome = validate(record, unit)
    assert "permit_issuance_mismatch" in {issue.code for issue in outcome.issues}
    assert not outcome.records[0].is_permit_issued


@pytest.mark.parametrize("field,value", [("request_number", "20260035"), ("submission_date", "15/01/2026")])
def test_address_precision_is_not_accepted_when_detail_identity_or_date_disagrees(field, value):
    record, unit = captured_record("20260034", "טלר 9 רחובות", "טלר 9 ב רחובות")
    record.raw_data["metadata"][field] = value
    outcome = validate(record, unit)
    assert "detail_address_mismatch" in {issue.code for issue in outcome.issues}
    assert outcome.records[0].details_available is False


@pytest.mark.parametrize("identity", ["building", "block", "parcel"])
def test_zero_placeholder_is_not_corroborating_land_identity(identity):
    record, unit = captured_record("20260034", "טלר 9 רחובות", "טלר 9 ב רחובות")
    if identity == "building":
        record.building_file_number = "0"
        record.raw_data["public_summary"]["building_file"] = "0"
        record.raw_data["detail"]["מספר תיק בניין"] = "0"
    elif identity == "block":
        record.block_number = "0"
        record.raw_data["public_summary"]["block"] = "0"
        record.raw_data["parcels"][0]["מספר גוש"] = "0"
    else:
        record.parcel_number = "0"
        record.raw_data["public_summary"]["parcel"] = "0"
        record.raw_data["parcels"][0]["מספר חלקה"] = "0"
    outcome = validate(record, unit)
    assert "detail_address_mismatch" in {issue.code for issue in outcome.issues}
    assert outcome.records[0].details_available is False
