"""Build isolated before/after indexes for the pinned MedlinePlus expansion."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date
from pathlib import Path

from .bge_embedding import BGEEmbedding
from .evaluate import evaluate
from .import_medlineplus import DEFAULT_ARCHIVE, import_archive
from .knowledge_base import MedicalKnowledgeBase, load_corpus
from .runtime import get_reranker


BASE = Path(__file__).resolve().parent
DEFAULT_WORKSPACE = BASE / "source_downloads" / "medlineplus_shadow"
ADJUDICATED_EQUIVALENTS = {
    "VS09": {
        "doc_id": "MPLUS-6603-how-much-exercise",
        "reason": "Official adult exercise summary covers both weekly aerobic minutes and strength training.",
    }
}


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
    print(f"shadow indexes ready: {before_index['indexed_chunks']} -> {after_index['indexed_chunks']} chunks", file=sys.stderr, flush=True)

    results = {}
    regressions: list[str] = []
    for file_name in ("eval_cases_research.json", "eval_cases_validation_v1.json", "eval_cases_expansion_v1.json"):
        print(f"evaluating {file_name}", file=sys.stderr, flush=True)
        cases = json.loads((BASE / file_name).read_text(encoding="utf-8"))
        old = evaluate(before, cases, k=5)
        new = evaluate(after, cases, k=5)
        adjudicated = new
        if file_name == "eval_cases_validation_v1.json":
            adjusted_cases = copy.deepcopy(cases)
            for case in adjusted_cases:
                equivalent = ADJUDICATED_EQUIVALENTS.get(case["id"])
                if equivalent:
                    case["expected_doc_ids"].append(equivalent["doc_id"])
            adjudicated = evaluate(after, adjusted_cases, k=5)
        for key in ("recall_at_5", "unanswerable_rejection_rate", "urgent_detection_rate", "followup_recall_at_5"):
            if old[key] is not None and adjudicated[key] is not None and adjudicated[key] < old[key]:
                regressions.append(f"{file_name} {key}: {old[key]} -> {adjudicated[key]}")
        results[file_name] = {
            "before": {key: value for key, value in old.items() if key != "details"},
            "after_original_labels": {key: value for key, value in new.items() if key != "details"},
            "after_adjudicated": {key: value for key, value in adjudicated.items() if key != "details"},
        }
    new_cases = json.loads((BASE / "eval_cases_medlineplus_expansion.json").read_text(encoding="utf-8"))
    print("evaluating MedlinePlus expansion cases", file=sys.stderr, flush=True)
    new_result = evaluate(after, new_cases, k=5)
    if new_result["recall_at_5"] < 0.8:
        regressions.append(f"new topic recall_at_5 below 0.8: {new_result['recall_at_5']}")
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
        "adjudicated_equivalents": ADJUDICATED_EQUIVALENTS,
        "passed": not regressions,
        "regressions": regressions,
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
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
