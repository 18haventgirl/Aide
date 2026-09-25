"""
笔记数据模型
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from core.database_core import BaseModel


class InvalidTagError(Exception):
    """标签验证异常"""
    pass


class Note(BaseModel):
    """
    笔记模型
    
    存储用户的笔记内容，用户信息来自本地 users 表
    """
    __tablename__ = 'notes'
    
    # 标签长度上限（与 tag 列的 String(50) 对齐）
    TAG_MAX_LENGTH = 50
    
    # 用户ID（关联 users.id）
    user_id = Column(Integer, nullable=False, comment='用户ID（关联users表）')
    
    # 笔记标题
    title = Column(String(200), nullable=False, comment='笔记标题')
    
    # 笔记内容
    content = Column(Text, comment='笔记内容')
    
    # 笔记标签（单个标签，自由文本）
    tag = Column(String(50), comment='笔记标签')
    
    # 笔记状态（草稿、已发布、已归档等）
    status = Column(String(20), default='draft', comment='笔记状态')
    
    # 最后更新时间
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now(), comment='最后更新时间')
    
    # 创建索引优化查询
    __table_args__ = (
        Index('idx_notes_user_id', 'user_id'),
        Index('idx_notes_title', 'title'),
        Index('idx_notes_status', 'status'),
        Index('idx_notes_tag', 'tag'),
        Index('idx_notes_last_updated', 'last_updated'),
        Index('idx_notes_user_status', 'user_id', 'status'),
    )
    
    def __repr__(self):
        return f"<Note(id={self.id}, user_id={self.user_id}, title='{self.title[:30]}...')>"
    
    def to_dict(self):
        """转换为字典格式"""
        return super().to_dict()
    
    @classmethod
    def normalize_tag(cls, tag):
        """把标签规整成去首尾空白的字符串，空标签返回 None"""
        if tag is None:
            return None
        cleaned = str(tag).strip()
        return cleaned or None

    @classmethod
    def validate_tag(cls, tag):
        """校验标签

        标签是自由文本（这个项目面向中文用户，写死的英文枚举会让笔记根本存不进去），
        只限制非空、单行和长度不超过列宽。
        """
        if tag is None:
            return True  # 允许空标签

        if not isinstance(tag, str):
            raise InvalidTagError(f"标签必须是字符串，当前类型: {type(tag).__name__}")

        if len(tag) > cls.TAG_MAX_LENGTH:
            raise InvalidTagError(
                f"标签过长（{len(tag)} 字符），最多 {cls.TAG_MAX_LENGTH} 个字符"
            )

        if any(ch in tag for ch in ('\n', '\r', '\t')):
            raise InvalidTagError("标签不能包含换行或制表符")

        return True
    
    @classmethod
    def create_from_dict(cls, data):
        """从字典创建实例"""
        tag = cls.normalize_tag(data.get('tag', ''))
        
        # 验证标签
        if tag:
            cls.validate_tag(tag)
        
        return cls(
            user_id=data.get('user_id'),
            title=data.get('title', ''),
            content=data.get('content', ''),
            tag=tag,
            status=data.get('status', 'draft')
        )
    
    def set_tag(self, tag):
        """设置标签"""
        tag = self.normalize_tag(tag)
        if tag:
            self.validate_tag(tag)
        self.tag = tag
    
    def get_tag(self):
        """获取标签"""
        return getattr(self, 'tag', None)
    
    def get_summary(self, max_length=100):
        """获取笔记摘要"""
        content_value = getattr(self, 'content', None)
        if not content_value:
            return ''
        
        # 移除多余的空白字符
        content = ' '.join(content_value.split())
        
        if len(content) <= max_length:
            return content
        
        return content[:max_length] + '...' 