"""Synthetic note scale benchmark. Never opens the application notes database.

Measures service functions, not HTTP/browser latency or medical correctness.
Uses the pinned real local BGE model and isolated ephemeral Chroma collections.
"""
import argparse
import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine, text

from medical.resource_budget import require_available, memory_status
from .note_search_index import NoteSearchIndex
from .note_search_evaluate import FIXTURES


def percentiles(values):
    values = sorted(values)
    return {name: round(values[max(0, math.ceil(len(values)*p)-1)], 2)
            for name, p in [('p50_ms', .5), ('p95_ms', .95), ('max_ms', 1)]}


def run_size(size, model, client):
    collection_name = 'note_bench_' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='aide-synthetic-notes-') as directory:
        engine = create_engine('sqlite:///' + str(Path(directory)/'notes.sqlite'))
        collection = client.create_collection(collection_name, metadata={'hnsw:space':'cosine'})
        index = NoteSearchIndex(engine, model, collection)
        try:
            with engine.begin() as c:
                c.execute(text('CREATE TABLE notes(id INTEGER PRIMARY KEY,user_id INTEGER,title TEXT,content TEXT,tag TEXT,status TEXT,last_updated TEXT)'))
            index.install()
            rows = []
            for i in range(1, size+1):
                title, body, _ = FIXTURES[(i-1) % len(FIXTURES)]
                marker = f'BENCH-{i:06d}'
                prefix = '本条为合成工作记录，关键事项在正文末尾。\n'*55 if i % 10 == 0 else ''
                rows.append({'id':i, 'user':1 if i%2 else 2, 'title':title,
                             'body':prefix+body+' 唯一编号 '+marker,
                             'tag':'work' if i%3 else 'home', 'status':'draft' if i%5 else 'published'})
            with engine.begin() as c:
                c.execute(text("INSERT INTO notes VALUES(:id,:user,:title,:body,:tag,:status,'2026-10-01')"), rows)
            started = time.perf_counter()
            processed = 0
            while index.process_one():
                processed += 1
                if processed % 50 == 0:
                    require_available(768)
                    print(json.dumps({'size':size,'indexed_jobs':processed}), flush=True)
            with engine.connect() as c:
                pending = c.execute(text('SELECT COUNT(*) FROM note_index_jobs')).scalar()
                indexed = c.execute(text('SELECT COUNT(*) FROM note_index_state')).scalar()
                chunk_count = c.execute(text('SELECT COUNT(*) FROM note_chunks_fts')).scalar()
            if pending or indexed != size:
                raise RuntimeError(f'incomplete benchmark index: indexed={indexed}, pending={pending}')
            build_seconds = round(time.perf_counter()-started, 2)
            # Warm-up is reported separately and excluded from the warm distribution.
            started = time.perf_counter()
            index.search(1, '出差报销需要哪些凭证', 5)
            first_query_ms = round((time.perf_counter()-started)*1000, 2)
            cases = []
            for i in (1, 2, size//2, size-1, size):
                row = rows[i-1]
                cases.append({'user':row['user'], 'query':f'BENCH-{i:06d}', 'expected':i, 'tag':row['tag'], 'status':row['status']})
            for j, (_, _, questions) in enumerate(FIXTURES):
                cases.append({'user':1 if j%2==0 else 2, 'query':questions[1], 'expected':None})
            durations, hybrid_results, errors = [], 0, []
            exact_found = 0
            def query(case):
                started = time.perf_counter()
                hits = index.search(case['user'], case['query'], 5, case.get('tag'), case.get('status'))
                elapsed = (time.perf_counter()-started)*1000
                for hit in hits:
                    if hit['user_id'] != case['user'] or (case.get('tag') and hit['tag']!=case['tag']) or (case.get('status') and hit['status']!=case['status']):
                        raise AssertionError('owner/filter isolation failed')
                return hits, elapsed
            # Five runs of a fixed workload; no threshold tuning here.
            for _ in range(5):
                for case in cases:
                    hits, elapsed = query(case)
                    durations.append(elapsed)
                    hybrid_results += int(any(h['search_type']=='local_bge_hybrid' for h in hits))
                    if case['expected']:
                        exact_found += int(case['expected'] in [h['id'] for h in hits])
            concurrent_times, concurrent_exact = [], 0
            # Four simultaneous callers exercise the bounded query slot and fallback.
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs = [(case, pool.submit(query, case)) for _ in range(5) for case in cases[:5]]
                for case, job in jobs:
                    hits, elapsed = job.result()
                    concurrent_times.append(elapsed)
                    concurrent_exact += int(case['expected'] in [h['id'] for h in hits])
            if exact_found != 25 or concurrent_exact != 25:
                errors.append('unique-marker exact lookup failed')
            return {'size':size, 'chunks':chunk_count, 'build_seconds':build_seconds,
                    'first_query_ms_after_model_load':first_query_ms,
                    'warm':{**percentiles(durations),'queries':len(durations),'queries_returning_hybrid_results':hybrid_results},
                    'concurrent_4':{**percentiles(concurrent_times),'queries':len(concurrent_times),'exact_found':concurrent_exact},
                    'exact_found':exact_found, 'exact_queries':25,
                    'fixture_sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                    'memory':memory_status(), 'errors':errors}
        finally:
            index.pool.shutdown(wait=True)
            engine.dispose()
            client.delete_collection(collection_name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', nargs='+', type=int, default=[100,1000])
    args = parser.parse_args()
    if any(n<10 or n>1000 for n in args.sizes): parser.error('sizes must be between 10 and 1000')
    before = require_available(1536)
    import torch
    import chromadb
    from chromadb.config import Settings
    from medical.bge_embedding import BGEEmbedding
    torch.set_num_threads(2)
    # Fixed settings for comparisons; do not inherit an accidental degraded mode.
    os.environ['NOTE_DENSE_SEARCH']='true'
    os.environ['NOTE_BGE_MAX_DISTANCE']='0.55'
    started = time.perf_counter()
    model = BGEEmbedding(batch_size=4)
    model._load()
    report = {'scope':'synthetic_service_benchmark_not_relevance_or_end_to_end_eval',
              'model':model.name(), 'weights':model.weight_sha256, 'memory_before':before,
              'model_load_ms':round((time.perf_counter()-started)*1000,2), 'results':[]}
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    output = Path('data/note_search_reports/scale_v1.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    for size in args.sizes:
        report['results'].append(run_size(size,model,client))
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report['results'][-1]),flush=True)
    if any(r['errors'] for r in report['results']): raise SystemExit('benchmark assertions failed')


if __name__=='__main__': main()
