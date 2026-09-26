"""重建笔记向量索引

换 embedding 模型、改文档布局或索引与数据库对不上时用它。集合名保持不变
（{prefix}_user_{uid}），所以是"清空该用户集合再写入"，幂等可重跑。

用法：
    cd backend && python -X utf8 scripts/reindex_notes.py            # 全部用户
    python -X utf8 scripts/reindex_notes.py --user 3                  # 指定用户
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.retrieval.documents import note_document      # noqa: E402
from core.retrieval.store import note_store             # noqa: E402

PAGE_SIZE = 200


def reindex_user(user_id, notes) -> int:
    """按给定笔记重建该用户集合，返回写入条数"""
    store = note_store(user_id)
    store.reset_collection()
    documents = [note_document(note) for note in notes if (getattr(note, "content", "") or "")]
    if documents:
        store.add_documents(documents)
    return len(documents)


def _all_user_ids():
    from service.service_manager import service_manager
    from service.services.user_service import UserService

    service = service_manager.get_service("user_service", UserService)
    return [user.id for user in service.get_all_users()]


def _notes_of(user_id):
    """分页取全部笔记：get_user_notes 默认只给 50 条，不翻页会静默截断"""
    from service.service_manager import service_manager
    from service.services.note_service import NoteService

    service = service_manager.get_service("note_service", NoteService)
    notes, offset = [], 0
    while True:
        page = service.get_user_notes(user_id, limit=PAGE_SIZE, offset=offset)
        notes.extend(page)
        if len(page) < PAGE_SIZE:
            return notes
        offset += PAGE_SIZE


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="重建笔记向量索引")
    parser.add_argument("--user", type=int, help="只重建指定用户")
    args = parser.parse_args(argv)

    users = [args.user] if args.user is not None else _all_user_ids()
    total = 0
    for user_id in users:
        count = reindex_user(user_id, _notes_of(user_id))
        total += count
        print(f"user {user_id}: {count} 条")
    print(f"完成：{len(users)} 个用户，共 {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
