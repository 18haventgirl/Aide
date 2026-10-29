"""Audit an isolated corpus and its literal-source sidecars without ML models."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .experiment import MEDICAL, ROOT, digest, repository_version
from .knowledge_base import load_corpus
from .source_origins import OriginResolver
from .source_pipeline import DOWNLOADS, sha256
from .source_provenance import body_hash


def original_asset_path(asset, raw_root):
    """Resolve only explicitly approved roots; legacy assets use downloads."""
    roots = {"downloads": DOWNLOADS.resolve(), "raw": Path(raw_root).resolve()}
    label = asset.get("root", "downloads")
    if label not in roots:
        raise ValueError("unknown original source asset root")
    relative = Path(asset["file"])
    path = (roots[label]/relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(roots[label]):
        raise ValueError("original source asset must stay within its approved root")
    return path


def audit_snapshot(snapshot, raw_root=ROOT/"medical-rag-data/raw", *, _seen=None, _candidate_state=None):
    snapshot = Path(snapshot).resolve()
    seen = set() if _seen is None else set(_seen)
    if snapshot in seen or len(seen) >= 32:
        raise ValueError("invalid source snapshot ancestry")
    seen.add(snapshot)
    state = (_candidate_state if _candidate_state is not None else
             json.loads((snapshot/"snapshot_manifest.json").read_text(encoding="utf-8")))
    schema = state.get("schema_version", 1)
    if type(schema) is not int or schema not in {1, 2}:
        raise ValueError("unsupported source snapshot schema")
    if schema == 2 and (not isinstance(state.get("parent_snapshot"), dict)
                        or not isinstance(state.get("origin_updates"), list)
                        or not isinstance(state.get("added_doc_ids"), list)):
        raise ValueError("version 2 snapshot requires ancestry and update declarations")
    if schema == 1 and any(key in state for key in ("parent_snapshot", "origin_updates", "added_doc_ids")):
        raise ValueError("ancestry declarations require version 2 snapshot")
    if state.get("complete") is not True:
        raise ValueError("source snapshot is incomplete")
    documents = load_corpus(snapshot/"corpus")
    corpus_hash = digest([d.model_dump(mode="json") for d in documents])
    if state["corpus_sha256"] != corpus_hash or state["documents"] != len(documents):
        raise ValueError("source snapshot corpus differs")
    manifests = {}
    for path in sorted((snapshot/"origins").glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["doc_id"] in manifests or path.stem != value["doc_id"]:
            raise ValueError("origin filename/ID is duplicated or inconsistent")
        manifests[value["doc_id"]] = value
    if state["origins_sha256"] != digest(manifests):
        raise ValueError("source origin sidecars differ")
    resolver = OriginResolver(documents, manifests, raw_root)
    pending = sorted(set(resolver.documents)-set(manifests))
    if state["origin_manifests_pending"] != pending or state["origin_verified_documents"] != len(manifests):
        raise ValueError("origin coverage declaration differs")
    # Verify underlying PDF/HTML bytes separately from the derived text captures.
    original_assets = {}
    for origin in manifests.values():
        for key in ("source_asset", "cross_check_asset"):
            asset = origin["capture"].get(key)
            if not asset: continue
            path = original_asset_path(asset, raw_root)
            if sha256(path) != asset["sha256"]:
                raise ValueError("underlying original source asset differs")
            name = asset["file"] if asset.get("root", "downloads") == "downloads" else f"raw:{asset['file']}"
            if name in original_assets and original_assets[name] != asset["sha256"]:
                raise ValueError("conflicting original source asset declarations")
            original_assets[name] = asset["sha256"]
    baseline = load_corpus(MEDICAL/"source_corpus")
    if state["baseline_corpus_sha256"] != digest([d.model_dump(mode="json") for d in baseline]):
        raise ValueError("historical baseline changed")
    by_id = {d.doc_id: d for d in baseline}
    current_ids = {d.doc_id for d in documents}
    if not set(by_id).issubset(current_ids):
        raise ValueError("new snapshot removed historical documents")
    added = sorted(current_ids-set(by_id))
    declared_added = state.get("added_doc_ids", [state.get("added_doc_id")])
    if (state["added_documents"] != len(added) or added != declared_added
            or ("added_doc_id" in state and declared_added != [state["added_doc_id"]])):
        raise ValueError("added document declaration differs")
    changes = []
    unchanged_files = 0
    for doc in documents:
        if doc.doc_id not in by_id: continue
        if doc.model_dump(mode="json") != by_id[doc.doc_id].model_dump(mode="json"):
            if doc.version <= by_id[doc.doc_id].version:
                raise ValueError("changed document must increase its version")
            changes.append(doc.doc_id)
        elif (snapshot/"corpus"/f"{doc.doc_id}.json").read_bytes() == (MEDICAL/"source_corpus"/f"{doc.doc_id}.json").read_bytes():
            unchanged_files += 1
        else:
            raise ValueError("an unchanged historical document was reserialized")
    if sorted(changes) != sorted(row["doc_id"] for row in state["changed_documents"]):
        raise ValueError("document version change declaration differs")
    for change in state["changed_documents"]:
        old = by_id[change["doc_id"]]
        new = resolver.documents[change["doc_id"]]
        if (change["from_version"] != old.version or change["to_version"] != new.version
                or change["old_body_sha256"] != body_hash(old.body) or change["new_body_sha256"] != body_hash(new.body)):
            raise ValueError("document change body/version declaration differs")
    parent_summary = None
    if "parent_snapshot" in state:
        anchor = state["parent_snapshot"]
        relative = Path(anchor["path"])
        parent = (ROOT/relative).resolve()
        if relative.is_absolute() or not parent.is_relative_to((ROOT/"medical-rag-data/datasets").resolve()):
            raise ValueError("parent snapshot must stay inside the approved datasets root")
        if sha256(parent/"snapshot_manifest.json") != anchor["manifest_sha256"]:
            raise ValueError("parent snapshot manifest differs")
        parent_summary = audit_snapshot(parent, raw_root, _seen=seen)
        if any(anchor[field] != parent_summary[field] for field in ("corpus_sha256", "origins_sha256")):
            raise ValueError("parent snapshot content binding differs")
        parent_documents = {d.doc_id: d for d in load_corpus(parent/"corpus")}
        if not set(parent_documents).issubset(current_ids):
            raise ValueError("new snapshot removed parent documents")
        for doc_id, old in parent_documents.items():
            new = resolver.documents[doc_id]
            if old.model_dump(mode="json") != new.model_dump(mode="json") and new.version <= old.version:
                raise ValueError("changed parent document must increase its version")
        parent_origins = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (parent/"origins").glob("*.json")}
        if not set(parent_origins).issubset(manifests):
            raise ValueError("new snapshot removed verified parent origins")
        updated_origins = sorted(k for k, v in manifests.items() if parent_origins.get(k) != v)
        if state.get("origin_updates") != updated_origins:
            raise ValueError("source origin update declaration differs")
    kinds = Counter(part["kind"] for origin in manifests.values() for part in origin["segments"])
    rows = []
    for doc in documents:
        origin = manifests.get(doc.doc_id)
        rows.append({"doc_id": doc.doc_id, "version": doc.version,
                     "body_sha256": body_hash(doc.body),
                     "origin_verified": origin is not None,
                     "capture_path": origin["capture"]["path"] if origin else None,
                     "capture_sha256": origin["capture"]["sha256"] if origin else None,
                     "origin_sha256": digest(origin) if origin else None})
    return {"schema_version": 1, "complete": True, "contract": "source_origin_v1", "analysis_code": repository_version(),
            "snapshot": snapshot.relative_to(ROOT).as_posix(), "build_code": state["code"],
            "corpus_sha256": corpus_hash, "origins_sha256": digest(manifests),
            "documents": len(documents), "unique_source_urls": len({str(d.source_url) for d in documents}),
            "origin_verified_documents": len(manifests), "pending_origin_documents": pending,
            "literal_parts": kinds["source_text"]+kinds["source_heading"], "part_kinds": dict(kinds),
            "unchanged_historical_files": unchanged_files, "changed_documents": state["changed_documents"],
            "added_doc_ids": added, "parent_snapshot": state.get("parent_snapshot"),
            "original_assets_sha256": original_assets, "documents_audit": rows,
            "limitations": ["canonical capture matching is not clinical review or permission to publish",
                "derived PDF/HTML captures include declared extraction normalization",
                "sleep capture is browser-rendered paragraph text, not an original HTTP response",
                "literal range verification does not establish audience or semantic sufficiency",
                "new snapshot is isolated; active retrieval and historical evaluation reports are unchanged"],
            "serving_index_switched": False, "release_ready": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_snapshot(args.snapshot)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({key: report[key] for key in ("complete", "documents", "unique_source_urls", "origin_verified_documents", "pending_origin_documents", "unchanged_historical_files")}, ensure_ascii=False))
