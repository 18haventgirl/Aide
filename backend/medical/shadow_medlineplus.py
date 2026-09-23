"""Build isolated before/after indexes for the pinned MedlinePlus expansion."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .bge_embedding import BGEEmbedding
from .evaluate import evaluate
from .import_medlineplus import DEFAULT_ARCHIVE, import_archive
from .knowledge_base import MedicalKnowledgeBase, load_corpus
from .runtime import get_reranker


BASE = Path(__file__).resolve().parent
DEFAULT_WORKSPACE = BASE / "source_downloads" / "medlineplus_shadow"


def _index(path: Path, documents: list, embedding, reranker):
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(path.resolve()),
        settings=Settings(anonymized_telemetry=False, allow_reset=True),
    )
    kb = MedicalKnowledgeBase(
        client, embedding, embedding.name(), research_mode=True,
        reranker=reranker, reranker_requested=reranker is not None,
    )
    return kb, kb.sync(documents)


def run(workspace: Path = DEFAULT_WORKSPACE, archive: Path = DEFAULT_ARCHIVE) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    baseline = load_corpus(BASE / "source_corpus")
    manifest = import_archive(archive, workspace / "expanded_documents", collected_at=date.today())
    expanded_by_id = {document.doc_id: document for document in baseline}
    expanded_by_id.update({document.doc_id: document for document in load_corpus(workspace / "expanded_documents")})
    expanded = list(expanded_by_id.values())
    embedding = BGEEmbedding()
    reranker = get_reranker()
    before, before_index = _index(workspace / "baseline_chroma", baseline, embedding, reranker)
    after, after_index = _index(workspace / "expanded_chroma", expanded, embedding, reranker)

    results = {}
    for file_name in ("eval_cases_research.json", "eval_cases_validation_v1.json", "eval_cases_expansion_v1.json"):
        cases = json.loads((BASE / file_name).read_text(encoding="utf-8"))
        old = evaluate(before, cases, k=5)
        new = evaluate(after, cases, k=5)
        for key in ("recall_at_5", "unanswerable_rejection_rate", "urgent_detection_rate", "followup_recall_at_5"):
            if old[key] is not None and new[key] is not None and new[key] < old[key]:
                raise ValueError(f"regression in {file_name} {key}: {old[key]} -> {new[key]}")
        results[file_name] = {
            "before": {key: value for key, value in old.items() if key != "details"},
            "after": {key: value for key, value in new.items() if key != "details"},
        }
    new_cases = json.loads((BASE / "eval_cases_medlineplus_expansion.json").read_text(encoding="utf-8"))
    new_result = evaluate(after, new_cases, k=5)
    results["eval_cases_medlineplus_expansion.json"] = {
        "after": {key: value for key, value in new_result.items() if key != "details"},
        "details": new_result["details"],
    }
    return {
        "baseline_documents": len(baseline),
        "expanded_documents": len(expanded),
        "medlineplus_manifest": manifest,
        "baseline_index": before_index,
        "expanded_index": after_index,
        "evaluations": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate MedlinePlus expansion in isolated Chroma indexes")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = run(args.workspace, args.archive)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
