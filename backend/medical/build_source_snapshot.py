"""Extend an audited Chinese source snapshot without changing previous versions.

Input bundles contain a MedicalDocument and its literal origin sidecar. An
origin-only update can complete provenance without reserializing the document.
This command never opens a serving index, a user database, or an LLM service.
"""
import argparse
from datetime import date
import json
from pathlib import Path

from .audit_source_snapshot import audit_snapshot
from .experiment import MEDICAL, ROOT, digest, repository_version
from .knowledge_base import load_corpus
from .schema import MedicalDocument
from .source_origins import verify_origin
from .source_pipeline import sha256
from .source_provenance import body_hash


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def build_snapshot(parent, output, *, bundles=(), origins=(), raw_root=None, as_of=None):
    root = ROOT.resolve()
    allowed = (root/"medical-rag-data/datasets").resolve()
    parent, output = Path(parent).resolve(), Path(output).resolve()
    raw_root = Path(raw_root) if raw_root is not None else root/"medical-rag-data/raw"
    as_of = as_of or date.today()
    if not parent.is_relative_to(allowed) or not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("source snapshots must stay inside the approved datasets root")
    if output.exists():
        raise FileExistsError("never overwrite a source snapshot")
    previous = audit_snapshot(parent, raw_root)
    parent_state = json.loads((parent/"snapshot_manifest.json").read_text(encoding="utf-8"))
    documents = {d.doc_id: d for d in load_corpus(parent/"corpus")}
    mappings = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (parent/"origins").glob("*.json")}
    changed, seen = {}, set()
    for bundle in bundles:
        doc = MedicalDocument.model_validate(bundle["document"])
        if doc.doc_id in seen:
            raise ValueError("duplicate source bundle ID")
        seen.add(doc.doc_id)
        if not doc.is_searchable(as_of, research_mode=True):
            raise ValueError("new source must be current checked Chinese research material")
        if (doc.reviewed_at > as_of or doc.source_collected_at > as_of or doc.source_published_at > as_of):
            raise ValueError("source dates cannot be in the future")
        prior = documents.get(doc.doc_id)
        if prior is not None:
            if doc.model_dump(mode="json") == prior.model_dump(mode="json"):
                raise ValueError("unchanged document should use an origin-only update")
            if doc.version <= prior.version:
                raise ValueError("changed parent document must increase its version")
        verify_origin(doc, bundle["origin"], raw_root)
        documents[doc.doc_id] = changed[doc.doc_id] = doc
        mappings[doc.doc_id] = bundle["origin"]
    for origin in origins:
        doc_id = origin["doc_id"]
        if doc_id in seen:
            raise ValueError("duplicate source origin update")
        seen.add(doc_id)
        if doc_id not in documents:
            raise ValueError("source origin update references an unknown document")
        if mappings.get(doc_id) == origin:
            raise ValueError("source origin update is unchanged")
        verify_origin(documents[doc_id], origin, raw_root)
        mappings[doc_id] = origin
    if not seen:
        raise ValueError("source snapshot needs at least one reviewed change")
    baseline = {d.doc_id: d for d in load_corpus(MEDICAL/"source_corpus")}
    changes = []
    for doc_id, old in baseline.items():
        new = documents[doc_id]
        if new.model_dump(mode="json") != old.model_dump(mode="json"):
            changes.append({"doc_id": doc_id, "from_version": old.version, "to_version": new.version,
                            "old_body_sha256": body_hash(old.body), "new_body_sha256": body_hash(new.body),
                            "reason": "versioned_source_snapshot_change"})
    added = sorted(set(documents)-set(baseline))
    state = {"schema_version": 2, "complete": False, "code": repository_version(),
             "build_date": as_of.isoformat(), "scope": "isolated_local_research_not_active_index",
             "baseline_corpus_sha256": parent_state["baseline_corpus_sha256"],
             "parent_snapshot": {"path": parent.relative_to(root).as_posix(),
                                 "manifest_sha256": sha256(parent/"snapshot_manifest.json"),
                                 "corpus_sha256": previous["corpus_sha256"],
                                 "origins_sha256": previous["origins_sha256"]},
             "documents": len(documents), "added_documents": len(added), "added_doc_ids": added,
             "changed_documents": sorted(changes, key=lambda row: row["doc_id"]),
             "origin_updates": sorted(seen), "origin_verified_documents": len(mappings),
             "origin_manifests_pending": sorted(set(documents)-set(mappings)),
             "corpus_sha256": digest([documents[k].model_dump(mode="json") for k in sorted(documents)]),
             "origins_sha256": digest(mappings)}
    output.mkdir(parents=True)
    target = output/"snapshot_manifest.json"
    _json(target, state)
    (output/"corpus").mkdir(); (output/"origins").mkdir()
    for doc_id, doc in documents.items():
        path = output/"corpus"/f"{doc_id}.json"
        if doc_id in changed:
            path.write_text(doc.model_dump_json(indent=2)+"\n", encoding="utf-8")
        else:
            path.write_bytes((parent/"corpus"/f"{doc_id}.json").read_bytes())
    for doc_id, origin in mappings.items():
        _json(output/"origins"/f"{doc_id}.json", origin)
    # A crash during audit must never leave a completed manifest on disk.
    state = {**state, "complete": True}
    report = audit_snapshot(output, raw_root, _candidate_state=state)
    temporary = output/"snapshot_manifest.complete.tmp"
    _json(temporary, state)
    temporary.replace(target)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, action="append", default=[])
    parser.add_argument("--origin", type=Path, action="append", default=[])
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    result = build_snapshot(args.parent, args.output,
                            bundles=[json.loads(p.read_text(encoding="utf-8")) for p in args.bundle],
                            origins=[json.loads(p.read_text(encoding="utf-8")) for p in args.origin], as_of=args.as_of)
    print(json.dumps({key: result[key] for key in ("complete", "documents", "unique_source_urls",
          "origin_verified_documents", "pending_origin_documents", "added_doc_ids")}, ensure_ascii=False))
