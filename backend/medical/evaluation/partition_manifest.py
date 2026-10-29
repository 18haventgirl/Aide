"""Seal/audit source-labelled splits without running retrieval or generation.

These local integrity checks cannot prove an external blind evaluation, an
honest exposure ledger, or absence of semantic leakage. A seal is immutable;
changed labels, source snapshots, or checking code require a new version.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from ..audit_source_snapshot import audit_snapshot
from ..evaluate import QUERY_CONTRACT, validate_cases
from ..experiment import digest, validate_source_bindings
from ..knowledge_base import load_corpus
from ..source_origins import OriginResolver, validate_literal_references
from .partitioning import validate_partitions


ROOT = Path(__file__).resolve().parents[3]
MEDICAL = ROOT/"backend/medical"
CONTRACT = "evidence_partition_manifest_v1"
CODE_FILES = (
    "backend/medical/evaluation/partition_manifest.py", "backend/medical/evaluation/partitioning.py",
    "backend/medical/evaluation/metrics.py", "backend/medical/evaluate.py", "backend/medical/experiment.py",
    "backend/medical/audit_source_snapshot.py", "backend/medical/source_origins.py",
    "backend/medical/source_provenance.py", "backend/medical/knowledge_base.py", "backend/medical/schema.py",
)
LIMITATIONS = [
    "mechanical checks do not prove semantic independence or an external blind evaluation",
    "exposure history and authorship declarations are operator attestations, not access controls",
    "source matching is not clinical review, answer correctness, or permission to publish",
    "no retrieval, LLM generation, or model quality is measured by this audit",
    "parameter preregistration and consuming this seal in experiment execution remain separate steps",
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def confined(path, root):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("file must stay within the declared root")
    return path


def stored_path(relative, root):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("manifest paths must be relative")
    return confined(Path(root)/relative, root)


def code_binding():
    def git(*args):
        result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, timeout=10, check=True)
        return result.stdout.strip()
    tracked = set(git("ls-files", "--", *CODE_FILES).splitlines())
    return {"commit": git("rev-parse", "HEAD"),
            "tracked_changes": bool(git("status", "--porcelain", "--untracked-files=no")),
            "untracked_bound_files": sorted(set(CODE_FILES)-tracked),
            "files_sha256": {name: sha256(ROOT/name) for name in CODE_FILES}}


def case_file(path, data_root):
    path = confined(path, data_root)
    raw = path.read_bytes()
    cases = json.loads(raw)
    validate_cases(cases)
    return {"path": path.relative_to(Path(data_root).resolve()).as_posix(), "file_sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_json_sha256": digest(cases), "count": len(cases)}, cases


def source_binding(snapshot, snapshot_root, raw_root):
    snapshot = confined(snapshot, snapshot_root)
    audit = audit_snapshot(snapshot, raw_root)
    documents = load_corpus(snapshot/"corpus")
    origins = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((snapshot/"origins").glob("*.json"))}
    binding = {"path": snapshot.relative_to(Path(snapshot_root).resolve()).as_posix(),
               "manifest_file_sha256": sha256(snapshot/"snapshot_manifest.json"),
               **{key: audit[key] for key in ("corpus_sha256", "origins_sha256", "documents",
                                               "origin_verified_documents", "pending_origin_documents")}}
    return binding, documents, OriginResolver(documents, origins, raw_root)


def check_cases(partitions, exposures, documents, resolver, similarity_threshold):
    report = validate_partitions(partitions, documents, similarity_threshold=similarity_threshold,
                                 exposure_sets=exposures)
    if not report["valid"]:
        raise ValueError("partition leakage or metadata checks failed: "+json.dumps(report, ensure_ascii=False))
    for cases in partitions.values():
        validate_source_bindings(cases, documents)
        validate_literal_references(cases, resolver)
        for case in cases:
            if not isinstance(case.get("authorship"), str) or not case["authorship"].strip():
                raise ValueError("sealed cases require explicit authorship")
            if case.get("kind", "supported") in {"unanswerable", "urgent"}:
                if not isinstance(case.get("no_evidence_reason"), str) or not case["no_evidence_reason"].strip():
                    raise ValueError("cases without positive evidence require no_evidence_reason")
    return report


def seal_partitions(development, validation, *, exposure_paths, snapshot, output, data_root,
                    snapshot_root, raw_root, similarity_threshold=.85):
    """Create a new local seal. No overwrite, silent relabel, or model calls."""
    output = confined(output, data_root)
    if output.exists():
        raise FileExistsError("refusing to overwrite a sealed partition manifest")
    if not exposure_paths:
        raise ValueError("an explicit historical exposure registry is required")
    paths = {"development": development, "validation": validation}
    files, partitions, exposure_files, exposures = {}, {}, [], {}
    for split, path in paths.items():
        files[split], partitions[split] = case_file(path, data_root)
    for path in exposure_paths:
        binding, cases = case_file(path, data_root)
        if binding["path"] in exposures:
            raise ValueError("duplicate exposure file")
        exposures[binding["path"]] = cases
        exposure_files.append(binding)
    source, documents, resolver = source_binding(snapshot, snapshot_root, raw_root)
    report = check_cases(partitions, exposures, documents, resolver, similarity_threshold)
    manifest = {"schema_version": 1, "contract": CONTRACT, "metric_contract": "source-evidence-v1",
                "query_contract": QUERY_CONTRACT, "status": "sealed_local_not_external_blind",
                "created_at": datetime.now(timezone.utc).isoformat(), "partitions": files,
                "exposure_files": exposure_files, "source_snapshot": source,
                "similarity_threshold": similarity_threshold, "mechanical_checks": report,
                "code": code_binding(), "limitations": LIMITATIONS}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents concurrent writers from replacing a seal.
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    return manifest


def audit_partition_manifest(path, *, data_root, snapshot_root, raw_root):
    """Re-read every input and return a compact report; this performs no writes."""
    path = confined(path, data_root)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("contract") != CONTRACT or manifest.get("metric_contract") != "source-evidence-v1"
            or manifest.get("query_contract") != QUERY_CONTRACT
            or manifest.get("status") != "sealed_local_not_external_blind"):
        raise ValueError("unsupported partition seal contract")
    if set(manifest.get("partitions", {})) != {"development", "validation"} or not manifest.get("exposure_files"):
        raise ValueError("both partitions and an exposure registry are required")
    partitions, exposures = {}, {}
    for split, expected in manifest["partitions"].items():
        actual, cases = case_file(stored_path(expected["path"], data_root), data_root)
        if actual != expected:
            raise ValueError("sealed case file changed: "+split)
        partitions[split] = cases
    for expected in manifest["exposure_files"]:
        actual, cases = case_file(stored_path(expected["path"], data_root), data_root)
        if actual != expected or expected["path"] in exposures:
            raise ValueError("sealed exposure file changed or was duplicated")
        exposures[expected["path"]] = cases
    expected = manifest["source_snapshot"]
    source, documents, resolver = source_binding(stored_path(expected["path"], snapshot_root), snapshot_root, raw_root)
    if source != expected:
        raise ValueError("sealed source snapshot changed")
    # Commits containing only documentation may change; the implementation bytes must not.
    current_code = code_binding()
    if current_code["files_sha256"] != manifest["code"]["files_sha256"]:
        raise ValueError("partition checking implementation changed; a new seal version is required")
    report = check_cases(partitions, exposures, documents, resolver, manifest["similarity_threshold"])
    if report != manifest["mechanical_checks"]:
        raise ValueError("sealed mechanical-check result changed")
    return {"valid": True, "contract": CONTRACT, "manifest_file_sha256": sha256(path),
            "counts": {split: len(cases) for split, cases in partitions.items()},
            "source_snapshot": source, "mechanical_checks": report,
            "sealed_code": manifest["code"], "audit_code": current_code, "limitations": LIMITATIONS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seal", "audit"))
    parser.add_argument("--data-root", type=Path, default=MEDICAL)
    parser.add_argument("--snapshot-root", type=Path, default=ROOT/"medical-rag-data/datasets")
    parser.add_argument("--raw-root", type=Path, default=ROOT/"medical-rag-data/raw")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--development", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--exposed", type=Path, action="append", default=[])
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--similarity-threshold", type=float, default=.85)
    args = parser.parse_args()
    roots = {key: getattr(args, key) for key in ("data_root", "snapshot_root", "raw_root")}
    try:
        if args.command == "seal":
            if not all((args.development, args.validation, args.snapshot)):
                parser.error("seal requires --development, --validation and --snapshot")
            result = seal_partitions(args.development, args.validation, exposure_paths=args.exposed,
                                     snapshot=args.snapshot, output=args.manifest,
                                     similarity_threshold=args.similarity_threshold, **roots)
            result = {"sealed": True, "contract": result["contract"],
                      "counts": {k: v["count"] for k, v in result["partitions"].items()},
                      "limitations": LIMITATIONS}
        else:
            result = audit_partition_manifest(args.manifest, **roots)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"valid": False, "contract": CONTRACT, "error": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
