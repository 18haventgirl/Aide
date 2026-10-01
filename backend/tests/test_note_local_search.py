import tempfile
import unittest
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine, text
from service.services.note_chunks import chunks, revision
from service.services.note_search_index import NoteSearchIndex


class Tokenizer:
    def encode(self, text, **kwargs): return list(text)


class Embedding:
    _tokenizer = Tokenizer()
    def embed_documents(self, texts): return [[1.0, 0.0] for _ in texts]
    def embed_queries(self, texts): return [[1.0, 0.0] for _ in texts]


class Collection:
    def __init__(self): self.rows = {}; self.fail = False
    def upsert(self, ids, documents, embeddings, metadatas):
        if self.fail: raise RuntimeError("offline")
        self.rows.update({i:(d,m) for i,d,m in zip(ids,documents,metadatas)})
    def get(self, where):
        return {'ids':[key for key,(_,m) in self.rows.items() if all(m[k]==v for cl in where['$and'] for k,v in cl.items())]}
    def delete(self, ids):
        for key in ids: self.rows.pop(key,None)
    def query(self, **kwargs):
        clauses = kwargs['where'].get('$and', [kwargs['where']])
        rows = [(d,m) for d,m in self.rows.values() if all(m[k]==v for cl in clauses for k,v in cl.items())]
        return {'documents': [[d for d,m in rows]], 'metadatas': [[m for d,m in rows]], 'distances': [[0.1]*len(rows)]}


class NoteIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///'+str(Path(self.tmp.name)/'test.db'))
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE notes(id INTEGER PRIMARY KEY,user_id INTEGER,title TEXT,content TEXT,tag TEXT,status TEXT,last_updated TEXT)'))
        self.collection = Collection()
        self.index = NoteSearchIndex(self.engine, Embedding(), self.collection)
        self.index.install()

    def tearDown(self):
        self.index.pool.shutdown(wait=True)
        self.engine.dispose()
        self.tmp.cleanup()

    def add(self, nid=1, user=1, body='报销需要发票和审批单', title='出差记录', tag='work'):
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO notes VALUES(:id,:user,:title,:body,:tag,'draft','2026-09-29')"),dict(id=nid,user=user,title=title,body=body,tag=tag))

    def test_atomic_outbox_rollback(self):
        with self.engine.connect() as c:
            t=c.begin()
            c.execute(text("INSERT INTO notes VALUES(1,1,'标题','正文','','draft','')"))
            t.rollback()
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT COUNT(*) FROM note_index_jobs')).scalar(),0)

    def test_current_data_ownership_filters_and_delete(self):
        self.add(); self.add(2,2); self.add(3,1,tag='private')
        while self.index.process_one(): pass
        hits=self.index.search(1,'报销',tag='work')
        self.assertEqual([h['id'] for h in hits],[1])
        with self.engine.begin() as c: c.execute(text('DELETE FROM notes WHERE id=1'))
        self.assertEqual(self.index.search(1,'报销',tag='work'),[])
        self.assertTrue(self.index.process_one())
        self.assertFalse(any(m['note_id']=='1' for _,m in self.collection.rows.values()))

    def test_failed_update_never_returns_old_revision(self):
        self.add(); self.index.process_one()
        with self.engine.begin() as c: c.execute(text("UPDATE notes SET content='新的会议议程' WHERE id=1"))
        self.collection.fail=True
        self.index.process_one()
        self.assertEqual(self.index.search(1,'报销'),[])
        self.assertEqual(self.index.search(1,'会议')[0]['content'],'新的会议议程')

    def test_title_only_and_duplicate_chunks(self):
        self.add(body='',title='患者回访')
        self.index.process_one()
        self.assertEqual(len(self.index.search(1,'患者')),1)

    def test_keyword_search_while_model_unavailable(self):
        self.add()
        self.index.ready=False
        self.assertEqual(self.index.search(1,'发票')[0]['id'],1)
        self.assertEqual(self.index.search(2,'发票'),[])

    def test_slow_dense_is_bounded_and_does_not_queue(self):
        self.add(); self.index.process_one()
        release = threading.Event()
        calls = []
        def slow_query(texts):
            calls.append(texts)
            release.wait(5)
            return [[1.0, 0.0]]
        self.index.embedding.embed_queries = slow_query
        try:
            started = time.monotonic()
            self.assertEqual(self.index.search(1, '发票')[0]['id'], 1)
            self.assertLess(time.monotonic() - started, 2.5)
            started = time.monotonic()
            self.assertEqual(self.index.search(1, '发票')[0]['id'], 1)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(len(calls), 1)
        finally:
            release.set()

    def test_active_writer_lease_does_not_spin(self):
        self.add(); self.add(2)
        with self.engine.begin() as c:
            c.execute(text('UPDATE note_index_jobs SET lease_until=:until WHERE note_id=1'), {'until':time.time()+300})
        self.assertFalse(self.index.process_one())
        self.assertEqual(self.collection.rows, {})

    def test_literal_sql_wildcard_not_match_all(self):
        self.add()
        self.index.ready=False
        self.assertEqual(self.index.search(1,'%'),[])

    def test_fts_shared_word_is_not_enough_for_unrelated_intent(self):
        self.add(body='游泳馆十月维修闭馆，会员卡延期五天', title='场馆通知')
        self.index.process_one()
        self.index.ready=False
        self.assertEqual(self.index.search(1, '打印机卡纸维修手册'), [])
        self.assertEqual(self.index.search(1, '游泳馆 维修')[0]['id'], 1)

    def test_lexical_gate_keeps_literal_and_independent_dense_hits(self):
        self.add(body='小王说自行车链条锈蚀的化学机理很复杂', title='随笔')
        self.index.process_one()
        self.index.ready=False
        self.assertEqual(self.index.search(1, '自行车链条锈蚀的化学机理')[0]['id'], 1)
        self.assertEqual(self.index.search(1, '金属氧化原理'), [])
        self.index.ready=True
        # The fake dense collection supplies a semantic match independently of FTS.
        self.assertEqual(self.index.search(1, '金属氧化原理')[0]['id'], 1)

    def test_fts_repeated_query_terms_do_not_inflate_coverage(self):
        self.add(body='游泳馆维修闭馆', title='场馆通知')
        self.index.process_one()
        self.index.ready=False
        self.assertEqual(self.index.search(1, '维修 维修 维修 打印机 卡纸 手册'), [])

    def test_bootstrap_idempotent(self):
        self.add(); self.index.install(); self.index.install()
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT COUNT(*) FROM note_index_jobs')).scalar(),1)

    def test_update_replaces_chunks_and_publishes_latest(self):
        self.add(); self.index.process_one()
        old=set(self.collection.rows)
        with self.engine.begin() as c: c.execute(text("UPDATE notes SET content='新的会议议程' WHERE id=1"))
        self.index.process_one()
        self.assertFalse(old & set(self.collection.rows))
        self.assertEqual(self.index.search(1,'会议')[0]['content'],'新的会议议程')

    def test_edit_during_embedding_does_not_publish_stale_revision(self):
        self.add(); self.index.process_one()
        with self.engine.begin() as c:
            c.execute(text("UPDATE notes SET content='中间版本' WHERE id=1"))
        entered, release = threading.Event(), threading.Event()
        original = self.index.embedding.embed_documents
        def delayed(texts):
            entered.set()
            if not release.wait(5): raise RuntimeError('test timeout')
            return original(texts)
        self.index.embedding.embed_documents = delayed
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(self.index.process_one)
            try:
                self.assertTrue(entered.wait(3))
                with self.engine.begin() as c:
                    c.execute(text("UPDATE notes SET content='最终版本会议' WHERE id=1"))
                self.assertEqual(self.index.search(1, '报销'), [])
                self.assertEqual(self.index.search(1, '最终版本')[0]['content'], '最终版本会议')
            finally:
                release.set()
            self.assertTrue(future.result(timeout=3))
        self.index.embedding.embed_documents = original
        while self.index.process_one(): pass
        with self.engine.connect() as c:
            note = dict(c.execute(text('SELECT * FROM notes WHERE id=1')).mappings().one())
            self.assertEqual(c.execute(text('SELECT revision FROM note_index_state WHERE note_id=1')).scalar(), revision(note))
        self.assertTrue(all(m['revision']==revision(note) for _,m in self.collection.rows.values()))

    def test_cleanup_failure_remains_retryable_after_publish(self):
        self.add(); self.index.process_one()
        old = set(self.collection.rows)
        with self.engine.begin() as c: c.execute(text("UPDATE notes SET content='会议议程' WHERE id=1"))
        original = self.collection.delete
        self.collection.delete = lambda **kwargs: (_ for _ in ()).throw(OSError('injected cleanup failure'))
        self.index.process_one()
        self.assertEqual(self.index.search(1, '会议')[0]['content'], '会议议程')
        with self.engine.begin() as c:
            self.assertEqual(c.execute(text('SELECT attempts FROM note_index_jobs')).scalar(), 1)
            c.execute(text('UPDATE note_index_jobs SET available_at=0'))
        self.collection.delete = original
        self.index.process_one()
        self.assertFalse(old & set(self.collection.rows))

    def test_crash_after_vector_write_recovers_expired_lease(self):
        self.add()
        original = self.collection.upsert
        def interrupt(**kwargs):
            original(**kwargs)
            raise SystemExit('injected process interruption')
        self.collection.upsert = interrupt
        with self.assertRaises(SystemExit): self.index.process_one()
        saved_ids = set(self.collection.rows)
        with self.engine.begin() as c:
            self.assertEqual(c.execute(text('SELECT COUNT(*) FROM note_index_state')).scalar(), 0)
            self.assertGreater(c.execute(text('SELECT lease_until FROM note_index_jobs')).scalar(), time.time())
            c.execute(text('UPDATE note_index_jobs SET lease_until=0'))  # Simulate lease expiry.
        self.collection.upsert = original
        recovered = NoteSearchIndex(self.engine, Embedding(), self.collection)
        try:
            recovered.install()
            self.assertTrue(recovered.process_one())
            self.assertFalse(recovered.process_one())
            self.assertEqual(set(self.collection.rows), saved_ids)
            self.assertEqual(recovered.search(1, '发票')[0]['id'], 1)
        finally:
            recovered.pool.shutdown(wait=True)

    def test_short_code_block_kept_together(self):
        code='```python\n'+('print(123)\n'*12)+'```\n'
        note=dict(id=1,user_id=1,title='代码',content='介绍。'*95+'\n'+code+'结束。')
        pieces=chunks(note,Tokenizer())
        self.assertTrue(any(code in p['text'] for p in pieces))

    def test_offsets_cover_body_and_token_limit(self):
        body=('第一部分要完整保存。\n'*80)+'第二部分是最后的关键事实。'
        note=dict(id=1,user_id=1,title='标题',content=body)
        pieces=chunks(note,Tokenizer())
        covered=set()
        for p in pieces:
            self.assertLessEqual(len(p['text']),480)
            covered.update(range(p['start'],p['end']))
            self.assertTrue(p['text'].endswith(body[p['start']:p['end']]))
        self.assertEqual(covered,set(range(len(body))))
        self.assertEqual(len({p['id'] for p in pieces}),len(pieces))
        self.assertEqual(pieces,chunks(note,Tokenizer()))


if __name__=='__main__': unittest.main()
