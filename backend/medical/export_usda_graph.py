"""Export exact USDA food-nutrient relations; this does not enable GraphRAG."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .import_usda_foundation import DATA_ROOT, RELEASE


def export_graph(data_root: Path = DATA_ROOT) -> dict:
    database_path = data_root / "structured" / f"usda_foundation_{RELEASE}.sqlite"
    graph_dir = data_root / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    nodes_path = graph_dir / f"usda_foundation_{RELEASE}_nodes.csv"
    edges_path = graph_dir / f"usda_foundation_{RELEASE}_edges.csv"
    with closing(sqlite3.connect(database_path)) as database:
        foods = database.execute("SELECT fdc_id, description, source_url FROM foods ORDER BY fdc_id").fetchall()
        nutrients = database.execute("SELECT nutrient_id, name, unit FROM nutrients ORDER BY nutrient_id").fetchall()
        relations = database.execute("""
            SELECT fn.fdc_id, fn.nutrient_id, fn.amount_per_100g, n.unit, f.source_url
            FROM food_nutrients AS fn
            JOIN nutrients AS n ON n.nutrient_id = fn.nutrient_id
            JOIN foods AS f ON f.fdc_id = fn.fdc_id
            ORDER BY fn.fdc_id, fn.nutrient_id
        """).fetchall()
    with nodes_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("node_id", "node_type", "name", "unit", "source_url", "dataset_id", "release"))
        for fdc_id, name, url in foods:
            writer.writerow((f"FDC:{fdc_id}", "Food", name, "", url, "usda_fdc", RELEASE))
        for nutrient_id, name, unit in nutrients:
            writer.writerow((f"FDC-NUTRIENT:{nutrient_id}", "Nutrient", name, unit,
                             "https://fdc.nal.usda.gov/download-datasets/", "usda_fdc", RELEASE))
    with edges_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("source_id", "predicate", "target_id", "amount_per_100g", "unit",
                         "source_url", "dataset_id", "release", "evidence_type"))
        for fdc_id, nutrient_id, amount, unit, url in relations:
            writer.writerow((f"FDC:{fdc_id}", "HAS_NUTRIENT", f"FDC-NUTRIENT:{nutrient_id}",
                             "" if amount is None else amount, unit, url, "usda_fdc", RELEASE,
                             "USDA Foundation Foods numeric record"))
    return {"foods": len(foods), "nutrients": len(nutrients), "edges": len(relations),
            "nodes_path": str(nodes_path), "edges_path": str(edges_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export USDA food-nutrient graph files")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    print(json.dumps(export_graph(args.data_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
