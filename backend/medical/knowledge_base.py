"""Import and retrieve reviewed public medical knowledge from Chroma."""

import hashlib
import json
import os
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
                 preview: bool = False, research_mode: bool = False):
        self.preview = preview
        self.research_mode = research_mode and not preview
        self.max_distance = (float(os.getenv("MEDICAL_RESEARCH_MAX_DISTANCE", "0.50"))
                             if self.research_mode and embedding_model.startswith("BAAI/bge-small-zh-v1.5")
                             else None)
        self.use_lexical = self.max_distance is not None and os.getenv("MEDICAL_RESEARCH_USE_LEXICAL", "true").lower() == "true"
        self.embedding_function = embedding_function
        self._lexical_index = None
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
        return {"indexed_documents": indexed_documents, "indexed_chunks": len(wanted_ids), "removed_chunks": removed_count}

    def search(self, query: str, limit: int = 5, today: date | None = None) -> list[MedicalHit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        today = today or date.today()
        count = self.collection.count()
        if count == 0:
            return []
        result = self.collection.query(
            query_embeddings=self._embed_queries([query]),
            n_results=(min(count, max(limit * 10, 100))
                       if self.use_lexical else max(limit * 2, 10)),
            include=["documents", "metadatas", "distances"],
        )
        lexical_scores = None
        lexical_ranks: dict[int, int] = {}
        if self.use_lexical:
            from .lexical import LexicalIndex
            source = self.collection.get(include=["documents"])
            if self._lexical_index is None or set(self._lexical_index.ids) != set(source["ids"]):
                self._lexical_index = LexicalIndex(source["ids"], source["documents"])
            scores_by_id = self._lexical_index.scores(query)
            lexical_scores = [scores_by_id.get(chunk_id, 0.0) for chunk_id in result["ids"][0]]
            ranked = sorted(range(len(lexical_scores)), key=lambda i: lexical_scores[i], reverse=True)
            lexical_ranks = {index: rank for rank, index in enumerate(ranked, 1)}
        hits: list[MedicalHit] = []
        rescued_ids: set[str] = set()
        for index, (chunk_id, text, metadata, distance) in enumerate(zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        )):
            if not self.preview:
                valid_status = ({"source_checked", "clinician_reviewed"} if self.research_mode
                                else {"clinician_reviewed"})
                if (metadata["status"] not in valid_status or metadata.get("withdrawn", False)
                        or not metadata["next_review_at"]
                        or date.fromisoformat(metadata["next_review_at"]) < today):
                    continue
            # Offline preview embeddings use normalized vectors; this provisional
            # cutoff only prevents obviously unrelated preview answers.
            if self.preview and distance is not None and distance > 1.4:
                continue
            # Provisional research-only rejection gate. The cutoff is deliberately
            # configurable; it must be recalibrated on a larger independent set.
            if self.max_distance is not None and distance is not None and distance > self.max_distance:
                lexical_rescue = (self.use_lexical and distance <= 0.60 and lexical_scores[index] >= 6.0
                                  and lexical_ranks[index] <= 3)
                if not lexical_rescue:
                    continue
                rescued_ids.add(chunk_id)
            hits.append(MedicalHit(
                chunk_id=chunk_id,
                doc_id=metadata["doc_id"],
                title=metadata["title"],
                section_path=metadata["section_path"],
                text=text,
                source_org=metadata["source_org"],
                source_url=metadata["source_url"],
                source_locator=metadata.get("source_locator") or None,
                source_published_at=date.fromisoformat(metadata["source_published_at"]),
                source_version=metadata.get("source_version") or None,
                source_sha256=metadata.get("source_sha256") or None,
                status=metadata.get("status"),
                reviewed_at=date.fromisoformat(metadata["reviewed_at"]) if metadata["reviewed_at"] else None,
                next_review_at=date.fromisoformat(metadata["next_review_at"]) if metadata["next_review_at"] else None,
                distance=distance,
            ))
            if not self.use_lexical and len(hits) >= limit:
                break
        if self.use_lexical:
            # Preserve calibrated dense ordering; append strong lexical rescues.
            # Rank fusion promoted unrelated lexical matches above good dense hits.
            hits.sort(key=lambda hit: hit.chunk_id in rescued_ids)
        return hits[:limit]
