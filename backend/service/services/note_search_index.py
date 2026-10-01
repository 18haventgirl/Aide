"""Local note index v1. SQLite is authoritative; Chroma is a rebuildable cache.

SQLite triggers enqueue mutations in the same transaction as the note write.
Workers publish a revision only after its vectors are durable. Readers verify
the current note hash and ownership, including during failed indexing/deletes.
"""
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from sqlalchemy import text

from .note_chunks import chunks, revision

log = logging.getLogger(__name__)
_instances = {}
_instances_lock = threading.Lock()


def get_note_index(engine):
    if engine.dialect.name != "sqlite":
        return None
    key = str(engine.url)
    with _instances_lock:
        if key not in _instances:
            index = NoteSearchIndex(engine)
            index.install()
            index.start()
            _instances[key] = index
        return _instances[key]


class NoteSearchIndex:
    def __init__(self, engine, embedding=None, collection=None):
        self.engine = engine
        self.embedding = embedding
        self.collection = collection
        self.model_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="note-query")
        self.query_slot = threading.BoundedSemaphore(1)
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.ready = embedding is not None and collection is not None

    def install(self):
        with self.engine.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS note_index_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER NOT NULL, user_id INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0, error_type TEXT)"))
            c.execute(text("CREATE INDEX IF NOT EXISTS note_jobs_owner ON note_index_jobs(user_id,note_id)"))
            c.execute(text("CREATE TABLE IF NOT EXISTS note_index_state (note_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, revision TEXT NOT NULL)"))
            c.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS note_chunks_fts USING fts5(chunk_id UNINDEXED,note_id UNINDEXED,user_id UNINDEXED,revision UNINDEXED,body,tokens)"))
            for event, row in (("INSERT", "new"), ("UPDATE", "new"), ("DELETE", "old")):
                c.execute(text(f"CREATE TRIGGER IF NOT EXISTS note_index_{event.lower()} AFTER {event} ON notes BEGIN INSERT INTO note_index_jobs(note_id,user_id) VALUES ({row}.id,{row}.user_id); END"))
            c.execute(text("INSERT INTO note_index_jobs(note_id,user_id) SELECT n.id,n.user_id FROM notes n WHERE NOT EXISTS (SELECT 1 FROM note_index_state s WHERE s.note_id=n.id) AND NOT EXISTS (SELECT 1 FROM note_index_jobs j WHERE j.note_id=n.id)"))

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="note-index-worker").start()

    def _models(self):
        if self.ready:
            return
        from medical.resource_budget import require_available
        require_available(1536)
        from medical.bge_embedding import BGEEmbedding
        import chromadb
        from chromadb.config import Settings
        model = BGEEmbedding(batch_size=4)
        import torch
        torch.set_num_threads(2)
        model._load()
        # Separate physical storage prevents accidental model-space mixing.
        path = str(Path(__file__).resolve().parents[2] / "data" / "note_index_v1" / "chroma")
        client = chromadb.PersistentClient(path=path, settings=Settings(anonymized_telemetry=False))
        metadata = {"model": model.name(), "weights": model.weight_sha256, "hnsw:space": "cosine"}
        collection = client.get_or_create_collection("notes_bge_zh_v1", metadata=metadata)
        if collection.metadata != metadata:
            raise ValueError("note index model metadata mismatch")
        self.embedding, self.collection, self.ready = model, collection, True

    def process_one(self):
        now = time.time()
        with self.engine.begin() as c:
            job = c.execute(text("SELECT * FROM note_index_jobs WHERE attempts<5 AND available_at<=:now AND lease_until<=:now ORDER BY id LIMIT 1"), {"now": now}).mappings().first()
            if not job:
                return False
            claimed = c.execute(text("UPDATE note_index_jobs SET lease_until=:lease WHERE id=:id AND lease_until<=:now AND NOT EXISTS (SELECT 1 FROM note_index_jobs WHERE lease_until>:now)"), {"lease": now + 300, "id": job["id"], "now": now}).rowcount
        if not claimed:
            return False  # Another process owns the writer lease; do not busy-spin.
        try:
            with self.engine.connect() as c:
                row = c.execute(text("SELECT * FROM notes WHERE id=:id AND user_id=:user"), {"id": job["note_id"], "user": job["user_id"]}).mappings().first()
                note = dict(row) if row else None
            with self.model_lock:
                self._models()
                owner = {"$and": [{"note_id": str(job["note_id"])}, {"user_id": str(job["user_id"])}]}
                old_ids = set(self.collection.get(where=owner)['ids'])
                parts = chunks(note, self.embedding._tokenizer) if note else []
                if parts:
                    self.collection.upsert(ids=[p["id"] for p in parts], documents=[p["text"] for p in parts],
                        embeddings=self.embedding.embed_documents([p["text"] for p in parts]),
                        metadatas=[{"note_id": str(note["id"]), "user_id": str(note["user_id"]),
                                    "revision": p["revision"], "start": p["start"], "end": p["end"],
                                    "tag": note.get("tag") or "", "status": note.get("status") or ""} for p in parts])
            from medical.lexical import tokens
            with self.engine.begin() as c:
                latest = c.execute(text("SELECT * FROM notes WHERE id=:id AND user_id=:user"), {"id": job["note_id"], "user": job["user_id"]}).mappings().first()
                current = dict(latest) if latest else None
                if (current is None) != (note is None) or (current and revision(current) != revision(note)):
                    c.execute(text("DELETE FROM note_index_jobs WHERE id=:id"), {"id": job["id"]})
                    return True  # The write trigger has queued the newer version.
                c.execute(text("DELETE FROM note_chunks_fts WHERE note_id=:id AND user_id=:user"), {"id": job["note_id"], "user": job["user_id"]})
                for p in parts:
                    c.execute(text("INSERT INTO note_chunks_fts VALUES (:chunk,:note,:user,:rev,:body,:tokens)"),
                              {"chunk": p["id"], "note": note["id"], "user": note["user_id"], "rev": p["revision"], "body": p["text"], "tokens": " ".join(tokens(p["text"]))})
                if note:
                    c.execute(text("INSERT INTO note_index_state VALUES (:id,:user,:rev) ON CONFLICT(note_id) DO UPDATE SET user_id=excluded.user_id,revision=excluded.revision"), {"id": note["id"], "user": note["user_id"], "rev": revision(note)})
                else:
                    c.execute(text("DELETE FROM note_index_state WHERE note_id=:id AND user_id=:user"), {"id": job["note_id"], "user": job["user_id"]})
            # Delete only stale revisions, never newly inserted revisions from another worker.
            with self.model_lock:
                stale = list(old_ids - {p['id'] for p in parts})
                if stale:
                    self.collection.delete(ids=stale)
            with self.engine.begin() as c:
                c.execute(text("DELETE FROM note_index_jobs WHERE id=:id"), {"id": job["id"]})
        except Exception as exc:
            with self.engine.begin() as c:
                c.execute(text("UPDATE note_index_jobs SET attempts=attempts+1,lease_until=0,available_at=:next,error_type=:error WHERE id=:id"),
                          {"next": time.time() + min(300, 2 ** (job["attempts"] + 2)), "error": type(exc).__name__, "id": job["id"]})
            log.warning("Note indexing deferred: %s", type(exc).__name__)
        return True

    def _loop(self):
        while not self.stopped.is_set():
            try:
                with self.model_lock:
                    self._models()
                worked = self.process_one()
            except Exception as exc:
                log.warning("Note worker unavailable: %s", type(exc).__name__)
                worked = False
            self.wake.wait(0.2 if worked else 3)
            self.wake.clear()

    def _dense(self, query, user_id, tag, status):
        try:
            if not self.ready or not self.model_lock.acquire(blocking=False):
                return []
            try:
                filters = [{"user_id": str(user_id)}]
                if tag: filters.append({"tag": tag})
                if status: filters.append({"status": status})
                where = {"$and": filters} if len(filters)>1 else filters[0]
                data = self.collection.query(query_embeddings=self.embedding.embed_queries([query]), where=where,
                    n_results=30, include=["metadatas", "documents", "distances"])
                floor = float(os.getenv("NOTE_BGE_MAX_DISTANCE", "0.55"))
                return [(m, body) for m, body, distance in zip(data['metadatas'][0], data['documents'][0], data['distances'][0]) if distance <= floor]
            finally:
                self.model_lock.release()
        finally:
            self.query_slot.release()

    def search(self, user_id, query, limit=20, tag=None, status=None):
        from medical.lexical import tokens
        started = time.monotonic()
        query = query.strip()[:500]
        if not query:
            return []
        params = {"user": user_id, "limit": limit}
        filters = "user_id=:user"
        for name, value in (("tag", tag), ("status", status)):
            if value:
                filters += f" AND {name}=:{name}"
                params[name] = value
        # Exact matches always use current SQLite, including unsynchronized notes.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.engine.connect() as c:
            exact = c.execute(text(f"SELECT * FROM notes WHERE {filters} AND (title LIKE :q ESCAPE '\\' OR content LIKE :q ESCAPE '\\' OR tag LIKE :q ESCAPE '\\') ORDER BY last_updated DESC LIMIT :limit"), {**params, "q": "%"+escaped+"%"}).mappings().all()
        candidates = {}
        for row in exact:
            note = dict(row)
            body = note.get('content') or note['title']
            position = max(0, body.lower().find(query.lower()) - 60)
            candidates[note['id']] = {"revision": revision(note), "score": 1.0, "snippet": body[position:position+300]}
        terms = list(dict.fromkeys(tokens(query)))
        if terms:
            match = " OR ".join('"'+t.replace('"','""')+'"' for t in terms[:16])
            with self.engine.connect() as c:
                rows = c.execute(text("SELECT f.note_id,f.revision,f.body,f.tokens FROM note_chunks_fts f JOIN notes n ON n.id=f.note_id AND n.user_id=f.user_id WHERE note_chunks_fts MATCH :match AND f.user_id=:user" + (" AND n.tag=:tag" if tag else "") + (" AND n.status=:status" if status else "") + " ORDER BY bm25(note_chunks_fts) LIMIT 30"), {**params, "match": match}).mappings().all()
            query_terms = set(terms)
            for rank, row in enumerate(rows, 1):
                # OR retrieves candidates, not evidence that a note answers a query.
                # Require at least half the distinct non-stop query terms in this
                # chunk. Exact SQLite hits and independent dense hits bypass this
                # lexical-only gate, preserving literal and paraphrase searches.
                if len(query_terms.intersection(row['tokens'].split())) * 2 < len(query_terms):
                    continue
                item = candidates.setdefault(int(row['note_id']), {"revision": row['revision'], "score": 0, "snippet": row['body']})
                item['score'] = max(item['score'], 1/(60+rank))
        dense = []
        dense_status = 'disabled' if os.getenv('NOTE_DENSE_SEARCH', 'true').lower() != 'true' else 'not_ready'
        if dense_status != 'disabled' and self.ready and self.query_slot.acquire(blocking=False):
            future = self.pool.submit(self._dense, query, user_id, tag, status)
            try:
                dense = future.result(timeout=1.2)
                dense_status = 'completed'
            except TimeoutError:
                dense_status = 'timeout'  # One bounded in-flight query, never an unbounded queue.
            except Exception as exc:
                dense_status = 'error'
                log.warning("Note dense fallback: %s", type(exc).__name__)
        elif dense_status != 'disabled' and self.ready:
            dense_status = 'busy'
        seen = set()
        for rank, (meta, body) in enumerate(dense, 1):
            nid = int(meta['note_id'])
            if nid in seen: continue
            seen.add(nid)
            item = candidates.setdefault(nid, {"revision": meta['revision'], "score": 0, "snippet": body})
            if item['revision'] == meta['revision']:
                item['score'] += 1/(60+rank)
        output = []
        with self.engine.connect() as c:
            for nid, item in sorted(candidates.items(), key=lambda x:x[1]['score'], reverse=True):
                row = c.execute(text(f"SELECT * FROM notes WHERE {filters} AND id=:id"), {**params, "id": nid}).mappings().first()
                if row and revision(dict(row)) == item['revision']:
                    output.append({**dict(row), "snippet": item['snippet'][:300], "score": item['score'], "search_type": "local_bge_hybrid" if dense else "local_keyword"})
                if len(output) >= limit: break
        log.info('Note search: dense=%s dense_candidates=%d results=%d elapsed_ms=%.1f',
                 dense_status, len(dense), len(output), (time.monotonic()-started)*1000)
        return output
