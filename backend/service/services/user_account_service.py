"""本地账号服务

users 表的读写。密码哈希由调用方（auth 层）完成，这里只管存与取，
避免 auth ↔ service 循环导入。
"""

import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError

from core.database_core import DatabaseClient

from ..models.user_account import UserAccount

logger = logging.getLogger(__name__)


class DuplicateUserError(Exception):
    """用户名或邮箱已被占用"""

    def __init__(self, field: str):
        self.field = field
        super().__init__(f"{field} 已被注册")


class UserAccountService:
    """已注册账号的存取"""

    def __init__(self, db_client: Optional[DatabaseClient] = None):
        if db_client is None:
            # 复用全局已初始化的客户端；裸建 DatabaseClient() 没 initialize()，
            # 取 session 时会直接抛"数据库客户端未初始化"
            from service.service_manager import service_manager
            db_client = service_manager.get_db_client()
        self.db_client = db_client

    def create_user(self, username: str, email: str, password_hash: str,
                    name: str = '') -> UserAccount:
        """创建账号；用户名或邮箱重复时抛 DuplicateUserError"""
        with self.db_client.get_session() as session:
            if session.query(UserAccount).filter(UserAccount.username == username).first():
                raise DuplicateUserError('用户名')
            if session.query(UserAccount).filter(UserAccount.email == email).first():
                raise DuplicateUserError('邮箱')

            account = UserAccount(
                username=username,
                email=email,
                password_hash=password_hash,
                name=name or username,
            )
            session.add(account)
            try:
                session.commit()
            except IntegrityError as e:
                # 上面的查重与插入之间可能有并发，唯一索引兜底
                session.rollback()
                orig = str(e.orig or '')
                if 'email' in orig:
                    raise DuplicateUserError('邮箱') from e
                raise DuplicateUserError('用户名') from e

            session.refresh(account)
            session.expunge(account)
            logger.info(f"已创建账号 {account.username} (id={account.id})")
            return account

    def get_by_username(self, username: str) -> Optional[UserAccount]:
        return self._first_by(UserAccount.username, username)

    def get_by_email(self, email: str) -> Optional[UserAccount]:
        return self._first_by(UserAccount.email, email)

    def get_by_id(self, user_id: int) -> Optional[UserAccount]:
        with self.db_client.get_session() as session:
            account = session.query(UserAccount).filter(UserAccount.id == user_id).first()
            if account:
                session.expunge(account)
            return account

    def _first_by(self, column, value: str) -> Optional[UserAccount]:
        with self.db_client.get_session() as session:
            account = session.query(UserAccount).filter(column == value).first()
            if account:
                session.expunge(account)
            return account
