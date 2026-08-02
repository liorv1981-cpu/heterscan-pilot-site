from __future__ import annotations

from datetime import date

from ..domain import ApplicationRecord, SearchUnit
from ..http import PublicHttpClient
from ..normalize import clean_text, in_range, parse_date
from .base import Adapter


class TelAvivAdapter(Adapter):
    name = "tel_aviv"
    query_url = "https://gisn.tel-aviv.gov.il/ArcGIS/rest/services/IView2/MapServer/772/query"
    fields = ",".join(
        [
            "oid_permit", "request_num", "permission_date", "permission_num", "open_request",
            "building_num", "sug_bakasha", "tochen_bakasha", "request_stage", "ms_tik_binyan",
            "addresses", "sivug_makor",
        ]
    )

    def collect(self, unit: SearchUnit, date_from: date, date_to: date) -> list[ApplicationRecord]:
        del unit
        client = PublicHttpClient(delay_seconds=0.3)
        output: list[ApplicationRecord] = []
        offset = 0
        try:
            while True:
                response = client.request(
                    "GET",
                    self.query_url,
                    params={
                        "f": "json",
                        "where": (
                            f"open_request >= timestamp '{date_from.isoformat()} 00:00:00' "
                            f"AND open_request <= timestamp '{date_to.isoformat()} 23:59:59'"
                        ),
                        "outFields": self.fields,
                        "returnGeometry": "false",
                        "resultOffset": offset,
                        "resultRecordCount": 500,
                        "orderByFields": "oid_permit",
                    },
                )
                payload = response.json()
                if payload.get("error"):
                    raise RuntimeError(f"ArcGIS error: {payload['error']}")
                features = payload.get("features") or []
                for feature in features:
                    attrs = feature.get("attributes") or {}
                    submitted = parse_date(attrs.get("open_request"))
                    if not in_range(submitted, date_from, date_to):
                        continue
                    permit_number = clean_text(attrs.get("permission_num")) or None
                    permit_date = parse_date(attrs.get("permission_date"))
                    issued = bool(permit_number and permit_date)
                    request_number = clean_text(attrs.get("request_num")) or None
                    source_reference = clean_text(attrs.get("oid_permit")) or request_number
                    output.append(
                        ApplicationRecord(
                            city_id=self.city_id,
                            application_number=request_number,
                            building_file_number=clean_text(attrs.get("ms_tik_binyan")) or None,
                            address=clean_text(attrs.get("addresses")) or None,
                            application_type=clean_text(attrs.get("sug_bakasha")) or None,
                            work_description=clean_text(attrs.get("tochen_bakasha")) or None,
                            submission_date=submitted,
                            approval_date=permit_date if issued else None,
                            is_approved=issued,
                            approval_confidence="high" if issued else None,
                            permit_number=permit_number,
                            permit_issue_date=permit_date,
                            permit_status_original=clean_text(attrs.get("request_stage")) or None,
                            is_permit_issued=issued,
                            permit_confidence="high" if issued else None,
                            source_url=f"https://gisn.tel-aviv.gov.il/ArcGIS/rest/services/IView2/MapServer/772/{source_reference}",
                            source_reference=source_reference,
                            adapter_name=self.name,
                            adapter_version=self.version,
                            raw_data=attrs,
                            evidence=[{"type": "arcgis_fields", "permit_number": permit_number, "permit_issue_date": str(permit_date or "")}],
                        )
                    )
                if not features or len(features) < 500:
                    break
                offset += len(features)
        finally:
            client.close()
        return output
