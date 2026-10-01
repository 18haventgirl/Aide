"""Local SQLite note index migration, backup, status and bounded retry."""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, text
from core.database_core.config import DatabaseConfig
from .note_search_index import NoteSearchIndex


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build','status','retry'])
    args=parser.parse_args()
    config=DatabaseConfig()
    if config.db_type!='sqlite': raise SystemExit('SQLite only; other backends keep existing search')
    engine=create_engine(config.get_connection_url())
    index=NoteSearchIndex(engine)
    if args.command in {'build','retry'}:
        root=Path(__file__).resolve().parents[2]/'data/backups'
        root.mkdir(parents=True,exist_ok=True)
        backup=root/f'notes-before-index-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite'
        with sqlite3.connect(config.sqlite_path) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        print(json.dumps({'backup':str(backup)}),flush=True)
        index.install()
        if args.command=='retry':
            with engine.begin() as c:
                c.execute(text('UPDATE note_index_jobs SET attempts=0,available_at=0 WHERE lease_until<=:now'), {'now':__import__('time').time()})
        while index.process_one(): pass
    with engine.connect() as c:
        pending = c.execute(text('SELECT COUNT(*) FROM note_index_jobs')).scalar()
        print(json.dumps({'notes':c.execute(text('SELECT COUNT(*) FROM notes')).scalar(),
            'indexed_notes':c.execute(text('SELECT COUNT(*) FROM note_index_state')).scalar(),
            'chunks':c.execute(text('SELECT COUNT(*) FROM note_chunks_fts')).scalar(),
            'pending_jobs':pending}))
    index.pool.shutdown(wait=True)
    engine.dispose()
    if args.command != 'status' and pending:
        raise SystemExit('Index incomplete: pending jobs remain; inspect status and retry after resolving the cause.')


if __name__=='__main__':main()
