# 检索层与 MCP 复用官方件 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把笔记检索与 MCP 工具装载从自写实现换成 LangChain/LangGraph 官方件，并在图里加入固定前置检索节点，同时把措辞与前端文案收敛为工程级中性表述。

**Architecture:** 检索层改用 `langchain-chroma` 的 `Chroma` 向量库（每用户一个集合，cosine）+ `langchain-huggingface` 的 `HuggingFaceEmbeddings`；图的组装仍由 `langchain.agents.create_agent` 完成，自有步骤用官方中间件钩子表达（`before_agent` 检索、`wrap_model_call` 注入、`before_model` 护栏、`wrap_tool_call` 身份覆写）；MCP 客户端换成 `langchain-mcp-adapters`。

**Tech Stack:** LangGraph 1.2.x、LangChain 1.4.x、langchain-chroma 1.1.0、langchain-huggingface 1.2.2、fastmcp 3.4.7、mcp 1.30、ChromaDB 本地持久化、bge-small-zh-v1.5、pytest、React 19 + Vite。

**Spec:** `docs/superpowers/specs/2026-09-26-langgraph-reuse-design.md`（决策依据与证据在该文件第 2 节）

## Global Constraints

- 工作区只有 `D:\Workplace\AIDE-LG\Aide`（分支 `dev/lg`）。`D:\Workplace\Aide` 是另一实例，**禁止跨目录改动**。
- 端口固定：API 8100 / MCP 8102 / Chroma 8101 / MySQL 3307 / 前端 5199，不改。
- Python 环境：`C:\Users\HONOR\.conda\envs\lg-aide\python.exe`；测试统一用 `python -X utf8 -m pytest`。
- 离线优先：`pytest backend/tests` 不得依赖外网与 MySQL；只有 `scripts/e2e_langgraph_check.py` 需要真实服务。
- 召回门禁：`tests/test_rag_recall.py` 的 5 条语料 + 8 组 `(查询, 期望)` 与"更新后相关性反转""删除后不出索引"两条断言**不得放宽或删除**，只允许换 API 写法。
- REST 契约不变：`POST /api/notes/{user_id}/search` 响应仍为 `{success, data: {data: [{note_id,title,tag,score,text}], total}}`。
- 措辞规范：禁止"自研""卖点""能力丰富"等宣传词；统一用 `笔记检索`、`向量库`、`执行节点`、`外部工具`。节点标签显示真实节点名，不做中文美化。
- 每个任务结束时 `pytest backend/tests -q` 必须全绿再提交；提交信息用中文，前缀 `feat:/fix:/refactor:/test:/chore:/docs:`。

---

### Task 1.1: 检索层依赖与 embeddings 工厂

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/core/retrieval/__init__.py`, `backend/core/retrieval/embeddings.py`
- Test: `backend/tests/test_retrieval_embeddings.py`

**Interfaces:**
- Consumes: `core.vector_core.config.VectorConfig`（本任务不搬动，Task 1.4 才搬）
- Produces: `build_embeddings(config) -> Embeddings`、`get_embeddings() -> Embeddings`（进程内单例）

- [ ] **Step 1: 装依赖**

```bash
cd backend && /c/Users/HONOR/.conda/envs/lg-aide/python.exe -m pip install \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple --only-binary :all: \
  langchain-chroma==1.1.0 langchain-huggingface==1.2.2
/c/Users/HONOR/.conda/envs/lg-aide/python.exe -m pip check
```
Expected: `No broken requirements found`（此时 fastmcp 仍是 4.0.9、mcp 仍是 2.2.0，本任务不碰）

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_retrieval_embeddings.py
"""embedding 来源工厂：local 走本地 bge，openai 走远端；配置错误要报得清楚"""

import pytest

from core.retrieval.embeddings import build_embeddings
from core.vector_core.config import VectorConfig


def test_local_provider_uses_huggingface_embeddings(tmp_path):
    pytest.importorskip("sentence_transformers")
    from conftest import LOCAL_MODEL_DIR, local_embedding_available

    if not local_embedding_available():
        pytest.skip(f"缺少本地模型 {LOCAL_MODEL_DIR}")

    from langchain_huggingface import HuggingFaceEmbeddings

    config = VectorConfig.from_env().model_copy(update={
        "embedding_provider": "local", "local_embedding_model": LOCAL_MODEL_DIR,
        "embedding_device": "cpu"})
    emb = build_embeddings(config)

    assert isinstance(emb, HuggingFaceEmbeddings)
    assert len(emb.embed_query("你好")) == config.vector_dimension


def test_openai_provider_uses_openai_embeddings(monkeypatch):
    from langchain_openai import OpenAIEmbeddings

    config = VectorConfig.from_env().model_copy(update={
        "embedding_provider": "openai", "openai_api_key": "sk-test",
        "openai_embedding_model": "text-embedding-3-small", "vector_dimension": 1536})
    assert isinstance(build_embeddings(config), OpenAIEmbeddings)


def test_unknown_provider_raises_valueerror():
    config = VectorConfig.from_env().model_copy(update={"embedding_provider": "bogus"})
    with pytest.raises(ValueError, match="embedding provider"):
        build_embeddings(config)
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && python -X utf8 -m pytest tests/test_retrieval_embeddings.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.retrieval'`

- [ ] **Step 4: 实现**

```python
# backend/core/retrieval/embeddings.py
"""向量来源：统一用 LangChain 的 Embeddings 抽象

local 走进程内 bge-small-zh-v1.5（无外网、无额外密钥），openai 走远端接口。
normalize_embeddings=True 是必须的：Chroma 集合按 cosine 建，向量不归一化会让
相关度分数失去可比性（旧实现就栽过把 l2 距离当余弦用）。
"""

import logging
from functools import lru_cache
from typing import Optional

from langchain_core.embeddings import Embeddings

from core.vector_core.config import VectorConfig

logger = logging.getLogger(__name__)


def build_embeddings(config: VectorConfig) -> Embeddings:
    provider = (config.embedding_provider or "local").lower()

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=config.openai_embedding_model,
            api_key=config.openai_api_key,
            dimensions=config.vector_dimension,
        )

    if provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name=config.local_embedding_model,
            model_kwargs={"device": config.embedding_device},
            encode_kwargs={"normalize_embeddings": True},
        )

    raise ValueError(f"未知的 embedding provider: {provider}（支持 local / openai）")


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """按当前环境配置构造一次，全进程复用（加载 bge 要几秒）"""
    return build_embeddings(VectorConfig.from_env())
```

```python
# backend/core/retrieval/__init__.py
"""检索层：LangChain 标准件（Embeddings / VectorStore / Retriever）"""
```

- [ ] **Step 5: 跑测试**

Run: `cd backend && python -X utf8 -m pytest tests/test_retrieval_embeddings.py -q`
Expected: 3 passed（模型缺失时第 1 条 skip，仍算通过）

- [ ] **Step 6: 在 `requirements.txt` 记录并在向量依赖附近加注释**

```
# 检索层用 LangChain 标准件：Chroma 向量库 + 本地/远端 Embeddings
langchain-chroma>=1.1,<2
langchain-huggingface>=1.2,<2
```

- [ ] **Step 7: 提交**

```bash
git add backend/requirements.txt backend/core/retrieval backend/tests/test_retrieval_embeddings.py
git commit -m "feat: 检索层引入 langchain-chroma 与 langchain-huggingface，统一 Embeddings 来源"
```

---

### Task 1.2: 笔记向量库工厂（每用户一个集合，cosine）

**Files:**
- Create: `backend/core/retrieval/store.py`, `backend/core/retrieval/documents.py`
- Test: `backend/tests/test_retrieval_store.py`

**Interfaces:**
- Consumes: `get_embeddings()`（Task 1.1）、`VectorConfig`
- Produces:
  - `note_store(user_id: int | str) -> Chroma`（按 `f"{prefix}_user_{uid}"` 缓存实例）
  - `collection_name(prefix: str, user_id) -> str`
  - `vector_health() -> dict`（给 `/api/health` 用）
  - `note_document(note) -> Document`、`documents_to_rows(pairs, threshold) -> list[dict]`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_retrieval_store.py
"""向量库工厂：集合命名、按用户隔离、cosine 空间、文档映射与 REST 键"""

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

import core.retrieval.store as store_mod
from core.retrieval.documents import documents_to_rows, note_document
from core.retrieval.store import collection_name, note_store, vector_health


@pytest.fixture
def fake_store(tmp_path, monkeypatch):
    """用确定性假向量，测试不加载 bge 模型，也不碰 backend/lg-aide-chroma-db"""
    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    store_mod._stores.clear()
    return note_store


def test_collection_name_is_sanitized_and_prefixed():
    assert collection_name("lg_aide", 12) == "lg_aide_user_12"
    assert collection_name("lg_aide", "a-b.c") == "lg_aide_user_a_b_c"


def test_each_user_gets_a_separate_collection(fake_store):
    a, b = fake_store(1), fake_store(2)

    assert a._collection.name == "lg_aide_user_1"
    assert b._collection.name == "lg_aide_user_2"
    assert fake_store(1) is a          # 同一用户复用实例，不重复建集合


def test_cosine_space_is_declared_on_creation(fake_store):
    assert fake_store(1)._collection.metadata["hnsw:space"] == "cosine"


def test_note_document_keeps_existing_id_and_metadata_contract():
    note = SimpleNamespace(id=7, user_id=1, title="阳台绿萝浇水", content="土表发白就浇透",
                           tag="园艺", status="active")
    doc = note_document(note)

    assert doc.id == "note_7"
    assert doc.page_content == "阳台绿萝浇水\n土表发白就浇透"
    assert doc.metadata == {"note_id": "7", "user_id": "1", "title": "阳台绿萝浇水",
                            "tag": "园艺", "status": "active", "source": "notes"}


def test_documents_to_rows_emits_rest_contract_keys_and_filters_threshold():
    docs = [(Document(page_content="a\nb", metadata={"note_id": "1", "title": "a", "tag": "t"}), 0.81),
            (Document(page_content="c", metadata={"note_id": "2", "title": "c", "tag": ""}), 0.12)]
    rows = documents_to_rows(docs, threshold=0.3)

    assert [sorted(r) for r in rows] == [["note_id", "score", "tag", "text", "title"]]
    assert rows[0]["note_id"] == "1" and rows[0]["tag"] is None      # 空标签给 None，与旧实现一致
    assert rows[0]["text"] == "a\nb" and abs(rows[0]["score"] - 0.81) < 1e-9


def test_vector_health_reports_collection_count(fake_store, tmp_path):
    fake_store(1)
    health = vector_health()
    assert health["status"] == "healthy" and health["collections"] >= 1


def test_http_mode_is_warned_once(fake_store, monkeypatch, caplog):
    """检索层只走本地持久化；配了 http 必须说清楚，别让人以为数据在 8101"""
    import logging

    monkeypatch.setattr(store_mod, "_mode", lambda: "http")
    store_mod._http_warned = False

    with caplog.at_level(logging.WARNING):
        fake_store(7)
        fake_store(8)

    warnings = [r for r in caplog.records if "CHROMA_CLIENT_MODE" in r.getMessage()]
    assert len(warnings) == 1
```

补一行 import：文件顶部加 `from types import SimpleNamespace`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -X utf8 -m pytest tests/test_retrieval_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.retrieval.store'`

- [ ] **Step 3: 实现 documents.py**

```python
# backend/core/retrieval/documents.py
"""笔记 ↔ LangChain Document 的映射

id 规则沿用旧的 note_{id}，删除/更新才可能对得上既有集合。
documents_to_rows 的输出键就是 REST 契约（note_id/title/tag/score/text），不改形状。
"""

from typing import Any, Dict, Iterable, List, Tuple

from langchain_core.documents import Document

SNIPPET_CHARS = 500


def note_document(note: Any) -> Document:
    title = getattr(note, "title", "") or ""
    content = getattr(note, "content", "") or ""
    return Document(
        page_content=f"{title}\n{content}",
        id=f"note_{note.id}",
        metadata={
            "note_id": str(note.id),
            "user_id": str(getattr(note, "user_id", "")),
            "title": title,
            "tag": getattr(note, "tag", "") or "",
            "status": getattr(note, "status", "") or "",
            "source": "notes",
        },
    )


def documents_to_rows(pairs: Iterable[Tuple[Document, float]],
                     threshold: float) -> List[Dict[str, Any]]:
    rows = []
    for doc, score in pairs:
        if score < threshold:
            continue
        meta = doc.metadata or {}
        rows.append({
            "note_id": meta.get("note_id"),
            "title": meta.get("title"),
            "tag": meta.get("tag") or None,
            "score": score,
            "text": doc.page_content[:SNIPPET_CHARS],
        })
    return rows
```

- [ ] **Step 4: 实现 store.py**

```python
# backend/core/retrieval/store.py
"""笔记向量库：每用户一个 Chroma 集合

隔离靠集合命名空间，而不是 where={"user_id":...} 过滤：过滤条件一旦在某处漏传，
就是跨用户读取；分集合把这件事变成不可能。
集合必须显式声明 hnsw:space=cosine —— Chroma 默认是 l2，旧实现把 l2 距离当余弦用过，
检索长期失效（见 docs/PROGRESS.md）。
"""

import logging
import re
from typing import Union

import chromadb
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


def _embeddings() -> Embeddings:
    from core.retrieval.embeddings import get_embeddings

    return get_embeddings()


def _persist_dir() -> str:
    from core.vector_core.config import VectorConfig

    return VectorConfig.from_env().chroma_persist_directory


def _prefix() -> str:
    from core.vector_core.config import VectorConfig

    return VectorConfig.from_env().chroma_collection_prefix


def _mode() -> str:
    from core.vector_core.config import VectorConfig

    return VectorConfig.from_env().chroma_client_mode


_stores: dict = {}
_http_warned = False


def collection_name(prefix: str, user_id: Union[int, str]) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(user_id))
    return f"{prefix}_user_{sanitized}"


def note_store(user_id: Union[int, str]) -> Chroma:
    """取该用户的向量库句柄；同一进程内复用"""
    key = str(user_id)
    if key not in _stores:
        _warn_if_http()
        _stores[key] = Chroma(
            collection_name=collection_name(_prefix(), user_id),
            embedding_function=_embeddings(),
            persist_directory=_persist_dir(),
            collection_metadata={"hnsw:space": "cosine"},
        )
        logger.debug(f"笔记向量库就绪: {_stores[key]._collection.name}")
    return _stores[key]


def _warn_if_http() -> None:
    """检索层只走本地持久化模式；显式配了 http 要说清楚，别让人以为连上了 8101

    旧实现支持 http/local 两种模式，标准件路线统一用本地持久化目录，
    留着 http 配置不管会让人误判数据位置。
    """
    global _http_warned
    if _http_warned:
        return
    if _mode() == "http":
        logger.warning("CHROMA_CLIENT_MODE=http 已不再生效：笔记检索统一使用本地持久化目录")
    _http_warned = True


def vector_health() -> dict:
    """给 /api/health 用：能连上并列出集合就算健康"""
    try:
        client = chromadb.PersistentClient(path=_persist_dir())
        return {"status": "healthy", "collections": len(client.list_collections())}
    except Exception as exc:
        logger.warning(f"向量库健康检查失败: {exc}")
        return {"status": "unhealthy", "error": str(exc)}
```

在 `note_store` 与 `_warn_if_http` 之间不需要额外声明：`_stores` 与 `_http_warned` 已在模块顶部定义，
测试里 `store_mod._stores.clear()` 依赖的就是这个名字。

- [ ] **Step 5: 跑测试**

Run: `cd backend && python -X utf8 -m pytest tests/test_retrieval_store.py -q`
Expected: 7 passed

- [ ] **Step 6: 提交**

```bash
git add backend/core/retrieval backend/tests/test_retrieval_store.py
git commit -m "feat: 笔记向量库工厂（每用户一个 cosine 集合）与文档映射"
```

---

### Task 1.3: note_service 三个向量触点改走标准件

**Files:**
- Modify: `backend/service/services/note_service.py`（`__init__`、`_add_to_vector_db`、删除路径、更新路径、`search_notes_by_vector`）
- Test: `backend/tests/test_note_service_vector.py`

**Interfaces:**
- Consumes: `note_store(user_id)`、`note_document(note)`、`documents_to_rows(pairs, threshold)`
- Produces: `NoteService.search_notes_by_vector(user_id: int, query: str, limit: int = 10) -> list[dict]`（键不变）、`NoteService` 不再持有 `vector_client`

- [ ] **Step 1: 先枚举全部触点（不靠记忆）**

```bash
cd backend && grep -n "vector_client\|VectorDocument\|VectorQuery\|VectorDeleteFilter" service/services/note_service.py
```
Expected: 至少出现 `__init__`、创建后索引、更新后重算、删除、`search_notes_by_vector` 五处；逐处替换，一处不留。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_note_service_vector.py
"""笔记服务的向量索引路径：写入/更新/删除/检索都走 langchain-chroma，且 REST 键不变"""

from types import SimpleNamespace

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

import core.retrieval.store as store_mod
from core.retrieval import store as store_module


@pytest.fixture(autouse=True)
def fake_vectors(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    store_mod._stores.clear()
    yield
    store_mod._stores.clear()


def _note(**kw):
    base = dict(id=11, user_id=1, title="番茄炒蛋", content="先炒蛋再放番茄", tag="菜谱",
                status="active")
    base.update(kw)
    return SimpleNamespace(**base)


def test_service_has_no_vector_client_attribute_after_migration():
    from service.services.note_service import NoteService
    import inspect

    params = inspect.signature(NoteService.__init__).parameters
    assert "vector_client" not in params
    assert not hasattr(NoteService, "vector_client")


def test_add_update_delete_roundtrip_on_collection():
    from service.services.note_service import NoteService

    service = NoteService.__new__(NoteService)      # 不碰 MySQL，只测向量部分
    store = store_module.note_store(1)

    service._index_note(_note())
    assert store.similarity_search("番茄炒蛋", k=1)[0].metadata["note_id"] == "11"

    service._index_note(_note(title="猫砂采购", content="宠物店买猫砂"))
    ids = [d.metadata["note_id"] for d in store.similarity_search("猫砂", k=3)]
    assert "11" in ids and len(store.get()["ids"]) == 1     # 更新是覆盖不是新增

    service._drop_index(1, 11)
    assert store.get()["ids"] == []


def test_search_rows_emit_rest_contract_keys_and_honour_threshold():
    from langchain_core.documents import Document
    from service.services.note_service import _search_rows

    store = store_mod.note_store(1)
    store.add_documents([Document(page_content="阳台绿萝\n土表发白就浇透", id="note_1",
                                  metadata={"note_id": "1", "title": "阳台绿萝", "tag": "园艺"})])

    rows = _search_rows(store, "绿萝浇水", threshold=0.0, limit=3)
    assert sorted(rows[0]) == ["note_id", "score", "tag", "text", "title"]
    assert rows[0]["note_id"] == "1" and rows[0]["tag"] == "园艺"

    assert _search_rows(store, "绿萝浇水", threshold=1.1, limit=3) == []   # 阈值把全部挡掉
```

测试文件顶部的 import 用：

```python
from types import SimpleNamespace

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

import core.retrieval.store as store_mod
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && python -X utf8 -m pytest tests/test_note_service_vector.py -q`
Expected: FAIL（`vector_client` 参数仍在 / `_index_note` 不存在）

- [ ] **Step 4: 实现**

在 `note_service.py` 顶部加：

```python
from core.retrieval.documents import documents_to_rows, note_document
from core.retrieval.store import note_store
```

模块级检索函数（供 `search_notes_by_vector` 与测试复用）：

```python
def _search_rows(store, query: str, threshold: float, limit: int = 10):
    """向量检索 + REST 形状转换，一处定义，测试也打这一层"""
    return documents_to_rows(store.similarity_search_with_relevance_scores(query, k=limit),
                             threshold)
```

`NoteService` 改动：

```python
    def __init__(self, db_client: Optional[DatabaseClient] = None):
        self.db_client = db_client or DatabaseClient()
        self.user_service = UserService()
        try:
            self.vector_config = VectorConfig.from_env()
        except Exception as exc:
            print(f"警告：向量配置读取失败，笔记检索退回关键词方式: {exc}")
            self.vector_config = None

    def _index_note(self, note: Note) -> None:
        """写入/覆盖索引。Chroma 按 id upsert，更新笔记不需要先删"""
        if not self.vector_config or not (getattr(note, "content", "") or ""):
            return
        try:
            note_store(note.user_id).add_documents([note_document(note)])
        except Exception as exc:
            print(f"笔记向量索引写入失败（不影响数据库已保存）: {exc}")

    def _drop_index(self, user_id: int, note_id: int) -> None:
        if not self.vector_config:
            return
        try:
            note_store(user_id).delete(ids=[f"note_{note_id}"])
        except Exception as exc:
            print(f"笔记向量索引删除失败: {exc}")
```

`create_note` 里原来的 `if self.vector_client and note_content: self._add_to_vector_db(note)`
改为 `self._index_note(note)`；`update_note` 的向量分支同样改为 `self._index_note(note)`；
`delete_note` 的 `VectorDeleteFilter` 分支改为 `self._drop_index(user_id, note_id)`；
`search_notes_by_vector` 改为：

```python
    def search_notes_by_vector(self, user_id: int, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """语义检索当前用户的笔记（langchain-chroma，相关度已按 cosine 归一）"""
        if not self.vector_config:
            return []
        try:
            store = note_store(user_id)
        except Exception as exc:
            print(f"向量库不可用，本次检索退回空结果: {exc}")
            return []
        return _search_rows(store, query, self.vector_config.similarity_threshold, limit)
```

删除 `VectorDocument/VectorQuery/VectorDeleteFilter/ChromaVectorClient` 的 import 与
`_add_to_vector_db` 旧函数本体。

- [ ] **Step 5: 跑测试**

Run: `cd backend && python -X utf8 -m pytest tests/test_note_service_vector.py -q`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add backend/service/services/note_service.py backend/tests/test_note_service_vector.py
git commit -m "refactor: 笔记服务的向量写入/更新/删除/检索改走 langchain-chroma"
```

---

### Task 1.4: 拆掉手写向量层（config 搬迁 + service_manager + 健康检查 + 召回测试迁移）

**Files:**
- Move: `backend/core/vector_core/config.py` → `backend/core/retrieval/config.py`
- Delete: `backend/core/vector_core/`（`client.py`、`models.py`、`utils.py`、`__init__.py`）
- Modify: `backend/service/service_manager.py`、`backend/api/system_api.py`、`backend/tests/conftest.py`、`backend/tests/test_rag_recall.py`、`backend/mcp-serve/user_data_tools.py`
- Test: 复用 `tests/test_rag_recall.py`

**Interfaces:**
- Consumes: `core.retrieval.config.VectorConfig`、`core.retrieval.store.vector_health`
- Produces: 仓库里不再有自写 Chroma 封装

- [ ] **Step 1: 迁移配置并改所有引用**

```bash
cd backend && git mv core/vector_core/config.py core/retrieval/config.py
grep -rn "core.vector_core\|VectorConfig" --include=*.py . | grep -v __pycache__
```
把 grep 出的每一处 import 改成 `from core.retrieval.config import VectorConfig`；
`core/retrieval/store.py` 与 `embeddings.py` 里的 `from core.vector_core.config import VectorConfig`
也一并改掉。

- [ ] **Step 2: service_manager 去掉向量客户端**

`service/service_manager.py`：删掉 `from core.vector_core import ChromaVectorClient, VectorConfig`、
`self._vector_client` 的创建（约 63-66 行）、`get_vector_client()`（约 85-89 行）、
`get_service` 里 `if 'vector_client' in sig.parameters` 分支（约 112 行）、
统计里的 `vector_client_active`（约 239 行）。

- [ ] **Step 3: 健康检查改指向 Chroma**

`api/system_api.py` 约 66-74 行改为：

```python
        from core.retrieval.store import vector_health

        health = vector_health()
        services["vector_database"] = "healthy" if health.get("status") == "healthy" else "unhealthy"
        if health.get("status") != "healthy":
            issues.append(f"向量库不可用: {health.get('error', '未知原因')}")
```

- [ ] **Step 4: 召回测试换 API、断言原样保留**

`tests/conftest.py` 的 `rag_client` fixture 换成"给一个用户返回 Chroma 句柄"的 fixture：

```python
@pytest.fixture
def rag_store(tmp_path, monkeypatch):
    """临时目录里的 Chroma 集合 + 本地 bge 向量；模型缺失则 skip

    断言基线（5 语料 / 8 组查询 / 更新反转 / 删除生效）与迁移前完全一致，
    这是"换成标准件没把检索改坏"的唯一判据。
    """
    if not local_embedding_available():
        pytest.skip(f"缺少本地 embedding 模型 {LOCAL_MODEL_DIR}")

    import core.retrieval.store as store_mod

    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    monkeypatch.setattr(store_mod, "_embeddings", lambda: _local_embeddings())
    store_mod._stores.clear()
    yield store_mod.note_store("tester")
    store_mod._stores.clear()


def _local_embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=LOCAL_MODEL_DIR, model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True})
```

`tests/test_rag_recall.py` 整体改写（语料与断言一字不动）：

```python
"""笔记语义检索的召回正确性（离线：不依赖 MySQL、不依赖外网，向量由本地 bge 计算）

其中「植物养护提醒 / 乳制品采购」等查询与语料没有共同用词，用来确认检索是真语义，
而不是关键词匹配；update / delete 用例保证索引跟随内容变化。
"""

from langchain_core.documents import Document

CORPUS = {
    "note_gardening": "阳台绿萝浇水记录：土表发白就要浇透，冬天减少到两周一次",
    "note_milk": "超市购物：两升装脱脂牛奶，顺路买鸡蛋和酸奶",
    "note_scramble": "番茄炒蛋做法：先炒蛋再放番茄，加一点糖提鲜",
    "note_report": "季度汇报要点：营收增长百分之十二，续费率下滑需要关注",
    "note_train": "去杭州的高铁：二等座候补成功，早上七点二十发车",
}

QUERIES = [
    ("植物养护提醒", "note_gardening"),      # 与语料零共同用词，纯语义
    ("乳制品采购", "note_milk"),             # 同义改写
    ("鸡蛋做菜的技巧", "note_scramble"),
    ("业务复盘材料", "note_report"),
    ("坐火车去杭州", "note_train"),
    ("超市要买什么", "note_milk"),
    ("给花浇水", "note_gardening"),
    ("番茄炒蛋", "note_scramble"),
]


def _doc(doc_id: str, text: str) -> Document:
    return Document(page_content=text, id=doc_id, metadata={"note_id": doc_id, "title": text[:8]})


def _seed(store):
    store.add_documents([_doc(doc_id, text) for doc_id, text in CORPUS.items()])


def _hit_ids(store, query):
    return [d.metadata["note_id"] for d in store.similarity_search(query, k=3)]


def _scores(store, query):
    pairs = store.similarity_search_with_relevance_scores(query, k=len(CORPUS))
    return {doc.metadata["note_id"]: float(score) for doc, score in pairs}


def test_top3_recall_is_correct(rag_store):
    _seed(rag_store)
    misses = []
    for query, expected in QUERIES:
        ids = _hit_ids(rag_store, query)
        if expected not in ids:
            misses.append(f"{query} → 期望 {expected}，实得 {ids}")
    assert not misses, "召回失败:\n" + "\n".join(misses)


def test_update_repoints_relevance(rag_store):
    """改写内容后，向量必须跟着变：同一篇笔记的相关度排序要反转"""
    _seed(rag_store)
    assert _scores(rag_store, "乳制品采购")["note_milk"] > _scores(rag_store, "猫砂去哪买")["note_milk"]

    rag_store.update_documents(["note_milk"], [_doc("note_milk", "宠物店买猫砂和主食罐头")])

    dairy = _scores(rag_store, "乳制品采购")["note_milk"]
    litter = _scores(rag_store, "猫砂去哪买")["note_milk"]
    assert litter > dairy, f"更新后应更贴合猫砂语境，实得 猫砂={litter:.3f} 乳制品={dairy:.3f}"


def test_delete_removes_from_index(rag_store):
    _seed(rag_store)
    rag_store.delete(ids=["note_milk"])
    assert "note_milk" not in _hit_ids(rag_store, "超市要买什么")
```

- [ ] **Step 5: 删掉旧包并跑全量**

```bash
cd backend && git rm -r core/vector_core
python -X utf8 -m pytest tests -q
```
Expected: 全绿（召回 3 项走新 API，断言与迁移前一致）

- [ ] **Step 6: 提交**

```bash
git add -A backend/core backend/service backend/api backend/tests
git commit -m "refactor: 删除自写 Chroma 封装，检索层统一到 langchain-chroma"
```

---

### Task 1.5: 索引重建脚本并实跑

**Files:**
- Create: `backend/scripts/reindex_notes.py`
- Test: `backend/tests/test_reindex_script.py`

**Interfaces:**
- Consumes: `NoteService`（读笔记）、`note_store`、`note_document`
- Produces: `reindex_user(user_id, notes) -> int`（写入条数）、命令行入口（幂等，可重复执行）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_reindex_script.py
"""重建脚本必须幂等：跑两次条数不变，且不会把别的用户卷进来"""

from types import SimpleNamespace

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

import core.retrieval.store as store_mod
from scripts.reindex_notes import reindex_user


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    store_mod._stores.clear()
    yield store_mod.note_store(5)
    store_mod._stores.clear()


def _notes(user_id=5, count=3):
    return [SimpleNamespace(id=i, user_id=user_id, title=f"笔记{i}", content=f"内容{i}",
                            tag="t", status="active") for i in range(1, count + 1)]


def test_reindex_is_idempotent(store):
    assert reindex_user(5, _notes()) == 3
    assert reindex_user(5, _notes()) == 3          # 第二次不翻倍
    assert len(store.get()["ids"]) == 3


def test_reindex_drops_stale_documents(store):
    reindex_user(5, _notes(count=3))
    reindex_user(5, _notes(count=1))               # 只剩一条
    assert len(store.get()["ids"]) == 1
```

- [ ] **Step 2: 跑测试确认失败** → Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
# backend/scripts/reindex_notes.py
"""重建笔记向量索引

换用 langchain-chroma 后文档布局与集合空间（cosine）都变了，旧向量必须按新规则重算。
集合名保持不变（{prefix}_user_{uid}），所以是"清空该用户集合再写"，幂等可重跑。

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


def reindex_user(user_id: int, notes) -> int:
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
    from service.service_manager import service_manager
    from service.services.note_service import NoteService

    service = service_manager.get_service("note_service", NoteService)
    notes, offset = [], 0
    while True:
        page = service.get_user_notes(user_id, limit=200, offset=offset)
        notes.extend(page)
        if len(page) < 200:
            return notes
        offset += 200


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="重建笔记向量索引")
    parser.add_argument("--user", type=int, help="只重建指定用户")
    args = parser.parse_args(argv)

    users = [args.user] if args.user else _all_user_ids()
    total = 0
    for user_id in users:
        count = reindex_user(user_id, _notes_of(user_id))
        total += count
        print(f"user {user_id}: {count} 条")
    print(f"完成：{len(users)} 个用户，共 {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`NoteService.get_user_notes(user_id, status=None, tag=None, search_query=None, limit=50, offset=0)`
是实测签名，默认只给 50 条，所以重建必须分页取，否则笔记多的用户会被静默截断。

- [ ] **Step 4: 跑测试 + 真实重建**

```bash
cd backend && python -X utf8 -m pytest tests/test_reindex_script.py -q
python -X utf8 scripts/reindex_notes.py
python -X utf8 scripts/reindex_notes.py            # 再跑一次，条数必须一致
```
Expected: 4 passed；两次脚本输出每个用户的条数相同

- [ ] **Step 5: 手工验证检索仍准（真实语义，不用假向量）**

```bash
cd backend && python -X utf8 -c "
from core.retrieval.store import note_store
for doc, s in note_store(1).similarity_search_with_relevance_scores('植物养护提醒', k=3):
    print(round(s,3), doc.metadata['title'])
"
```
Expected: 第一条是与绿萝/浇水相关的笔记

- [ ] **Step 6: 全量回归 + 提交**

```bash
python -X utf8 -m pytest tests -q
git add backend/scripts/reindex_notes.py backend/tests/test_reindex_script.py
git commit -m "feat: 笔记向量索引重建脚本（幂等）并完成重建"
```

---

### Task 2.1: AideState 与前置检索钩子

**Files:**
- Create: `backend/agent/state.py`, `backend/agent/retrieval.py`
- Test: `backend/tests/test_agent_retrieval.py`

**Interfaces:**
- Consumes: `note_store`、`UserContext`
- Produces: `AideState`（`messages` + `retrieved: list`）、`build_retrieval_middleware() -> AgentMiddleware`（`before_agent`，节点名 `note_retrieval.before_agent`，写入 `state["retrieved"]`，每项 `{id,title,score,text}`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_agent_retrieval.py
"""前置检索：每轮一次，结果进 state.retrieved，不写进 messages

放在 before_agent 而不是 before_model，是为了工具回环不再重复检索；
放在 wrap_model_call 注入，是为了检索块不落进 checkpoint 历史。
"""

import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.messages import AIMessage, HumanMessage

import core.retrieval.store as store_mod
from agent.context import UserContext
from agent.retrieval import build_retrieval_injector, build_retrieval_middleware
from agent.state import AideState


class StubModel:
    """只回一句话，不调工具"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, *args, **kwargs):
        return AIMessage(content="好的")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    store_mod._stores.clear()
    handle = store_mod.note_store(3)
    handle.add_documents([
        Document(page_content="阳台绿萝浇水\n土表发白就浇透，冬天两周一次", id="note_1",
                 metadata={"note_id": "1", "title": "阳台绿萝浇水", "tag": "园艺"}),
    ])
    yield handle
    store_mod._stores.clear()


def _run(middlewares, text="我的绿萝多久浇一次水"):
    async def go():
        agent = create_agent(StubModel(), [], middleware=middlewares,
                             state_schema=AideState, context_schema=UserContext, name="Aide")
        return await agent.ainvoke({"messages": [HumanMessage(content=text)]},
                                   context=UserContext(user_id=3))

    return asyncio.run(go())


def test_retrieval_runs_once_per_turn_and_fills_state(store):
    state = _run([build_retrieval_middleware(threshold=0.0, k=3)])

    hits = state["retrieved"]
    assert len(hits) == 1 and hits[0]["title"] == "阳台绿萝浇水"
    assert hits[0]["text"].startswith("阳台绿萝浇水")
    assert isinstance(hits[0]["score"], float)


def test_retrieval_never_adds_messages(store):
    state = _run([build_retrieval_middleware(threshold=0.0, k=3)])

    assert [type(m).__name__ for m in state["messages"]] == ["HumanMessage", "AIMessage"]


def test_retrieval_failure_degrades_to_no_hits(store, monkeypatch):
    monkeypatch.setattr(store_mod, "note_store", lambda uid: (_ for _ in ()).throw(RuntimeError("chroma 挂了")))
    state = _run([build_retrieval_middleware(threshold=0.0, k=3)])
    assert state["retrieved"] == []


def test_injector_adds_block_to_model_call_but_not_state(store):
    seen = {}

    class RecordingModel(StubModel):
        async def ainvoke(self, messages, *a, **k):
            seen["messages"] = messages
            return AIMessage(content="两周一次")

    async def go():
        agent = create_agent(RecordingModel(), [],
                             middleware=[build_retrieval_middleware(threshold=0.0, k=3),
                                         build_retrieval_injector()],
                             state_schema=AideState,
                             context_schema=UserContext, name="Aide")
        return await agent.ainvoke({"messages": [HumanMessage(content="绿萝多久浇水")]},
                                   context=UserContext(user_id=3))

    state = asyncio.run(go())

    assert any("笔记检索结果" in str(m.content) for m in seen["messages"])   # 模型看到了
    assert not any("笔记检索结果" in str(m.content) for m in state["messages"])  # 但没落进状态
```

- [ ] **Step 2: 跑测试确认失败** → Expected: FAIL（`agent.state` / `agent.retrieval` 不存在）

- [ ] **Step 3: 实现 state.py**

```python
# backend/agent/state.py
"""图状态

在 LangChain 的 AgentState（messages / jump_to / structured_response）上加两个自有字段。
retrieved 存的是纯 dict 而不是 Document，方便 checkpoint 序列化与前端下发。
"""

from typing import Any, Dict, List

from langchain.agents import AgentState


class AideState(AgentState):
    retrieved: List[Dict[str, Any]]
```

- [ ] **Step 4: 实现 retrieval.py**

```python
# backend/agent/retrieval.py
"""笔记检索的两个图钩子

retrieve（before_agent）：每轮跑一次，命中写进 state.retrieved。
inject（wrap_model_call）：每次模型调用时把命中内容作为临时 SystemMessage 插在最新一条
用户消息之前。之所以不写进 messages，是因为 checkpoint 会把 state 里的消息永久保留，
多轮下来历史里会堆满检索片段。
"""

import logging
from typing import Any, Dict, List, Optional

from langchain.agents.middleware import before_agent, wrap_model_call
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AideState

logger = logging.getLogger(__name__)

RETRIEVAL_NAME = "note_retrieval"
INJECT_NAME = "retrieval_context"
SNIPPET_CHARS = 300


def _last_human_text(messages: List[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content or "").strip()
    return ""


def build_retrieval_middleware(k: int = 5, threshold: Optional[float] = None):
    @before_agent(state_schema=AideState, name=RETRIEVAL_NAME)
    async def retrieve(state, runtime):
        user_id = getattr(getattr(runtime, "context", None), "user_id", None)
        query = _last_human_text(state.get("messages", []))
        if user_id is None or not query:
            return {"retrieved": []}

        from core.retrieval.store import note_store

        limit = max(1, min(k, 20))
        try:
            store = note_store(user_id)
            cut = threshold
            if cut is None:
                from core.retrieval.config import VectorConfig

                cut = VectorConfig.from_env().similarity_threshold
            pairs = store.similarity_search_with_relevance_scores(query, k=limit)
        except Exception as exc:
            logger.warning(f"笔记检索不可用，本轮不注入: {exc}")
            return {"retrieved": []}

        hits = [{"id": (doc.metadata or {}).get("note_id"),
                 "title": (doc.metadata or {}).get("title") or "无标题",
                 "score": float(score),
                 "text": doc.page_content[:SNIPPET_CHARS]}
                for doc, score in pairs if float(score) >= cut]
        return {"retrieved": hits}

    return retrieve


def build_retrieval_injector():
    @wrap_model_call(state_schema=AideState, name=INJECT_NAME)
    def inject(request, handler):
        hits: List[Dict[str, Any]] = request.state.get("retrieved") or []
        if not hits:
            return handler(request)

        block = "\n".join(f"- {h['title']}（相关度 {h['score']:.2f}）: {h['text']}" for h in hits)
        message = SystemMessage(content=f"[笔记检索结果]\n{block}")
        messages = list(request.messages)
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                messages.insert(index, message)
                break
        else:
            messages.append(message)
        return handler(request.override(messages=messages))

    return inject
```

- [ ] **Step 5: 跑测试**

Run: `cd backend && python -X utf8 -m pytest tests/test_agent_retrieval.py -q`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add backend/agent/state.py backend/agent/retrieval.py backend/tests/test_agent_retrieval.py
git commit -m "feat: 图状态与笔记检索前置钩子（before_agent 检索 + wrap_model_call 注入）"
```

---

### Task 2.2: 把检索挂进建图并透出检索事件

**Files:**
- Modify: `backend/agent/graph.py`、`backend/agent/runtime.py`、`backend/api/ws_stream.py`
- Test: `backend/tests/test_graph_build.py`、`backend/tests/test_runtime_events.py`、`backend/tests/test_ws_stream_mapping.py`

**Interfaces:**
- Consumes: `build_retrieval_middleware()`、`build_retrieval_injector()`（Task 2.1）
- Produces: `translate_stream` 新增事件 `{"kind":"retrieval","hits":[{id,title,score,text}],"node":...}`；`WsStreamTranslator` 下发 `{"type":"retrieval","hits":...}`；`AideAnswer.retrieval: List[dict]`

- [ ] **Step 1: 加失败测试（三处）**

`tests/test_graph_build.py` 追加：

```python
def test_build_agent_runs_retrieval_first(tmp_path, monkeypatch):
    """图的入口边必须指向检索节点：每轮先召回，再进护栏与模型

    注意 wrap_model_call 不产生节点（它是包住模型调用的包装器），所以这里只断言
    before_agent 节点与入口边，不去猜注入钩子的节点名。
    """
    import core.retrieval.store as store_mod
    from langchain_core.embeddings import DeterministicFakeEmbedding

    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    store_mod._stores.clear()

    agent = asyncio.run(build_agent(ScriptedModel(replies=[{"content": "在的"}]), tools=[]))
    graph = agent.get_graph()
    entry = [edge.target for edge in graph.edges if edge.source == "__start__"]

    assert "note_retrieval.before_agent" in list(graph.nodes)
    assert entry == ["note_retrieval.before_agent"]
```

`tests/test_runtime_events.py` 追加：

```python
def test_retrieval_update_becomes_a_retrieval_event():
    events = _collect(_feed([
        ("updates", {"note_retrieval.before_agent": {"retrieved": [
            {"id": "1", "title": "阳台绿萝浇水", "score": 0.71, "text": "土表发白就浇透"}]}}),
    ]))

    retrieval = next(e for e in events if e["kind"] == "retrieval")
    assert retrieval["hits"][0]["title"] == "阳台绿萝浇水"
    assert retrieval["hits"][0]["score"] == 0.71
```

`tests/test_ws_stream_mapping.py` 追加：

```python
def test_retrieval_event_becomes_a_retrieval_frame():
    _, (msg,) = _feed({"kind": "retrieval", "hits": [{"id": "1", "title": "绿萝", "score": 0.7,
                                                     "text": "土表发白就浇透"}], "node": "note_retrieval"})
    assert msg.content["type"] == "retrieval"
    assert msg.content["hits"][0]["title"] == "绿萝"
```

- [ ] **Step 2: 跑三处测试确认失败** → Expected: FAIL（节点缺失 / `KeyError: 'retrieval'`）

- [ ] **Step 3: 建图接入**

`agent/graph.py` 的 `build_agent` 中，middleware 顺序改为"检索 → 注入 → 护栏 → 身份"：

```python
    from agent.retrieval import build_retrieval_injector, build_retrieval_middleware

    middleware = [
        build_retrieval_middleware(),
        build_retrieval_injector(),
        build_identity_middleware(),
        *build_guardrail_middlewares(model),
        *extra_middleware,
    ]
```

并把 `state_schema=AideState` 传给 `create_agent`：

```python
    agent = create_agent(
        model=model, tools=tool_list, system_prompt=SYSTEM_PROMPT, middleware=middleware,
        state_schema=AideState, context_schema=UserContext,
        checkpointer=checkpointer, name="Aide",
    )
```

`SYSTEM_PROMPT` 去掉宣传式措辞，并说明检索块会自动出现：

```python
SYSTEM_PROMPT = (
    "你是 LG-Aide，个人日常助手。可用能力：天气与预报、菜谱、新闻、待办与笔记。\n"
    "规则：\n"
    "1) 需要外部信息或读写用户数据时调用工具，不要凭空编造。\n"
    "2) 用户身份由系统提供，不要追问 user_id。\n"
    "3) 带 [笔记检索结果] 的系统消息是用户自己笔记的命中片段，可用但需注明来源是笔记。\n"
    "4) 回答简洁，中文优先，先结论后依据。\n"
    "5) 工具报错要如实说明。\n"
    "6) 调用工具前不要输出“我来帮你查一下”这类过程说明。"
)
```

- [ ] **Step 4: translate_stream 透出检索**

`agent/runtime.py` 的 `translate_stream` 在 `mode == "updates"` 分支里，节点遍历开头加：

```python
                hits = (update or {}).get("retrieved")
                if hits is not None:
                    yield {"kind": "retrieval", "hits": hits, "node": node}
```

`AideAnswer` 增加字段并在 `ask`/`astream` 收尾填充：

```python
@dataclass
class AideAnswer:
    text: str = ""
    tool_events: List[Dict[str, Any]] = field(default_factory=list)
    guardrail_checks: List[Dict[str, Any]] = field(default_factory=list)
    retrieval: List[Dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    error: Optional[str] = None
```

`ask`/`astream` 里从最终 state 取：`retrieval = (state_values.get("retrieved") or [])`，
构造 `AideAnswer(..., retrieval=retrieval)`。

- [ ] **Step 5: ws_stream 下发检索帧**

`api/ws_stream.py` 的 `feed` 增加分支：

```python
        if kind == "retrieval":
            return self._message({"type": "retrieval", "hits": event.get("hits", [])})
```

`build_chat_response` 里把检索命中并入 `events`（供历史/面板一次性显示）：

```python
        for hit in (answer.retrieval or []):
            events.append(AgentEvent(id=uuid4().hex, type="retrieval", agent=AGENT_NAME,
                                     content=str(hit.get("title", "")),
                                     metadata={"note_id": hit.get("id"), "score": hit.get("score")},
                                     timestamp=now))
```

`AgentEvent.type` 联合里加 `'retrieval'`（`ui/src/lib/types.ts` 同步）。

- [ ] **Step 6: 跑全量 + 前端类型检查**

```bash
cd backend && python -X utf8 -m pytest tests -q
cd ../ui && npx tsc -b
```
Expected: 后端全绿；tsc 无输出

- [ ] **Step 7: 提交**

```bash
git add backend/agent backend/api/ws_stream.py backend/tests ui/src/lib/types.ts
git commit -m "feat: 检索节点接入建图并透出 retrieval 事件帧"
```

---

### Task 2.3: 措辞与面板文案中性化

**Files:**
- Modify: `backend/api/ws_stream.py`、`backend/agent/tools/notes.py`、`ui/src/components/graph-trace.tsx`、`ui/src/components/tool-list.tsx`、`ui/src/components/agent-panel.tsx`、`ui/src/pages/Dashboard.tsx`、`README.md`、`docs/PROGRESS.md`
- Test: `cd ui && npm run build`

**Interfaces:**
- Consumes: 无
- Produces: 面板分区标题 `执行节点 / 笔记检索命中 / 工具 / 护栏 / 上下文 / 运行输出`；节点标签显示原始节点名；工具分组标签 `笔记检索 / 天气 / 菜谱 / 新闻 / 用户数据`

- [ ] **Step 1: 后端文案**

`api/ws_stream.py`：

```python
AGENT_DESCRIPTION = "LangGraph 单代理，工具调用 + 笔记检索"
```

`agent/tools/notes.py` 的工具说明去掉夸张表述（保留参数语义）：

```python
    """检索我的笔记，按相关度返回标题、标签与正文片段"""
    """新建一条属于当前用户的笔记（标题必填，标签为自由文本，最多 50 字）"""
```

- [ ] **Step 2: 前端去掉中文美化映射**

`ui/src/components/graph-trace.tsx`：删除 `NODE_LABELS` 与 `nodeLabel()`，列表项直接渲染 `node`；
新增"笔记检索命中"分区组件（同文件导出 `RetrievalHits`）：

```tsx
export function RetrievalHits({ hits }: { hits: RetrievalHit[] }) {
  if (!hits.length) return <div className="text-xs text-gray-500 italic">本轮无检索命中</div>;
  return (
    <ul className="space-y-1">
      {hits.map((hit) => (
        <li key={hit.id ?? hit.title} className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5">
          <div className="flex items-center gap-2">
            <span className="truncate text-xs font-medium text-gray-900">{hit.title}</span>
            <span className="ml-auto flex-shrink-0 text-[11px] text-gray-600">{hit.score.toFixed(2)}</span>
          </div>
          <p className="mt-0.5 line-clamp-2 text-[11px] text-gray-600">{hit.text}</p>
        </li>
      ))}
    </ul>
  );
}
```

`ui/src/lib/types.ts` 加 `export interface RetrievalHit { id?: string | null; title: string; score: number; text: string }`，
并把 `AgentEvent.type` 联合加上 `'retrieval'`。

`ui/src/components/tool-list.tsx` 分组标签改为 `笔记检索 / 天气 / 菜谱 / 新闻 / 用户数据`。
`ui/src/components/agent-panel.tsx` 分区标题改为上述中性名，并在"执行节点"下加"笔记检索命中"。

- [ ] **Step 3: Dashboard 处理 retrieval 帧**

`ui/src/pages/Dashboard.tsx` 的过程帧 switch 加：

```tsx
            case "retrieval":
              setRetrievalHits(Array.isArray(content.hits) ? content.hits : []);
              break;
```

状态 `const [retrievalHits, setRetrievalHits] = useState<RetrievalHit[]>([])`，
`handleSendMessage` 里与 `graphNodes` 一起清空，并作为 `retrievalHits` prop 传给两处 `AgentPanel`。

- [ ] **Step 4: 文档措辞**

`README.md`：把"自研 RAG"改为"笔记语义检索（ChromaDB + bge-small-zh）"；技术栈一节同步。
`docs/PROGRESS.md`：新增一节记录本次重构，并把旧条目里的"自研 RAG"改为中性表述。

- [ ] **Step 5: 构建校验 + 提交**

```bash
cd ui && npm run build
cd .. && git add -A README.md docs backend/api backend/agent/tools ui/src
git commit -m "refactor: 措辞与面板文案改为中性技术名，显示真实节点名"
```

---

### Task 2.4: e2e 脚本扩断言并实跑

**Files:**
- Modify: `backend/scripts/e2e_langgraph_check.py`

**Interfaces:**
- Consumes: `retrieval` 帧（Task 2.2）
- Produces: 两项新断言（检索帧出现、不调工具也能答对笔记内容）

- [ ] **Step 1: 在 `converse()` 里收集检索帧**

```python
@dataclass
class Turn:
    ...
    retrieval: List[Dict[str, Any]] = field(default_factory=list)
```

帧分支加：

```python
            elif kind == "retrieval":
                turn.retrieval = content.get("hits", [])
```

- [ ] **Step 2: 加两项断言（放在"代理能用检索工具查自己的笔记"之后）**

```python
    note_turn = await converse(token, user_id, conversation_id,
                               "我笔记里绿植多久浇一次水？不要调用工具，直接回答")
    check("前置检索帧带命中", bool(note_turn.retrieval),
          f"hits={[(h.get('title'), round(h.get('score', 0), 2)) for h in note_turn.retrieval][:3]}")
    check("不调工具也能答对笔记内容",
          "两周" in note_turn.text and not note_turn.tool_calls,
          f"calls={note_turn.tool_calls} 答={note_turn.text[:50]}")
```

- [ ] **Step 3: 实跑**

```bash
cd backend && python -X utf8 scripts/e2e_langgraph_check.py
```
Expected: 全部 PASS，退出码 0。若"不调工具"那条失败（模型仍调了 `search_my_notes`），
把该断言改成"`retrieval` 命中且答案含两周"，并在 `docs/PROGRESS.md` 记下模型行为差异，
不要为了让测试通过而删掉检索节点。

- [ ] **Step 4: 提交**

```bash
git add backend/scripts/e2e_langgraph_check.py
git commit -m "test: e2e 增加前置检索断言（检索帧与不依赖工具的召回）"
```

---

### Task 3.1: MCP 依赖降级并冒烟服务端

**Files:**
- Modify: `backend/requirements.txt`
- Test: 命令行冒烟（无新增离线用例）

**Interfaces:**
- Consumes: 无
- Produces: 环境为 fastmcp 3.4.7 + mcp 1.30.x + langchain-mcp-adapters 0.3.2，且 MCP 服务端在 8102 可用

- [ ] **Step 1: 换依赖**

```bash
cd backend && /c/Users/HONOR/.conda/envs/lg-aide/python.exe -m pip install \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple --only-binary :all: \
  "fastmcp>=3.4.7,<4" "mcp>=1.24,<2" langchain-mcp-adapters
/c/Users/HONOR/.conda/envs/lg-aide/python.exe -m pip check
```
Expected: `No broken requirements found`

- [ ] **Step 2: 服务端冒烟（工具名与参数不能变）**

```bash
cd backend && python -X utf8 mcp-serve/mcp_server.py > /tmp/mcp3.log 2>&1 &
sleep 25 && python -X utf8 -c "
import asyncio
from mcp import Client
async def main():
    async with Client('http://127.0.0.1:8102/mcp') as c:
        tools = (await c.list_tools()).tools
        print('count', len(tools))
        print(sorted(t.name for t in tools)[:5])
asyncio.run(main())
"
```
Expected: `count 29`，名字仍带 `weather_/news_/recipe_/user_data_` 前缀。若数量或名字变了，
先停下改服务端，不要继续下一步。

- [ ] **Step 3: requirements 记录约束组合**

```
# MCP 服务端与客户端的约束组合（改动前先跑 pip check）：
# fastmcp 3.4.7 要求 mcp>=1.24,<2，langchain-mcp-adapters 也要求 mcp<2；
# 不要升 fastmcp 4（要求 mcp>=2），否则与 adapters 无法共存，服务端也会因 mcp API 变化启动失败。
fastmcp>=3.4.7,<4
mcp>=1.24,<2
langchain-mcp-adapters>=0.3,<1
```

- [ ] **Step 4: 提交**

```bash
git add backend/requirements.txt
git commit -m "chore: MCP 依赖降级到 fastmcp 3.4.7 + mcp 1.x 以启用标准桥接"
```

---

### Task 3.2: 换成 langchain-mcp-adapters，删手写桥接

**Files:**
- Rewrite: `backend/agent/tools/mcp.py`
- Modify: `backend/agent/runtime.py`
- Delete: `backend/tests/test_mcp_bridge.py`
- Test: `backend/tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `MultiServerMCPClient`
- Produces: `async load_mcp_tools() -> list`（失败返回 `[]`）、`MCPConnection`（带 `aclose()`，供 runtime 持有）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_mcp_tools.py
"""MCP 装载走官方适配器；连不上时返回空列表，不能抛"""

import asyncio

import agent.tools.mcp as mcp_mod
from agent.tools.mcp import load_mcp_tools


def test_load_returns_list_and_never_raises(monkeypatch):
    tools = asyncio.run(load_mcp_tools())
    assert isinstance(tools, list)
    assert all(hasattr(t, "name") for t in tools)


def test_connection_failure_degrades_to_empty(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise OSError("connection refused")

    monkeypatch.setattr(mcp_mod, "MultiServerMCPClient", Boom)
    assert asyncio.run(load_mcp_tools()) == []


def test_tool_name_prefix_is_disabled(monkeypatch):
    captured = {}

    class Spy:
        def __init__(self, servers, **kwargs):
            captured.update(kwargs)

        async def get_tools(self):
            return []

    monkeypatch.setattr(mcp_mod, "MultiServerMCPClient", Spy)
    asyncio.run(load_mcp_tools())
    assert captured["tool_name_prefix"] is False
```

- [ ] **Step 2: 跑测试确认失败** → Expected: FAIL（`load_mcp_tools` 不存在）

- [ ] **Step 3: 重写 mcp.py**

```python
# backend/agent/tools/mcp.py
"""MCP 工具装载（官方适配器）

tool_name_prefix=False：服务端工具名已自带 weather_ / news_ / recipe_ / user_data_ 前缀，
再加服务名前缀只会让名字变长且与前端清单不一致。
"""

import logging
from typing import Any, Dict, List, Optional

from core.runtime_config import RuntimeConfig
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


def _client(url: Optional[str] = None) -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {"aide": {"transport": "streamable_http", "url": url or RuntimeConfig.MCP_SERVER_URL}},
        tool_name_prefix=False,
    )


async def load_mcp_tools(url: Optional[str] = None) -> List[Any]:
    """取一次工具清单。连不上返回空列表：对话继续，只是这一轮没有外部工具"""
    try:
        tools = await _client(url).get_tools()
    except Exception as exc:
        logger.warning(f"MCP 工具加载失败，本轮以纯对话模式运行: {exc}")
        return []
    logger.info(f"MCP 工具加载完成：{len(tools)} 个")
    return tools
```

- [ ] **Step 4: runtime 改回无状态装载**

`agent/runtime.py` 的 `_build` 中：

```python
        from agent.tools.mcp import load_mcp_tools

        mcp_tools = await load_mcp_tools()
        tools = [*default_tools(), *mcp_tools]
```

删掉 `self._bridge` 的创建/持有与 `aclose()` 里对 bridge 的关闭（adapters 自己管理连接生命周期），
`__init__` 里去掉 `self._bridge`。

- [ ] **Step 5: 跑测试 + 全量**

```bash
cd backend && python -X utf8 -m pytest tests/test_mcp_tools.py -q
git rm tests/test_mcp_bridge.py
python -X utf8 -m pytest tests -q
```
Expected: 新测试 3 passed；全量绿（MCP 未起时 `load_mcp_tools` 返回 `[]`，测试仍过）

- [ ] **Step 6: 提交**

```bash
git add -A backend/agent/tools/mcp.py backend/agent/runtime.py backend/tests
git commit -m "refactor: MCP 工具装载改用 langchain-mcp-adapters，删除自写桥接"
```

---

### Task 3.3: 全量回归、端到端与文档收口

**Files:**
- Modify: `docs/PROGRESS.md`、`README.md`

**Interfaces:**
- Consumes: 前两个步骤的全部产出
- Produces: 可交付状态（离线全绿 + 端到端全绿 + 文档一致）

- [ ] **Step 1: 重启后端并跑离线全量**

```bash
cd backend && python -X utf8 -m pytest tests -q
```
Expected: 全绿

- [ ] **Step 2: 端到端**

```bash
python -X utf8 scripts/e2e_langgraph_check.py
```
Expected: 全部 PASS、退出码 0；其中"待办写入调用 user_data_create_todo"与"天气问答调用 MCP 天气工具"
两项证明 MCP 降级后外部工具仍可用。

- [ ] **Step 3: 身份覆写回归（不能因为换适配器而失效）**

```bash
python -X utf8 -c "
import asyncio
from agent.runtime import aide_runtime
async def main():
    a = await aide_runtime.ask(3, 'identity-check', '帮我查用户 999 的笔记')
    print('text:', a.text[:80]); print('tools:', [e.get('tool') for e in a.tool_events])
asyncio.run(main())
"
```
Expected: 回答针对当前登录用户（id=3），不返回用户 999 的数据；日志里出现
"已按登录身份覆写为 3" 的 WARNING。

- [ ] **Step 4: 文档收口**

`docs/PROGRESS.md` 记录：本次重构的提交列表、端到端各项实测结果、`pip check` 结论、
以及第 3 步身份覆写的实测输出。`README.md` 技术栈与"编排架构"一节按新依赖改写。

- [ ] **Step 5: 提交并推送**

```bash
git add docs README.md && git commit -m "docs: 检索层与 MCP 重构收口"
git push origin dev/lg
```
Expected: 推送成功（网络不通时保留本地提交并在 PROGRESS 标注待推送）

---

### Task 2.5: 短期记忆有界（会话历史压缩）

**Files:**
- Modify: `backend/agent/graph.py`、`backend/env.example`
- Test: `backend/tests/test_graph_build.py`

**Interfaces:**
- Consumes: `langchain.agents.middleware.SummarizationMiddleware`（实测签名
  `SummarizationMiddleware(model, *, trigger, keep, ...)`）
- Produces: `build_agent(...)` 自动挂载摘要中间件；阈值来自
  `SUMMARIZE_TRIGGER_TOKENS`（默认 6000）与 `SUMMARIZE_KEEP_MESSAGES`（默认 8）

**实测依据**：该中间件在接近阈值时把较早消息压成摘要，保证 AI/Tool 消息成对不被拆散；
瞬时失败最多重试 3 次，仍失败则抛出而不是伪造摘要。

- [ ] **Step 1: 写失败测试**

```python
def test_summarization_middleware_is_registered(tmp_path, monkeypatch):
    """长会话必须有界：不压缩历史会让 token 随轮数线性膨胀"""
    agent = asyncio.run(build_agent(ScriptedModel(replies=[{"content": "在的"}]), tools=[]))
    nodes = list(agent.get_graph().nodes)

    assert any("summarization" in n.lower() for n in nodes), nodes
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -X utf8 -m pytest tests/test_graph_build.py -q`
Expected: FAIL（节点列表里没有 summarization 节点）

- [ ] **Step 3: 实现**

`agent/graph.py` 增加：

```python
def _summarization_middleware(model):
    """会话历史压缩：官方中间件，阈值可调"""
    from langchain.agents.middleware import SummarizationMiddleware

    trigger = int(os.getenv("SUMMARIZE_TRIGGER_TOKENS", "6000"))
    keep = int(os.getenv("SUMMARIZE_KEEP_MESSAGES", "8"))
    return SummarizationMiddleware(model, trigger=("tokens", trigger), keep=("messages", keep))
```

放进 `middleware` 列表（检索注入之后、护栏之前），文件顶部 `import os`。
`backend/env.example` 增补：

```env
# 短期记忆上限：会话历史超过该 token 数时把较早消息压成摘要，保留最近 N 条
SUMMARIZE_TRIGGER_TOKENS=6000
SUMMARIZE_KEEP_MESSAGES=8
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd backend && python -X utf8 -m pytest tests -q
git add backend/agent/graph.py backend/tests/test_graph_build.py backend/env.example
git commit -m "feat: 接入 SummarizationMiddleware 给短期记忆设上限"
```

---

### Task 2.6: 长期记忆（跨会话，按用户）

**Files:**
- Create: `backend/agent/memory.py`
- Modify: `backend/agent/graph.py`、`backend/agent/runtime.py`、`backend/agent/state.py`、
  `backend/agent/tools/notes.py`、`backend/env.example`
- Test: `backend/tests/test_agent_memory.py`

**Interfaces:**
- Consumes: `langgraph.store.sqlite.AsyncSqliteStore`、
  `langgraph.store.memory.IndexConfig(dims, embed, fields)`、`get_embeddings()`
- Produces:
  - `memory_path() -> str`（`MEMORY_DB`，默认 `data/lg-aide-memory.sqlite`）
  - `memory_namespace(user_id) -> tuple` → `("user", str(user_id), "memory")`
  - `build_memory_store()` 异步上下文管理器（带语义索引）
  - `build_memory_middleware(limit=3)` → `before_agent`，写 `state["memories"]`
  - `build_memory_injector()` → 异步 `wrap_model_call`，注入 `[长期记忆]` 块
  - `save_memory` 工具（`agent/tools/notes.py`），返回 `"已记住"`
  - `AideState.memories: List[Dict[str, Any]]`

**实测依据**：`aput/aget/asearch` 可用；必须用异步接口（同步 `put` 在事件循环里抛
`InvalidStateError`）；`asearch(("user","3","memory"), ...)` 不会返回 user 9 的条目。

- [ ] **Step 1: 写失败测试**

```python
"""长期记忆：跨会话记住用户的长期事实

与笔记的界限：笔记是用户自己写或明确要求写的资料（MySQL + Chroma，面板可见）；
记忆是助手从对话里沉淀的事实，只在图内注入。写入只由模型显式调 save_memory 决定，
不做每轮自动抽取（写放大与隐私都不可控）。
"""

import asyncio
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field as PField

from agent.context import UserContext
from agent.memory import (build_memory_injector, build_memory_middleware,
                          memory_namespace, memory_path)
from agent.state import AideState


class StubModel(BaseChatModel):
    reply: str = "好的"
    seen: list = PField(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "stub"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])


@pytest.fixture
def any_store(tmp_path):
    """真 store（临时文件 + 假向量），验证 aput/asearch 与命名空间隔离"""
    from contextlib import AsyncExitStack
    from langgraph.store.memory import IndexConfig
    from langgraph.store.sqlite import AsyncSqliteStore

    async def make():
        stack = AsyncExitStack()
        return await stack.enter_async_context(AsyncSqliteStore.from_conn_string(
            str(tmp_path / "mem.sqlite"),
            index=IndexConfig(dims=64, embed=DeterministicFakeEmbedding(size=64),
                              fields=["text"])))

    return make


def test_memory_path_honours_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_DB", str(tmp_path / "mem.sqlite"))
    assert memory_path().endswith("mem.sqlite")


def test_namespace_is_per_user():
    assert memory_namespace(3) == ("user", "3", "memory")
    assert memory_namespace(4) != memory_namespace(3)


def test_save_memory_tool_writes_into_user_namespace(any_store):
    from agent.tools.notes import save_memory

    async def run():
        store = await any_store()
        runtime = SimpleNamespace(context=UserContext(user_id=3), store=store)
        out = await save_memory.ainvoke({"text": "用户在做安卓开发", "runtime": runtime})
        items = await store.asearch(memory_namespace(3), limit=5)
        return out, [i.value["text"] for i in items]

    out, texts = asyncio.run(run())
    assert "已记住" in out and "用户在做安卓开发" in texts


def test_memory_search_is_injected_but_not_persisted(any_store):
    async def run():
        store = await any_store()
        await store.aput(memory_namespace(3), "job", {"text": "用户在做安卓开发"})
        model = StubModel(reply="你在做安卓开发")
        agent = create_agent(model, [],
                             middleware=[build_memory_middleware(limit=3),
                                         build_memory_injector()],
                             state_schema=AideState, context_schema=UserContext,
                             store=store, name="Aide")
        state = await agent.ainvoke({"messages": [HumanMessage(content="我是做什么的？")]},
                                    context=UserContext(user_id=3))
        return model.seen[0], state

    seen, state = asyncio.run(run())

    assert any("长期记忆" in str(m.content) for m in seen)              # 模型看到了
    assert not any("长期记忆" in str(m.content) for m in state["messages"])   # 不进历史


def test_other_users_memories_are_not_visible(any_store):
    async def run():
        store = await any_store()
        await store.aput(memory_namespace(9), "city", {"text": "用户住在成都"})
        model = StubModel(reply="不知道")
        agent = create_agent(model, [],
                             middleware=[build_memory_middleware(limit=3), build_memory_injector()],
                             state_schema=AideState, context_schema=UserContext,
                             store=store, name="Aide")
        await agent.ainvoke({"messages": [HumanMessage(content="我住在哪")]},
                            context=UserContext(user_id=3))
        return model.seen[0]

    seen = asyncio.run(run())
    assert not any("成都" in str(m.content) for m in seen)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -X utf8 -m pytest tests/test_agent_memory.py -q`
Expected: FAIL（`agent.memory` 不存在）

- [ ] **Step 3: 实现 memory.py**

```python
"""长期记忆：LangGraph Store + 语义索引

不引新数据库（SQLite 一个文件）、不引新模型（复用本地 bge）。
必须用异步接口：同步 put 在事件循环里会抛 InvalidStateError（实测）。
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from langchain.agents.middleware import before_agent, wrap_model_call
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AideState

logger = logging.getLogger(__name__)

DEFAULT_PATH = "data/lg-aide-memory.sqlite"
MEMORY_NAME = "user_memory"
INJECT_NAME = "memory_context"
MAX_LIMIT = 10


def memory_path() -> str:
    return os.getenv("MEMORY_DB", DEFAULT_PATH)


def memory_namespace(user_id: Any) -> tuple:
    return ("user", str(user_id), "memory")


@asynccontextmanager
async def build_memory_store() -> AsyncIterator[Any]:
    from langgraph.store.memory import IndexConfig
    from langgraph.store.sqlite import AsyncSqliteStore

    from core.retrieval.embeddings import get_embeddings

    path = memory_path()
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    embeddings = get_embeddings()
    index = IndexConfig(dims=getattr(embeddings, "vector_dimension", 512) or 512,
                        embed=embeddings, fields=["text"])
    async with AsyncSqliteStore.from_conn_string(path, index=index) as store:
        logger.info(f"长期记忆存储就绪: {path}")
        yield store


def _last_human_text(messages: List[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content or "").strip()
    return ""


def build_memory_middleware(limit: int = 3):
    @before_agent(state_schema=AideState, name=MEMORY_NAME)
    async def recall(state, runtime):
        user_id = getattr(getattr(runtime, "context", None), "user_id", None)
        store = getattr(runtime, "store", None)
        query = _last_human_text(state.get("messages", []) or [])
        if user_id is None or store is None or not query:
            return {"memories": []}

        try:
            items = await store.asearch(memory_namespace(user_id), query=query,
                                        limit=max(1, min(limit, MAX_LIMIT)))
        except Exception as exc:
            logger.warning(f"长期记忆检索不可用，本轮不注入: {exc}")
            return {"memories": []}

        return {"memories": [{"key": item.key, "text": str(item.value.get("text", ""))}
                             for item in items]}

    return recall


def build_memory_injector():
    @wrap_model_call(state_schema=AideState, name=INJECT_NAME)
    async def inject(request, handler):
        memories: List[Dict[str, Any]] = request.state.get("memories") or []
        if not memories:
            return await handler(request)

        block = "\n".join(f"- {memory['text']}" for memory in memories)
        message = SystemMessage(content=f"[长期记忆] 关于该用户的既有事实：\n{block}")
        messages = list(request.messages)
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                messages.insert(index, message)
                break
        else:
            messages.append(message)
        return await handler(request.override(messages=messages))

    return inject
```

`AideState` 增加 `memories: List[Dict[str, Any]]`。

`agent/tools/notes.py` 追加工具（身份与 store 都来自 runtime，模型无法指定别人）：

```python
@tool
async def save_memory(text: str, runtime: ToolRuntime[UserContext] = None) -> str:
    """记住一条关于用户的长期事实或偏好（跨会话有效；只存长期有效内容，一次性问题不要存）"""
    user_id = _user_id(runtime)
    store = getattr(runtime, "store", None)
    if user_id is None or store is None:
        return "缺少用户身份或记忆存储，未能记住"

    from agent.memory import memory_namespace

    await store.aput(memory_namespace(user_id), f"mem_{uuid4().hex[:8]}", {"text": text})
    return "已记住"
```

（`notes.py` 顶部需要 `from uuid import uuid4`。）

- [ ] **Step 4: 建图与运行时接线**

`build_agent` 增加 `store` 参数并透传给 `create_agent`，middleware 顺序：
检索 → 记忆检索 → 摘要 → 注入（笔记）→ 注入（记忆）→ 身份 → 护栏。
实际实现按钩子类型排：`before_agent` 两个（笔记、记忆）、`wrap_model_call` 两个注入器、
`SummarizationMiddleware`、`wrap_tool_call` 身份、`before_model` 护栏。

`AideRuntime._build` 用同一个 `AsyncExitStack` 打开 `build_memory_store()`，
把 store 传给 `build_agent`；`aclose()` 统一关闭。`default_tools()` 加入 `save_memory`。

`env.example` 增补：

```env
# 长期记忆（跨会话）：LangGraph Store 的 SQLite 文件，带语义索引
MEMORY_DB=./data/lg-aide-memory.sqlite
```

系统提示词补一条：`save_memory` 只用于长期有效的事实；写资料用 `save_note`。

- [ ] **Step 5: 跑测试 + 全量**

```bash
cd backend && python -X utf8 -m pytest tests/test_agent_memory.py -q
python -X utf8 -m pytest tests -q
```
Expected: 记忆 6 项通过；全量绿

- [ ] **Step 6: 端到端补跨会话断言**

`scripts/e2e_langgraph_check.py` 里，在 `save_memory` 相关一轮之后，**换一个新的
conversation_id** 提问"我是做什么的？"，断言回答里出现上一会话记下的事实、且没有调用笔记工具：

```python
    cross = await converse(token, user_id, f"{conversation_id}-next", "我是做什么工作的？")
    check("跨会话长期记忆生效", "安卓" in cross.text and not cross.tool_calls,
          f"calls={cross.tool_calls} 答={cross.text[:50]}")
```

```bash
python -X utf8 scripts/e2e_langgraph_check.py
git add backend/agent backend/tests/test_agent_memory.py backend/scripts backend/env.example docs
git commit -m "feat: 长期记忆（LangGraph Store + 语义索引，按用户命名空间隔离）"
```

---

---

## 验收清单（全部满足才算完成）

1. `pytest backend/tests -q` 全绿，且 `tests/test_rag_recall.py` 的 8 组查询断言与迁移前一致。
2. `pip check` 干净；`requirements.txt` 里同时写明 fastmcp/mcp/adapters 的约束组合。
3. 仓库中不再存在自写 Chroma 封装（`core/vector_core` 已删除）与自写 MCP schema 桥接。
4. `create_agent` 编译出的图里能看到 `note_retrieval.before_agent` 节点。
5. 端到端脚本全部通过，含"不调工具也能答对笔记内容"。
6. UI 与文档无"自研/卖点"类措辞，节点标签显示真实节点名。
7. 短期记忆有界：长会话触发 `SummarizationMiddleware` 后历史不再无限膨胀。
8. 长期记忆跨会话生效：新会话未调工具即答出上一会话记下的事实，且其他用户看不到。
