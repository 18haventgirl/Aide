"""
用户服务

用户身份统一来自本地 users 表。此前取自公共演示站 JSONPlaceholder（只有 10 个假用户），
导致第 11 个之后注册的账号被 validate_user_exists 判为"用户不存在"，
笔记/待办/偏好全都写不进去。
"""

from typing import Optional, List

from sqlalchemy import or_

from ..models.user_account import UserAccount


class UserService:
    """
    用户服务类

    提供用户相关的业务逻辑，数据来源为本地 users 表
    """

    def __init__(self, db_client=None):
        """
        初始化用户服务

        Args:
            db_client: 数据库客户端；缺省时在首次使用时取全局单例，
                       避免与 service_manager 形成导入环
        """
        self._db_client = db_client

    @property
    def db_client(self):
        if self._db_client is None:
            from service.service_manager import service_manager
            self._db_client = service_manager.get_db_client()
        return self._db_client

    def get_user(self, user_id: int) -> Optional[UserAccount]:
        """
        获取用户信息

        Args:
            user_id: 用户ID

        Returns:
            用户对象或None
        """
        try:
            with self.db_client.get_session() as session:
                user = session.query(UserAccount).filter(UserAccount.id == user_id).first()
                if user:
                    session.expunge(user)
                return user
        except Exception as e:
            print(f"获取用户信息失败: {e}")
            return None

    def get_all_users(self) -> List[UserAccount]:
        """
        获取所有用户信息

        Returns:
            用户列表
        """
        try:
            with self.db_client.get_session() as session:
                users = session.query(UserAccount).order_by(UserAccount.id).all()
                for user in users:
                    session.expunge(user)
                return users
        except Exception as e:
            print(f"获取所有用户失败: {e}")
            return []

    def validate_user_exists(self, user_id: int) -> bool:
        """
        验证用户是否存在

        Args:
            user_id: 用户ID

        Returns:
            是否存在
        """
        return self.get_user(user_id) is not None

    def search_users_by_name(self, name: str) -> List[UserAccount]:
        """
        按用户名或展示名模糊搜索用户

        Args:
            name: 搜索的关键字

        Returns:
            匹配的用户列表
        """
        if not name:
            return []
        pattern = f"%{name}%"
        try:
            with self.db_client.get_session() as session:
                users = session.query(UserAccount).filter(
                    or_(UserAccount.name.like(pattern), UserAccount.username.like(pattern))
                ).all()
                for user in users:
                    session.expunge(user)
                return users
        except Exception as e:
            print(f"搜索用户失败: {e}")
            return []

    def search_users_by_email(self, email: str) -> List[UserAccount]:
        """
        根据邮箱搜索用户

        Args:
            email: 搜索的邮箱

        Returns:
            匹配的用户列表
        """
        if not email:
            return []
        try:
            with self.db_client.get_session() as session:
                users = session.query(UserAccount).filter(UserAccount.email == email).all()
                for user in users:
                    session.expunge(user)
                return users
        except Exception as e:
            print(f"搜索用户邮箱失败: {e}")
            return []

    def get_user_summary(self, user_id: int) -> dict:
        """
        获取用户概要信息

        Args:
            user_id: 用户ID

        Returns:
            用户概要信息字典（用户不存在时为空字典）
        """
        user = self.get_user(user_id)
        if not user:
            return {}

        return {
            'id': user.id,
            'name': user.name,
            'username': user.username,
            'email': user.email,
        }
