"""Fail-closed source and rights registry for medical data imports."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from urllib.parse import urlparse


REGISTRY_DIR = Path(__file__).resolve().parents[2] / "medical-rag-data" / "registry"
RIGHTS = ("commercial_use", "redistribution", "translation_or_adaptation", "rag_use", "model_training")
RIGHT_VALUES = {"yes", "no", "unknown"}
CLASSIFICATIONS = {"OPEN", "RESEARCH_ONLY", "NON_COMMERCIAL", "REGISTRATION_REQUIRED", "RESTRICTED", "UNKNOWN"}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "dataset_id" not in reader.fieldnames:
            raise ValueError(f"missing dataset_id column: {path}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def validate_registry(directory: Path = REGISTRY_DIR) -> dict[str, object]:
    datasets = _rows(directory / "datasets.csv")
    licenses = _rows(directory / "licenses.csv")
    errors: list[str] = []
    dataset_ids = [row["dataset_id"] for row in datasets]
    license_ids = [row["dataset_id"] for row in licenses]
    if len(dataset_ids) != len(set(dataset_ids)):
        errors.append("duplicate dataset_id in datasets.csv")
    if len(license_ids) != len(set(license_ids)):
        errors.append("duplicate dataset_id in licenses.csv")
    for missing in sorted(set(dataset_ids) - set(license_ids)):
        errors.append(f"missing license row: {missing}")
    for extra in sorted(set(license_ids) - set(dataset_ids)):
        errors.append(f"orphan license row: {extra}")
    for row in datasets:
        source_url = row.get("source_url", "")
        if urlparse(source_url).scheme != "https" or not urlparse(source_url).netloc:
            errors.append(f"{row['dataset_id']}: source_url must be HTTPS")
    for row in licenses:
        dataset_id = row["dataset_id"]
        classification = row.get("classification", "")
        if classification not in CLASSIFICATIONS:
            errors.append(f"{dataset_id}: invalid classification {classification}")
        for field in RIGHTS:
            if row.get(field) not in RIGHT_VALUES:
                errors.append(f"{dataset_id}: invalid {field}")
        if row.get("registration_required") not in RIGHT_VALUES:
            errors.append(f"{dataset_id}: invalid registration_required")
        if row.get("answer_eligible") not in {"yes", "no"}:
            errors.append(f"{dataset_id}: answer_eligible must be yes or no")
        if row.get("answer_eligible") == "yes" and (classification != "OPEN" or row.get("rag_use") != "yes"):
            errors.append(f"{dataset_id}: answer eligibility requires OPEN classification and confirmed RAG rights")
        license_url = row.get("license_url", "")
        if urlparse(license_url).scheme != "https" or not urlparse(license_url).netloc:
            errors.append(f"{dataset_id}: license_url must be HTTPS")
    return {
        "dataset_count": len(datasets),
        "verified_count": sum(row.get("investigation_status") == "verified" for row in datasets),
        "answer_eligible": sorted(row["dataset_id"] for row in licenses if row.get("answer_eligible") == "yes"),
        "errors": errors,
    }


def assert_answer_eligible(dataset_id: str, directory: Path = REGISTRY_DIR) -> None:
    report = validate_registry(directory)
    if report["errors"]:
        raise ValueError("invalid data registry: " + "; ".join(report["errors"]))
    if dataset_id not in report["answer_eligible"]:
        raise PermissionError(f"dataset {dataset_id} is not approved for answer evidence")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate medical source and rights registries")
    parser.add_argument("--directory", type=Path, default=REGISTRY_DIR)
    args = parser.parse_args()
    report = validate_registry(args.directory)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
