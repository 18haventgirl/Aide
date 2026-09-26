"""
笔记服务

管理用户笔记，包括创建、更新、删除、搜索等操作
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from core.database_core import DatabaseClient
from core.retrieval.documents import documents_to_rows, note_document
from core.retrieval.store import note_store
from core.retrieval.config import VectorConfig
from ..models.note import Note, InvalidTagError
from .user_service import UserService


def _search_rows(store, query: str, threshold: float, limit: int = 10) -> List[Dict[str, Any]]:
    """向量检索 + REST 形状转换，一处定义，测试也打这一层"""
    return documents_to_rows(store.similarity_search_with_relevance_scores(query, k=limit),
                             threshold)


class NoteService:
    """
    笔记服务类
    
    管理用户的笔记数据，并同步到向量数据库
    """
    
    def __init__(self, db_client: Optional[DatabaseClient] = None):
        """
        初始化笔记服务
        
        Args:
            db_client: 数据库客户端，如果未提供则创建新实例
        """
        self.db_client = db_client or DatabaseClient()
        self.user_service = UserService()

        # 向量配置：读不到就退回"只存 MySQL、不做语义检索"，不影响笔记本身
        try:
            self.vector_config = VectorConfig.from_env()
        except Exception as e:
            print(f"警告：向量配置读取失败，笔记检索退回关键词方式: {e}")
            self.vector_config = None
        
        # 确保数据库初始化
        if not self.db_client._initialized:
            self.db_client.initialize()
    
    def create_note(self, user_id: int, title: str, content: str = '', 
                   tag: Optional[str] = None, status: str = 'draft') -> Optional[Note]:
        """
        创建新笔记
        
        Args:
            user_id: 用户ID
            title: 笔记标题
            content: 笔记内容
            tag: 笔记标签（单个标签）
            status: 笔记状态
            
        Returns:
            创建的笔记对象或None
        """
        try:
            # 验证用户是否存在
            if not self.user_service.validate_user_exists(user_id):
                print(f"用户 {user_id} 不存在")
                return None
            
            # 验证标签
            tag = Note.normalize_tag(tag)
            if tag:
                Note.validate_tag(tag)
            
            with self.db_client.get_session() as session:
                note = Note(
                    user_id=user_id,
                    title=title,
                    content=content,
                    tag=tag,
                    status=status
                )
                
                session.add(note)
                session.commit()
                session.refresh(note)
                
                # 写入向量索引（无正文时 _index_note 内部会跳过）
                self._index_note(note)
                
                return note
                
        except InvalidTagError as e:
            print(f"创建笔记失败 - 标签验证错误: {e}")
            return None
        except Exception as e:
            print(f"创建笔记失败: {e}")
            return None
    
    def _index_note(self, note: Note) -> None:
        """写入或覆盖向量索引

        Chroma 按 id 做 upsert，更新笔记不需要"先删再加"。
        没有正文的笔记不进索引：空文档只会污染检索结果（与迁移前行为一致）。
        """
        try:
            if not self.vector_config or not (getattr(note, 'content', '') or ''):
                return
            if getattr(note, 'id', None) is None or getattr(note, 'user_id', None) is None:
                return
            note_store(note.user_id).add_documents([note_document(note)])
            print(f"笔记 {note.id} 已写入向量索引")
        except Exception as e:
            print(f"笔记向量索引写入失败（不影响数据库已保存）: {e}")

    def _drop_index(self, user_id: int, note_id: int) -> None:
        """从向量索引里移除一条笔记"""
        try:
            if not self.vector_config:
                return
            note_store(user_id).delete(ids=[f"note_{note_id}"])
        except Exception as e:
            print(f"笔记向量索引删除失败: {e}")
    
    def get_note(self, note_id: int) -> Optional[Note]:
        """
        获取笔记
        
        Args:
            note_id: 笔记ID
            
        Returns:
            笔记对象或None
        """
        try:
            with self.db_client.get_session() as session:
                note = session.query(Note).filter(Note.id == note_id).first()
                return note
                
        except Exception as e:
            print(f"获取笔记失败: {e}")
            return None
    
    def get_user_notes(self, user_id: int, status: Optional[str] = None, 
                      tag: Optional[str] = None, search_query: Optional[str] = None,
                      limit: int = 50, offset: int = 0) -> List[Note]:
        """
        获取用户的笔记列表
        
        Args:
            user_id: 用户ID
            status: 笔记状态筛选
            tag: 标签筛选
            search_query: 搜索关键词
            limit: 限制数量
            offset: 偏移量
            
        Returns:
            笔记列表
        """
        try:
            with self.db_client.get_session() as session:
                query = session.query(Note).filter(Note.user_id == user_id)
                
                if status:
                    query = query.filter(Note.status == status)
                    
                if tag:
                    query = query.filter(Note.tag == tag)
                    
                if search_query:
                    search_term = f"%{search_query}%"
                    query = query.filter(
                        or_(
                            Note.title.like(search_term),
                            Note.content.like(search_term)
                        )
                    )
                
                notes = query.order_by(Note.last_updated.desc()).offset(offset).limit(limit).all()
                return notes
                
        except Exception as e:
            print(f"获取用户笔记失败: {e}")
            return []
    
    def update_note(self, note_id: int, title: Optional[str] = None, content: Optional[str] = None,
                   tag: Optional[str] = None, status: Optional[str] = None) -> Optional[Note]:
        """
        更新笔记
        
        Args:
            note_id: 笔记ID
            title: 新标题
            content: 新内容
            tag: 新标签
            status: 新状态
            
        Returns:
            更新后的笔记对象或None
        """
        try:
            with self.db_client.get_session() as session:
                note = session.query(Note).filter(Note.id == note_id).first()
                
                if not note:
                    return None
                
                # 验证标签（空串表示清除标签）
                if tag is not None:
                    tag = Note.normalize_tag(tag)
                    if tag:
                        Note.validate_tag(tag)
                
                # 更新字段
                if title is not None:
                    note.title = title
                if content is not None:
                    note.content = content
                if tag is not None:
                    note.tag = tag
                if status is not None:
                    note.status = status
                
                session.commit()
                session.refresh(note)
                
                # 更新向量索引：Chroma 按 id upsert
                self._index_note(note)
                
                return note
                
        except InvalidTagError as e:
            print(f"更新笔记失败 - 标签验证错误: {e}")
            return None
        except Exception as e:
            print(f"更新笔记失败: {e}")
            return None
    
    def delete_note(self, note_id: int) -> bool:
        """
        删除笔记
        
        Args:
            note_id: 笔记ID
            
        Returns:
            是否删除成功
        """
        try:
            with self.db_client.get_session() as session:
                note = session.query(Note).filter(Note.id == note_id).first()
                
                if note:
                    # 先从向量索引里移除
                    self._drop_index(note.user_id, note.id)
                    
                    # 再从关系数据库中删除
                    session.delete(note)
                    session.commit()
                    return True
                return False
                
        except Exception as e:
            print(f"删除笔记失败: {e}")
            return False
    
    def search_notes(self, user_id: int, query: str, search_in_content: bool = True,
                    search_in_tags: bool = True, tag: Optional[str] = None, 
                    status: Optional[str] = None, limit: int = 20) -> List[Note]:
        """
        搜索笔记
        
        Args:
            user_id: 用户ID
            query: 搜索关键词
            search_in_content: 是否搜索内容
            search_in_tags: 是否搜索标签
            limit: 限制数量
            
        Returns:
            匹配的笔记列表
        """
        try:
            with self.db_client.get_session() as session:
                conditions = [Note.user_id == user_id]
                
                # 构建搜索条件
                search_conditions = []
                
                # 搜索标题
                search_conditions.append(Note.title.contains(query))
                
                # 搜索内容
                if search_in_content:
                    search_conditions.append(Note.content.contains(query))
                
                # 搜索标签
                if search_in_tags:
                    search_conditions.append(Note.tag.contains(query))
                
                # 组合搜索条件
                if search_conditions:
                    conditions.append(or_(*search_conditions))
                
                # 添加标签过滤
                if tag:
                    conditions.append(Note.tag == tag)
                
                # 添加状态过滤
                if status:
                    conditions.append(Note.status == status)
                
                notes = session.query(Note).filter(and_(*conditions)).order_by(
                    Note.last_updated.desc()
                ).limit(limit).all()
                
                return notes
                
        except Exception as e:
            print(f"搜索笔记失败: {e}")
            return []
    
    def get_notes_by_tag(self, user_id: int, tag: str, limit: int = 20) -> List[Note]:
        """
        根据标签获取笔记
        
        Args:
            user_id: 用户ID
            tag: 标签
            limit: 限制数量
            
        Returns:
            匹配的笔记列表
        """
        try:
            with self.db_client.get_session() as session:
                notes = session.query(Note).filter(
                    Note.user_id == user_id,
                    Note.tag == tag
                ).order_by(Note.last_updated.desc()).limit(limit).all()
                
                return notes
                
        except Exception as e:
            print(f"根据标签获取笔记失败: {e}")
            return []
    
    def get_user_tags(self, user_id: int) -> List[str]:
        """
        获取用户使用的所有标签
        
        Args:
            user_id: 用户ID
            
        Returns:
            标签列表
        """
        try:
            with self.db_client.get_session() as session:
                tags = session.query(Note.tag).filter(
                    Note.user_id == user_id,
                    Note.tag.isnot(None),
                    Note.tag != ''
                ).distinct().all()
                
                return [tag[0] for tag in tags if tag[0]]
                
        except Exception as e:
            print(f"获取用户标签失败: {e}")
            return []
    
    def get_notes_statistics(self, user_id: int) -> Dict[str, Any]:
        """
        获取笔记统计信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            统计信息字典
        """
        try:
            with self.db_client.get_session() as session:
                # 总笔记数
                total_notes = session.query(Note).filter(Note.user_id == user_id).count()
                
                # 按状态统计
                status_counts = {}
                status_results = session.query(Note.status, func.count(Note.id)).filter(
                    Note.user_id == user_id
                ).group_by(Note.status).all()
                
                for status, count in status_results:
                    status_counts[status] = count
                
                # 按标签统计
                tag_counts = {}
                tag_results = session.query(Note.tag, func.count(Note.id)).filter(
                    Note.user_id == user_id,
                    Note.tag.isnot(None),
                    Note.tag != ''
                ).group_by(Note.tag).all()
                
                for tag, count in tag_results:
                    tag_counts[tag] = count
                
                # 最近更新的笔记
                recent_notes = session.query(Note).filter(
                    Note.user_id == user_id
                ).order_by(Note.last_updated.desc()).limit(5).all()
                
                # 获取所有标签
                all_tags = self.get_user_tags(user_id)
                
                return {
                    'total_notes': total_notes,
                    'status_counts': status_counts,
                    'tag_counts': tag_counts,
                    'recent_notes': [
                        {
                            'id': note.id,
                            'title': note.title,
                            'tag': note.tag,
                            'last_updated': note.last_updated.isoformat() if hasattr(note, 'last_updated') and getattr(note, 'last_updated', None) else None
                        }
                        for note in recent_notes
                    ],
                    'total_tags': len(all_tags),
                    'tags': all_tags
                }
                
        except Exception as e:
            print(f"获取笔记统计失败: {e}")
            return {}
    
    def archive_note(self, note_id: int) -> bool:
        """
        归档笔记
        
        Args:
            note_id: 笔记ID
            
        Returns:
            是否归档成功
        """
        return self.update_note(note_id, status='archived') is not None
    
    def publish_note(self, note_id: int) -> bool:
        """
        发布笔记
        
        Args:
            note_id: 笔记ID
            
        Returns:
            是否发布成功
        """
        return self.update_note(note_id, status='published') is not None
    
    def get_note_summary(self, note_id: int) -> Optional[Dict[str, Any]]:
        """
        获取笔记摘要信息
        
        Args:
            note_id: 笔记ID
            
        Returns:
            笔记摘要字典或None
        """
        note = self.get_note(note_id)
        if not note:
            return None
        
        return {
            'id': note.id,
            'user_id': note.user_id,
            'title': note.title,
            'summary': note.get_summary(),
            'tag': note.tag,
            'status': note.status,
            'created_at': note.created_at.isoformat() if hasattr(note, 'created_at') and getattr(note, 'created_at', None) else None,
            'last_updated': note.last_updated.isoformat() if hasattr(note, 'last_updated') and getattr(note, 'last_updated', None) else None
        }
    
    def search_notes_by_vector(self, user_id: int, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        使用向量数据库搜索笔记
        
        Args:
            user_id: 用户ID
            query: 搜索查询
            limit: 限制数量
            
        Returns:
            搜索结果列表
        """
        try:
            if not self.vector_config:
                return []
            store = note_store(user_id)
        except Exception as e:
            print(f"向量库不可用，本次检索退回空结果: {e}")
            return []

        try:
            return _search_rows(store, query, self.vector_config.similarity_threshold, limit)
        except Exception as e:
            print(f"向量搜索失败: {e}")
            return []
    
    def close(self):
        """关闭数据库连接"""
        if self.db_client:
            self.db_client.close() 