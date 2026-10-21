"""Describe collection quality separately from transport/process completion."""
from collections import Counter


def collection_outcome(run: dict, results: list[dict], units: list[dict]) -> dict:
    partial = [row for row in results if row.get("details_available") is False]
    issues = Counter()
    for row in partial:
        diagnostics = (row.get("raw_data") or {}).get("source_diagnostics") or {}
        evidence = diagnostics.get("blocking_evidence") or diagnostics
        reason = evidence.get("classification") or evidence.get("parser_result") or "unknown"
        issues[reason] += 1
    review = sum(unit.get("status") == "requires_review" for unit in units)
    failed = sum(unit.get("status") == "failed" for unit in units)
    message = None
    if run["status"] in {"requires_review", "completed_with_errors"}:
        if partial:
            summary_only = (run.get("configuration_snapshot") or {}).get("collectionMode") == "public_summary"
            message = (
                f"נשמרו {len(results)} בקשות; {len(partial)} מהן ללא פרטים מלאים. "
                + ("נבחר איסוף סיכומים בלבד. " if summary_only else "איסוף פרטי הבקשות לא הושלם. ")
                + "ספירת ההיתרים חלקית; מצב ההיתר בבקשות ללא פרטים אינו ידוע."
            )
        elif not results:
            message = "לא התקבלו בקשות שניתן לאמת; אין להסיק שלא קיימות בקשות בטווח."
        else:
            message = f"נשמרו {len(results)} בקשות, אך כיסוי החיפוש לא אומת."
        if review or failed:
            message += f" יחידות הדורשות בדיקה: {review}; יחידות שנכשלו: {failed}."
    return {"applications": len(results), "full_details": len(results) - len(partial),
            "partial_details": len(partial), "review_units": review, "failed_units": failed,
            "source_issues": dict(issues), "message": message}
