"""One deterministic evidence pack shared by the MCP tool and evaluation."""
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json

from .source_provenance import default_resolver

CONTRACT_VERSION = "medical_evidence_pack_v1"


@dataclass(frozen=True)
class EvidenceBudget:
    max_chunks: int = 5
    max_chunks_per_document: int = 2
    max_chars_per_chunk: int = 1600
    max_content_chars: int = 8000

    def __post_init__(self):
        if any(type(value) is not int for value in asdict(self).values()):
            raise ValueError("evidence budgets must be integers")
        if not 1 <= self.max_chunks <= 8 or not 1 <= self.max_chunks_per_document <= 8:
            raise ValueError("invalid evidence chunk budget")
        if self.max_chars_per_chunk < 1 or self.max_content_chars < 1:
            raise ValueError("invalid evidence content budget")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def build_evidence_pack(hits, budget=None, resolver=None):
    budget = budget or EvidenceBudget()
    rows, seen, counts = [], set(), Counter()
    omissions = Counter()
    consumed = 0
    for hit in hits:
        if hit.chunk_id in seen:
            omissions["duplicate_chunk"] += 1
            continue
        seen.add(hit.chunk_id)
        if len(rows) >= budget.max_chunks or consumed >= budget.max_content_chars:
            omissions["content_or_chunk_budget"] += 1
            continue
        if counts[hit.doc_id] >= budget.max_chunks_per_document:
            omissions["per_document_cap"] += 1
            continue
        text = hit.text[:min(budget.max_chars_per_chunk, budget.max_content_chars - consumed)]
        if not text.strip():
            omissions["empty_content"] += 1
            continue
        if resolver is None:
            resolver = default_resolver()
        provenance = resolver.resolve(hit, text)
        rows.append({
            "evidence_id": f"E{len(rows)+1}", "chunk_id": hit.chunk_id,
            "doc_id": hit.doc_id, "title": hit.title, "section_path": hit.section_path,
            "text": text, "source_url": hit.source_url, "source_org": hit.source_org,
            "usage_scope": hit.usage_scope, "status": hit.status,
            "reviewed_at": hit.reviewed_at.isoformat() if hit.reviewed_at else None,
            "relevance_score": round(hit.rerank_score, 4) if hit.rerank_score is not None else None,
            "source_mapping": provenance, "content_truncated": len(text) < len(hit.text),
        })
        consumed += len(text)
        counts[hit.doc_id] += 1
    payload = {"contract_version": CONTRACT_VERSION, "budget": asdict(budget), "hits": rows}
    byte_count = sum(len(row["text"].encode("utf-8")) for row in rows)
    return {**payload, "pack_sha256": canonical_hash(payload), "diagnostics": {
        "selected_chunks": len(rows), "distinct_documents": len(counts), "content_chars": consumed,
        "content_utf8_bytes": byte_count, "content_tokens_estimate": (byte_count + 2)//3,
        "token_estimate_method": "utf8_bytes_div3_not_provider_tokenizer",
        "truncated_chunks": sum(row["content_truncated"] for row in rows),
        "unmapped_chunks": sum(row["source_mapping"]["status"] == "unmapped" for row in rows),
        "omissions": dict(omissions),
    }}
