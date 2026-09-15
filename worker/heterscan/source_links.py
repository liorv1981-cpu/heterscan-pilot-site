"""Presentation links use municipal business identifiers, not recycled GIS OIDs."""
import re
from urllib.parse import urlencode, urlsplit

TEL_AVIV_QUERY = "https://gisn.tel-aviv.gov.il/ArcGIS/rest/services/IView2/MapServer/772/query"
TEL_AVIV_FIELDS = "request_num,addresses,permission_num,permission_date,open_request,building_stage"


def tel_aviv_source_url(application_number: str | None) -> str:
    number = str(application_number or "")
    if not re.fullmatch(r"[0-9]+", number):
        return ""
    return TEL_AVIV_QUERY + "?" + urlencode({
        "where": f"request_num = {number}", "outFields": TEL_AVIV_FIELDS,
        "returnGeometry": "false", "f": "html",
    })


def stable_source_url(source_url: str | None, application_number: str | None) -> str:
    """Correct legacy output without altering immutable collected snapshots."""
    original = str(source_url or "")
    try:
        parsed = urlsplit(original)
        if parsed.hostname == "gisn.tel-aviv.gov.il" and re.fullmatch(
            r"/ArcGIS/rest/services/IView2/MapServer/772/(?:[0-9]+|query)", parsed.path
        ):
            return tel_aviv_source_url(application_number)
    except ValueError:
        pass
    return original
