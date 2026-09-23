"""Import a pinned USDA Foundation Foods release into a local structured store.

Nutrition values remain numeric per 100 g. This is an offline research asset;
it is not part of the Medical Health Agent's answer tool yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

from .data_registry import assert_answer_eligible


BASE = Path(__file__).resolve().parent
DATA_ROOT = BASE.parents[1] / "medical-rag-data"
ARCHIVE = BASE / "source_downloads" / "FoodData_Central_foundation_food_json_2026-04-30.zip"
ARCHIVE_URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_json_2026-04-30.zip"
ARCHIVE_SHA256 = "186e988ec542e913f51ef62b86a47758e8cdd0d1dc3889e7b055581f3c09c77a"
MEMBER_NAME = "FoodData_Central_foundation_food_json_2026-04-30.json"
RELEASE = "2026-04-30"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def import_archive(archive: Path = ARCHIVE, data_root: Path = DATA_ROOT) -> dict:
    assert_answer_eligible("usda_fdc")
    archive_bytes = archive.read_bytes()
    archive_hash = _sha256(archive_bytes)
    if archive_hash != ARCHIVE_SHA256:
        raise ValueError(f"USDA archive SHA256 mismatch: {archive_hash}")
    with zipfile.ZipFile(archive) as bundle:
        if bundle.namelist() != [MEMBER_NAME]:
            raise ValueError("unexpected USDA archive members")
        json_bytes = bundle.read(MEMBER_NAME)
    payload = json.loads(json_bytes)
    if set(payload) != {"FoundationFoods"} or not isinstance(payload["FoundationFoods"], list):
        raise ValueError("unexpected USDA Foundation Foods schema")
    rows = payload["FoundationFoods"]
    foods = [row for row in rows if isinstance(row, dict)]
    null_placeholders = len(rows) - len(foods)
    if len(foods) < 300 or len({row["fdcId"] for row in foods}) != len(foods):
        raise ValueError("unexpected USDA food count or duplicate FDC ID")

    target = data_root / "structured" / f"usda_foundation_{RELEASE}.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".sqlite.part")
    if temporary.exists():
        temporary.unlink()
    food_count = nutrient_count = food_nutrient_count = missing_amount_count = 0
    try:
        with closing(sqlite3.connect(temporary)) as database:
            database.execute("PRAGMA foreign_keys=ON")
            database.executescript("""
                CREATE TABLE foods (
                    fdc_id INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    publication_date TEXT,
                    source_url TEXT NOT NULL,
                    source_release TEXT NOT NULL
                );
                CREATE TABLE nutrients (
                    nutrient_id INTEGER PRIMARY KEY,
                    nutrient_number TEXT,
                    name TEXT NOT NULL,
                    unit TEXT NOT NULL
                );
                CREATE TABLE food_nutrients (
                    fdc_id INTEGER NOT NULL REFERENCES foods(fdc_id),
                    nutrient_id INTEGER NOT NULL REFERENCES nutrients(nutrient_id),
                    amount_per_100g REAL,
                    data_points INTEGER,
                    derivation_code TEXT,
                    PRIMARY KEY (fdc_id, nutrient_id)
                );
                CREATE INDEX food_description_idx ON foods(description);
                CREATE INDEX food_nutrient_lookup_idx ON food_nutrients(nutrient_id, fdc_id);
            """)
            for food in foods:
                fdc_id = int(food["fdcId"])
                database.execute(
                    "INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?)",
                    (fdc_id, food["description"], food["dataType"], food.get("publicationDate"),
                     "https://fdc.nal.usda.gov/download-datasets/", RELEASE),
                )
                food_count += 1
                for item in food.get("foodNutrients") or []:
                    nutrient = item["nutrient"]
                    nutrient_id = int(nutrient["id"])
                    database.execute(
                        "INSERT OR IGNORE INTO nutrients VALUES (?, ?, ?, ?)",
                        (nutrient_id, nutrient.get("number"), nutrient["name"], nutrient["unitName"]),
                    )
                    amount = item.get("amount")
                    if amount is None:
                        missing_amount_count += 1
                    database.execute(
                        "INSERT INTO food_nutrients VALUES (?, ?, ?, ?, ?)",
                        (fdc_id, nutrient_id, amount, item.get("dataPoints"),
                         (item.get("foodNutrientDerivation") or {}).get("code")),
                    )
                    food_nutrient_count += 1
            nutrient_count = database.execute("SELECT COUNT(*) FROM nutrients").fetchone()[0]
            database.commit()
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()

    manifest = {
        "dataset_id": "usda_fdc",
        "data_type": "FoundationFoods",
        "release": RELEASE,
        "source_url": ARCHIVE_URL,
        "license_url": "https://fdc.nal.usda.gov/api-guide/",
        "archive_sha256": archive_hash,
        "json_sha256": _sha256(json_bytes),
        "food_records": food_count,
        "nutrient_definitions": nutrient_count,
        "food_nutrient_records": food_nutrient_count,
        "missing_amounts": missing_amount_count,
        "null_placeholders_in_source": null_placeholders,
        "unit_basis": "per 100 g of food",
        "agent_enabled": False,
    }
    manifest_path = data_root / "structured" / f"usda_foundation_{RELEASE}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def lookup_nutrient(database_path: Path, fdc_id: int, nutrient_id: int) -> dict | None:
    """Look up an exact numeric food/nutrient pair without inventing missing values."""
    with closing(sqlite3.connect(database_path)) as database:
        row = database.execute("""
            SELECT f.fdc_id, f.description, n.nutrient_id, n.name, n.unit,
                   fn.amount_per_100g, f.source_url, f.source_release
            FROM food_nutrients AS fn
            JOIN foods AS f ON f.fdc_id = fn.fdc_id
            JOIN nutrients AS n ON n.nutrient_id = fn.nutrient_id
            WHERE f.fdc_id = ? AND n.nutrient_id = ?
        """, (fdc_id, nutrient_id)).fetchone()
    if row is None:
        return None
    return dict(zip(("fdc_id", "food", "nutrient_id", "nutrient", "unit", "amount_per_100g",
                     "source_url", "source_release"), row))


def main() -> None:
    parser = argparse.ArgumentParser(description="Import pinned USDA Foundation Foods into SQLite")
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    print(json.dumps(import_archive(args.archive, args.data_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
