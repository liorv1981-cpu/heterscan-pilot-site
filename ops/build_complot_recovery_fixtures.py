"""Extract minimal offline fixtures from preserved public evidence; no requests/DB writes.

The HTML is reconstructed from captured fields, NOT a saved HTTP response.
Interested parties and other unrelated personal data are deliberately excluded.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "github-pages-site/worker/tests/fixtures/complot_recovery.json"


def load(relative):
    path = ROOT / relative
    return json.loads(path.read_text(encoding="utf-8-sig"))


def evidence(relative):
    return {"file": relative, "sha256": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()}


def main():
    cases = []
    folder = "outputs/herzliya-verification-2026-10-05"
    checks = load(f"{folder}/municipal-followup-reconciliation.json")["checks"]
    for number in ("20260010", "20260038"):
        relative = f"{folder}/municipal-detail-{number}.json"
        captured = load(relative)
        check = next(row for row in checks if row["request"] == number)
        events = next(table["rows"] for table in captured["tables"]
                      if table["rows"] and "סוג אירוע" in table["rows"][0])
        cases.append({"city_id": "6400", "city_name": "הרצליה", "site_id": "121",
                      "number": number, "address": check["address"],
                      "submission_date": check["submissionDate"], "fields": check["generalFields"],
                      "events": events, "evidence": evidence(relative), "source_url": captured["url"],
                      "expected_permit": check["permitNumber"], "expected_issue_date": check["permitDate"]})
    relative = f"{folder}/raw-results.json"
    raw = load(relative)["raw_results"]
    for number in ("20260011", "20260015"):
        row = next(row for row in raw if row["application_number"] == number)
        data = row["raw_data"]
        events = data["events"]
        headers = list(events[0]) if events else []
        cases.append({"city_id": "6400", "city_name": "הרצליה", "site_id": "121",
                      "number": number, "address": data["metadata"]["address"],
                      "submission_date": row["submission_date"], "fields": data["detail"],
                      "events": [headers, *([event.get(key, "") for key in headers] for event in events)],
                      "evidence": evidence(relative), "source_url": row["source_url"],
                      "expected_permit": row["permit_number"], "expected_issue_date": row["permit_issue_date"]})
    for city, name, site, number, relative in (
        ("2600", "אילת", "56", "20260001", "outputs/advanced-qa-2026-09-30/batch-final-three/2600/municipal-detail-20260001.txt"),
        ("8400", "רחובות", "22", "20260005", "outputs/advanced-qa-2026-09-30/batch-five/8400/public-detail-20260005.txt"),
    ):
        text = (ROOT / relative).read_text(encoding="utf-8-sig")
        address = re.search(r"text כתובת: (.+)", text).group(1).strip()
        submitted = re.search(r"text תאריך הגשה: (.+)", text).group(1).strip()
        fields = {}
        for key in ("מספר תיק בניין", "סוג הבקשה", "מספר היתר", "תאריך הפקת היתר"):
            match = re.search(r"text " + key + r"\r?\n\s*\d+ (?:text ([^\n]+)|link Description: ([^,\n]+))", text)
            if match:
                fields[key] = (match.group(1) or match.group(2)).strip()
        cases.append({"city_id": city, "city_name": name, "site_id": site, "number": number,
                      "address": address, "submission_date": submitted, "fields": fields, "events": [],
                      "evidence": evidence(relative), "source_url": re.search(r'URL: "([^"]+)"', text).group(1),
                      "expected_permit": "20260001" if city == "2600" else None,
                      "expected_issue_date": "2026-06-01" if city == "2600" else None})
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps({"fixture_kind": "reconstructed_from_preserved_fields",
                               "fresh_source_access": False, "cases": cases}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"Wrote {len(cases)} offline cases")


if __name__ == "__main__":
    main()
