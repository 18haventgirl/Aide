"""本地账号数据模型

原项目的"用户"来自公共演示站 JSONPlaceholder（只有 10 个假用户，密码还写死在代码里），
无法支撑真正的注册/登录，所以账号数据落在自己的 users 表。
"""

from sqlalchemy import Column, Integer, String, Index
from core.database_core import BaseModel


class UserAccount(BaseModel):
    """已注册的用户账号"""

    __tablename__ = 'users'

    # 登录名
    username = Column(String(80), nullable=False, unique=True, index=True, comment='登录用户名')

    # 邮箱
    email = Column(String(120), nullable=False, unique=True, index=True, comment='邮箱')

    # bcrypt 哈希后的密码，绝不存明文
    password_hash = Column(String(255), nullable=False, comment='密码哈希(bcrypt)')

    # 展示名
    name = Column(String(120), default='', comment='显示名称')

    __table_args__ = (
        Index('idx_users_username', 'username'),
        Index('idx_users_email', 'email'),
    )

    def __repr__(self):
        return f"<UserAccount(id={getattr(self, 'id', None)}, username='{self.username}')>"

    def to_public_dict(self):
        """对外返回的用户信息（不含密码哈希）"""
        data = super().to_dict()
        data.pop('password_hash', None)
        return data
