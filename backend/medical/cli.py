"""Manage and inspect the public medical knowledge index.

Run from backend: python -m medical.cli validate|sync|search ...
"""

import argparse
import json
from pathlib import Path

from .knowledge_base import MedicalKnowledgeBase, load_corpus
from .runtime import get_knowledge_base


DEFAULT_CORPUS = Path(__file__).resolve().parent / "corpus"


def _knowledge_base(preview: bool = False, research: bool = False) -> MedicalKnowledgeBase:
    return get_knowledge_base(preview, True if research else None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Curated medical knowledge index")
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate", help="validate source documents without connecting to Chroma")
    validate.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    sync = subcommands.add_parser("sync", help="index only reviewed, unexpired documents")
    sync.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    sync.add_argument("--preview", action="store_true", help="index drafts into a separate development collection")
    sync.add_argument("--research", action="store_true", help="index source-checked research documents (development only)")
    search = subcommands.add_parser("search", help="inspect retrieved source chunks")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--preview", action="store_true")
    search.add_argument("--research", action="store_true")
    args = parser.parse_args()

    if args.command == "validate":
        documents = load_corpus(args.corpus)
        print(json.dumps({
            "documents": len(documents),
            "source_checked": sum(doc.status == "source_checked" for doc in documents),
            "clinician_reviewed": sum(doc.status == "clinician_reviewed" for doc in documents),
            "collected": sum(doc.status == "collected" for doc in documents),
            "draft": sum(doc.status == "draft" for doc in documents),
            "retired": sum(doc.status == "retired" for doc in documents),
        }, ensure_ascii=False))
        return
    if args.preview and args.research:
        parser.error("--preview and --research cannot be combined")
    kb = _knowledge_base(preview=args.preview, research=args.research)
    if args.command == "sync":
        print(json.dumps(kb.sync(load_corpus(args.corpus)), ensure_ascii=False))
    else:
        print(json.dumps([hit.model_dump(mode="json") for hit in kb.search(args.query, args.limit)], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
