"""Import and retrieve reviewed public medical knowledge from Chroma."""

import hashlib
import json
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

from .chunking import chunk_document
from .schema import MedicalDocument, MedicalHit


COLLECTION_NAME = "aide_medical_public_bge_zh_v2"
RESEARCH_COLLECTION_NAME = "aide_medical_research_bge_zh_v2"
PREVIEW_COLLECTION_NAME = "aide_medical_preview_hash_v1"
INDEX_VERSION = "medical-zh-section-v2"
PREVIEW_INDEX_VERSION = "medical-zh-section-v1"


def load_corpus(directory: Path) -> list[MedicalDocument]:
    files = sorted(path for path in directory.glob("*.json") if not path.name.endswith("_manifest.json"))
    if not files:
        raise ValueError(f"no JSON documents found in {directory}")
    documents = [MedicalDocument.model_validate(json.loads(path.read_text(encoding="utf-8"))) for path in files]
    ids = [document.doc_id for document in documents]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate doc_id in corpus")
    return documents


class MedicalKnowledgeBase:
    def __init__(self, chroma_client: Any, embedding_function: Any, embedding_model: str,
                 preview: bool = False, research_mode: bool = False, reranker: Any = None,
                 reranker_requested: bool = False):
        self.preview = preview
        self.research_mode = research_mode and not preview
        self.max_distance = (float(os.getenv("MEDICAL_RESEARCH_MAX_DISTANCE", "0.50"))
                             if self.research_mode and embedding_model.startswith("BAAI/bge-small-zh-v1.5")
                             else None)
        self.use_lexical = self.max_distance is not None and os.getenv("MEDICAL_RESEARCH_USE_LEXICAL", "true").lower() == "true"
        self.embedding_function = embedding_function
        self.reranker = reranker
        self.reranker_requested = reranker_requested
        self._lexical_index = None
        self._source_by_id = None
        self._source_cache_at = 0.0
        self._search_state = threading.local()
        collection_name = (PREVIEW_COLLECTION_NAME if preview else
                           RESEARCH_COLLECTION_NAME if self.research_mode else COLLECTION_NAME)
        expected_metadata = {
            "embedding_model": embedding_model,
            "embedding_weight_sha256": getattr(embedding_function, "weight_sha256", "unversioned"),
            "index_version": PREVIEW_INDEX_VERSION if preview else INDEX_VERSION,
            "preview": preview,
            "research_mode": self.research_mode,
            "hnsw:space": "cosine",
        }
        self.collection = chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            metadata=expected_metadata,
        )
        metadata = self.collection.metadata or {}
        if any(metadata.get(key) != value for key, value in expected_metadata.items()):
            raise ValueError("medical index settings changed; create a new versioned collection")

    def _embed_documents(self, texts: list[str]):
        if hasattr(self.embedding_function, "embed_documents"):
            return self.embedding_function.embed_documents(texts)
        return self.embedding_function(texts)

    def _embed_queries(self, queries: list[str]):
        if hasattr(self.embedding_function, "embed_queries"):
            return self.embedding_function.embed_queries(queries)
        return self.embedding_function(queries)

    def sync(self, documents: list[MedicalDocument], today: date | None = None) -> dict[str, int]:
        """Treat the supplied corpus as authoritative; withdraw removed or expired docs."""
        if not documents:
            raise ValueError("refusing to sync an empty authoritative corpus")
        today = today or date.today()
        ids = [document.doc_id for document in documents]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate doc_id")

        wanted_ids: set[str] = set()
        indexed_documents = 0
        removed_count = 0
        for document in documents:
            old = self.collection.get(where={"doc_id": document.doc_id})
            old_ids = set(old["ids"])
            new_ids: set[str] = set()
            eligible = document.is_searchable(today, research_mode=self.research_mode) or (
                self.preview and document.status == "draft"
            )
            if eligible:
                chunks = chunk_document(document.body, document.title)
                if not chunks:
                    raise ValueError(f"reviewed document {document.doc_id} has no chunks")
                chunk_ids = []
                metadatas = []
                texts = []
                for chunk in chunks:
                    text = f"{document.title}\n{chunk.section_path}\n{chunk.text}"
                    chunk_id = hashlib.sha256(
                        f"{document.doc_id}:{document.version}:{chunk.section_path}:{chunk.index}:{chunk.text}".encode("utf-8")
                    ).hexdigest()[:32]
                    new_ids.add(chunk_id)
                    chunk_ids.append(chunk_id)
                    texts.append(text)
                    metadatas.append({
                        "doc_id": document.doc_id,
                        "version": document.version,
                        "title": document.title,
                        "topic": document.topic,
                        "audience": document.audience,
                        "section_path": chunk.section_path,
                        "chunk_index": chunk.index,
                        "source_org": document.source_org,
                        "source_url": str(document.source_url),
                        "source_sha256": document.source_sha256 or "",
                        "source_locator": document.source_locator or "",
                        "source_collected_at": document.source_collected_at.isoformat() if document.source_collected_at else "",
                        "source_version": document.source_version or "",
                        "usage_scope": document.usage_scope or "",
                        "withdrawn": document.withdrawn,
                        "source_published_at": document.source_published_at.isoformat(),
                        "reviewed_at": document.reviewed_at.isoformat() if document.reviewed_at else "",
                        "next_review_at": document.next_review_at.isoformat() if document.next_review_at else "",
                        "status": document.status,
                    })
                # Upsert first, then remove stale chunks for an updated document.
                self.collection.upsert(
                    ids=chunk_ids, documents=texts, metadatas=metadatas,
                    embeddings=self._embed_documents(texts),
                )
                wanted_ids.update(new_ids)
                indexed_documents += 1
            stale = list(old_ids - new_ids)
            if stale:
                self.collection.delete(ids=stale)
                removed_count += len(stale)

        # Delete documents removed from the authoritative corpus.
        all_ids = set(self.collection.get()["ids"])
        removed = list(all_ids - wanted_ids)
        if removed:
            self.collection.delete(ids=removed)
            removed_count += len(removed)
        self._lexical_index = None
        self._source_by_id = None
        self._source_cache_at = 0.0
        return {"indexed_documents": indexed_documents, "indexed_chunks": len(wanted_ids), "removed_chunks": removed_count}

    def search_metrics(self) -> dict[str, Any]:
        """Diagnostics for the most recent search in the current thread."""
        return dict(getattr(self._search_state, "metrics", {}))

    def _metadata_is_current(self, metadata: dict, today: date) -> bool:
        if self.preview:
            return True
        valid_status = ({"source_checked", "clinician_reviewed"} if self.research_mode
                        else {"clinician_reviewed"})
        return (metadata["status"] in valid_status
                and not metadata.get("withdrawn", False)
                and bool(metadata.get("next_review_at"))
                and date.fromisoformat(metadata["next_review_at"]) >= today)

    def _to_hit(self, candidate: dict) -> MedicalHit:
        metadata = candidate["metadata"]
        return MedicalHit(
            chunk_id=candidate["chunk_id"], doc_id=metadata["doc_id"],
            title=metadata["title"], section_path=metadata["section_path"],
            text=candidate["text"], source_org=metadata["source_org"],
            source_url=metadata["source_url"],
            source_locator=metadata.get("source_locator") or None,
            source_published_at=date.fromisoformat(metadata["source_published_at"]),
            source_version=metadata.get("source_version") or None,
            source_sha256=metadata.get("source_sha256") or None,
            status=metadata.get("status"),
            reviewed_at=(date.fromisoformat(metadata["reviewed_at"])
                         if metadata.get("reviewed_at") else None),
            next_review_at=(date.fromisoformat(metadata["next_review_at"])
                            if metadata.get("next_review_at") else None),
            distance=candidate.get("distance"), dense_rank=candidate.get("dense_rank"),
            lexical_rank=candidate.get("lexical_rank"),
            lexical_score=candidate.get("lexical_score"),
            fusion_score=candidate.get("fusion_score"),
            rerank_score=candidate.get("rerank_score"),
            retrieval_method=candidate.get("retrieval_method", "dense"),
        )

    def search(self, query: str, limit: int = 5, today: date | None = None) -> list[MedicalHit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        today = today or date.today()
        count = self.collection.count()
        if count == 0:
            self._search_state.metrics = {"candidate_count": 0, "selected_count": 0}
            return []
        started = time.perf_counter()
        dense_limit = min(count, int(os.getenv("MEDICAL_DENSE_CANDIDATES", "24")))
        result = self.collection.query(
            query_embeddings=self._embed_queries([query]),
            n_results=dense_limit,
            include=["documents", "metadatas", "distances"],
        )
        dense_ms = round((time.perf_counter() - started) * 1000, 1)

        candidates: dict[str, dict] = {}
        for rank, (chunk_id, text, metadata, distance) in enumerate(zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0],
            result["distances"][0]
        ), 1):
            if self._metadata_is_current(metadata, today):
                candidates[chunk_id] = {
                    "chunk_id": chunk_id, "text": text, "metadata": metadata,
                    "distance": distance, "dense_rank": rank,
                    "retrieval_method": "dense",
                }

        lexical_started = time.perf_counter()
        if self.use_lexical:
            from .lexical import LexicalIndex
            source = None
            cache_ttl = float(os.getenv("MEDICAL_LEXICAL_CACHE_TTL_SECONDS", "60"))
            cache_expired = time.monotonic() - self._source_cache_at >= cache_ttl
            if (self._lexical_index is None or self._source_by_id is None
                    or len(self._source_by_id) != count or cache_expired):
                source = self.collection.get(include=["documents", "metadatas"])
                self._lexical_index = LexicalIndex(source["ids"], source["documents"])
                self._source_by_id = {
                    chunk_id: (text, metadata) for chunk_id, text, metadata in
                    zip(source["ids"], source["documents"], source["metadatas"])
                }
                self._source_cache_at = time.monotonic()
            source_by_id = self._source_by_id
            lexical_limit = min(count, int(os.getenv("MEDICAL_LEXICAL_CANDIDATES", "24")))
            for rank, (chunk_id, score) in enumerate(self._lexical_index.ranked(query, lexical_limit), 1):
                text, metadata = source_by_id[chunk_id]
                if not self._metadata_is_current(metadata, today):
                    continue
                candidate = candidates.setdefault(chunk_id, {
                    "chunk_id": chunk_id, "text": text, "metadata": metadata,
                    "distance": None, "dense_rank": None,
                    "retrieval_method": "lexical",
                })
                candidate["lexical_rank"] = rank
                candidate["lexical_score"] = score
                candidate["retrieval_method"] = (
                    "hybrid" if candidate.get("dense_rank") else "lexical"
                )
        lexical_ms = round((time.perf_counter() - lexical_started) * 1000, 1)

        # Weighted reciprocal-rank fusion is used only to choose the small set
        # evaluated by the cross encoder.  It is not the final relevance score.
        rrf_k = 60.0
        for candidate in candidates.values():
            dense_rrf = (0.60 / (rrf_k + candidate["dense_rank"])
                         if candidate.get("dense_rank") else 0.0)
            lexical_rrf = (0.40 / (rrf_k + candidate["lexical_rank"])
                           if candidate.get("lexical_rank") else 0.0)
            candidate["fusion_score"] = dense_rrf + lexical_rrf
        pre_limit = min(len(candidates), int(os.getenv("MEDICAL_RERANK_CANDIDATES", "8")))
        # Reserve places for both retrievers. With weighted RRF alone, a
        # lexical-only exact match can never outrank a dense-only candidate.
        # Quotas keep those complementary candidates available to the cross encoder.
        dense_quota = min(5, pre_limit)
        lexical_quota = min(3, max(0, pre_limit - dense_quota))
        dense_ranked = sorted(
            (item for item in candidates.values() if item.get("dense_rank")),
            key=lambda item: item["dense_rank"],
        )
        lexical_ranked = sorted(
            (item for item in candidates.values() if item.get("lexical_rank")),
            key=lambda item: item["lexical_rank"],
        )
        selected_ids = {
            item["chunk_id"] for item in dense_ranked[:dense_quota] + lexical_ranked[:lexical_quota]
        }
        preselected = [item for item in candidates.values() if item["chunk_id"] in selected_ids]
        for item in sorted(candidates.values(), key=lambda row: row["fusion_score"], reverse=True):
            if len(preselected) >= pre_limit:
                break
            if item["chunk_id"] not in selected_ids:
                selected_ids.add(item["chunk_id"])
                preselected.append(item)
        ranked = preselected[:pre_limit]

        rerank_started = time.perf_counter()
        reranker_status = "unavailable" if self.reranker_requested and self.reranker is None else "disabled"
        if self.reranker is not None and ranked:
            try:
                scores = self.reranker.score(query, [item["text"] for item in ranked])
                if len(scores) != len(ranked):
                    raise ValueError("reranker returned an unexpected score count")
                for candidate, score in zip(ranked, scores):
                    candidate["rerank_score"] = score
                ranked.sort(key=lambda item: (item["rerank_score"], item["fusion_score"]), reverse=True)
                reranker_status = "applied"
            except Exception as error:
                # Retrieval remains available if the optional local model is
                # corrupt or cannot be loaded; diagnostics expose the fallback.
                reranker_status = f"fallback:{type(error).__name__}"
        rerank_ms = round((time.perf_counter() - rerank_started) * 1000, 1)

        accepted: list[dict] = []
        if reranker_status == "applied":
            best = ranked[0]["rerank_score"] if ranked else 0.0
            relative_floor = float(os.getenv("MEDICAL_RERANK_RELATIVE_FLOOR", "0.35"))
            absolute_floor = float(os.getenv("MEDICAL_RERANK_MIN_SCORE", "0.05"))
            floor = max(absolute_floor, best * relative_floor)
            accepted = [
                item for item in ranked
                if item["rerank_score"] >= floor
                or (item["rerank_score"] >= absolute_floor
                    and item.get("lexical_rank", 999) <= 2)
            ]
        else:
            for item in ranked:
                distance = item.get("distance")
                lexical_rescue = (item.get("lexical_rank", 999) <= 3
                                  and item.get("lexical_score", 0.0) >= 6.0
                                  and (distance is None or distance <= 0.60))
                if self.preview:
                    if distance is None or distance <= 1.4:
                        accepted.append(item)
                elif self.max_distance is None or (distance is not None and distance <= self.max_distance) or lexical_rescue:
                    accepted.append(item)

        # Keep enough context while preventing one long source from occupying
        # the entire model prompt.
        per_doc_limit = int(os.getenv("MEDICAL_MAX_CHUNKS_PER_DOCUMENT", "2"))
        doc_counts: dict[str, int] = {}
        selected: list[dict] = []
        for item in accepted:
            doc_id = item["metadata"]["doc_id"]
            if doc_counts.get(doc_id, 0) >= per_doc_limit:
                continue
            doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1
            selected.append(item)
            if len(selected) >= limit:
                break

        self._search_state.metrics = {
            "candidate_count": len(candidates), "rerank_candidate_count": len(ranked),
            "selected_count": len(selected), "reranker_status": reranker_status,
            "reranker_model": self.reranker.name() if self.reranker is not None else None,
            "top_rerank_score": (round(ranked[0]["rerank_score"], 6)
                                 if ranked and ranked[0].get("rerank_score") is not None else None),
            "dense_ms": dense_ms, "lexical_ms": lexical_ms, "rerank_ms": rerank_ms,
        }
        return [self._to_hit(item) for item in selected]
