"""Read-only workflow quality gate, run only after the report is published."""
import argparse
import json
import os
import sys
from pathlib import Path

from .supabase import SupabaseRepository


def check_run(run: dict) -> int:
    status = run["status"]
    accepted = status == "completed" and bool(run.get("report_path")) and run.get("applications_found", 0) > 0
    summary = {key: run.get(key) for key in (
        "id", "city_name", "status", "applications_found", "permits_found", "coverage_verification",
    )}
    print(json.dumps(summary, ensure_ascii=True))
    explanation = ("Collection finished; source coverage still requires separate verification." if accepted
                   else "Collection needs review. A published partial report is not a successful full scan.")
    if not accepted:
        print("::warning::" + explanation)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write("\n### Collection outcome\n\n")
            stream.write("```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n\n")
            stream.write(explanation + "\n")
    return 0 if accepted else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    repository = SupabaseRepository()
    try:
        code = check_run(repository.get_run(args.run_id))
    finally:
        repository.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
