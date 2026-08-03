from __future__ import annotations

from datetime import datetime, timezone

from .http import PublicHttpClient
from .normalize import clean_text
from .supabase import SupabaseRepository

API_URL = "https://jerbasicserviceapi.jerusalem.muni.il/api/Db/ExecuteGetJSON"
CITY_ID = "3000"


def sync(repository: SupabaseRepository) -> int:
    client = PublicHttpClient(delay_seconds=0)
    try:
        response = client.request(
            "POST",
            API_URL,
            json={"ProcName": 242700426, "Cnn": "cnnGisYk", "Parameters": {}},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        unique: dict[str, dict[str, str]] = {}
        fetched_at = datetime.now(timezone.utc).isoformat()
        for row in response.json() or []:
            code = clean_text(row.get("Semel"))
            name = clean_text(row.get("StreetName"))
            if code and name:
                unique[code] = {
                    "city_id": CITY_ID,
                    "municipal_code": code,
                    "municipal_name": name,
                    "fetched_at": fetched_at,
                }
        if not unique:
            raise RuntimeError("Jerusalem municipal street catalog returned no usable streets")
        return repository.upsert_many(
            "municipal_streets",
            unique.values(),
            conflict="city_id,municipal_code",
            batch_size=400,
        )
    finally:
        client.close()


def main() -> None:
    repository = SupabaseRepository()
    try:
        count = sync(repository)
        print(f"Synchronized {count:,} Jerusalem municipal streets")
    finally:
        repository.close()


if __name__ == "__main__":
    main()
