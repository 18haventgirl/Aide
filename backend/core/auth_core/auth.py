"""
认证核心模块

提供JWT令牌生成、验证和用户认证相关功能
"""

import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Union

import bcrypt
from fastapi import HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from dotenv import load_dotenv

# 必须在读取下面的环境变量之前加载 .env：本模块在 main.py 里比 runtime_config、
# database_core 等会调 load_dotenv() 的模块更早被导入，否则 JWT_SECRET_KEY 会静默
# 退回代码里的默认值，.env 形同不存在。
# 这里显式给出 backend/.env 的绝对路径：load_dotenv() 的自动查找依赖调用方的文件位置，
# 用 python -c 或从其他目录启动时会找不到，导致不同进程用到不同的密钥。
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# JWT配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-here-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_DAYS = 7

# HTTP Bearer 安全方案
security = HTTPBearer()

logger = logging.getLogger(__name__)


class TokenData(BaseModel):
    """JWT令牌数据模型"""
    user_id: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None


class Token(BaseModel):
    """令牌响应模型"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_info: Dict[str, Any]


class UserClaims(BaseModel):
    """用户声明模型"""
    user_id: str
    username: str
    email: str
    exp: int
    iat: int


class AuthUtils:
    """认证工具类"""
    
    @staticmethod
    def _bcrypt_secret(password: str) -> bytes:
        """把任意长度密码压成固定长度再交给 bcrypt

        bcrypt 只接受 <=72 字节的输入，5.x 版本超长会直接抛异常（passlib 时代是静默截断）。
        先做 sha256 派生既不截断也不报错。
        """
        return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        验证密码
        
        Args:
            plain_password: 明文密码
            hashed_password: 哈希密码
            
        Returns:
            是否验证成功
        """
        try:
            return bcrypt.checkpw(
                AuthUtils._bcrypt_secret(plain_password), hashed_password.encode("utf-8")
            )
        except ValueError:
            # 存储的哈希格式不对（例如脏数据），按验证失败处理
            return False
    
    @staticmethod
    def get_password_hash(password: str) -> str:
        """
        获取密码哈希
        
        Args:
            password: 明文密码
            
        Returns:
            哈希密码
        """
        return bcrypt.hashpw(
            AuthUtils._bcrypt_secret(password), bcrypt.gensalt()
        ).decode("utf-8")
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """
        创建访问令牌
        
        Args:
            data: 要编码的数据
            expires_delta: 过期时间增量
            
        Returns:
            JWT令牌字符串
        """
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(days=JWT_ACCESS_TOKEN_EXPIRE_DAYS)
        
        to_encode.update({"exp": expire, "iat": datetime.utcnow()})
        encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> Optional[Dict[str, Any]]:
        """
        验证令牌
        
        Args:
            token: JWT令牌字符串
            
        Returns:
            解码后的数据或None
        """
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except JWTError:
            return None
    
    @staticmethod
    def decode_token(token: str) -> Optional[UserClaims]:
        """
        解码令牌
        
        Args:
            token: JWT令牌字符串
            
        Returns:
            用户声明对象或None
        """
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return UserClaims(**payload)
        except (JWTError, ValueError):
            return None
    
    @staticmethod
    def get_current_user_from_token(token: str) -> Optional[Dict[str, Any]]:
        """
        从令牌获取当前用户信息
        
        Args:
            token: JWT令牌字符串
            
        Returns:
            用户信息字典或None
        """
        payload = AuthUtils.verify_token(token)
        if payload is None:
            return None
        
        user_id = payload.get("user_id")
        if user_id is None:
            return None
        
        return {
            "user_id": user_id,
            "username": payload.get("username"),
            "email": payload.get("email")
        }
    
    @staticmethod
    def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        用户认证：查本地 users 表并校验 bcrypt 密码哈希

        Args:
            username: 用户名或邮箱
            password: 明文密码

        Returns:
            用户信息字典或None
        """
        from service.services.user_account_service import UserAccountService

        try:
            service = UserAccountService()
            account = service.get_by_username(username) or service.get_by_email(username)
        except Exception as e:
            logger.error(f"账号查询失败: {e}")
            return None

        if not account or not AuthUtils.verify_password(password, account.password_hash):
            # 用户不存在与密码错误返回同样的结果，避免用户名枚举
            return None

        return {
            "user_id": str(account.id),
            "username": account.username,
            "email": account.email,
            "name": account.name,
        }


class AuthService:
    """认证服务类"""
    
    def __init__(self):
        self.user_service = None
    
    def login(self, username: str, password: str) -> Optional[Token]:
        """
        用户登录
        
        Args:
            username: 用户名或邮箱
            password: 密码
            
        Returns:
            令牌对象或None
        """
        # 认证用户
        user = AuthUtils.authenticate_user(username, password)
        if not user:
            return None

        return self.issue_token(user)
    
    def register(self, username: str, email: str, password: str,
                 name: str = '') -> Token:
        """
        注册新账号并直接返回令牌

        Args:
            username: 用户名
            email: 邮箱
            password: 明文密码（只存 bcrypt 哈希）
            name: 展示名，缺省用用户名

        Returns:
            令牌对象

        Raises:
            DuplicateUserError: 用户名或邮箱已被占用
            ValueError: 密码长度不足
        """
        from service.services.user_account_service import UserAccountService

        if len(password) < 8:
            raise ValueError("密码至少 8 位")

        account = UserAccountService().create_user(
            username=username,
            email=email,
            password_hash=AuthUtils.get_password_hash(password),
            name=name or username,
        )

        return self.issue_token({
            "user_id": str(account.id),
            "username": account.username,
            "email": account.email,
            "name": account.name,
        })

    def issue_token(self, user: Dict[str, Any]) -> Token:
        """按用户信息签发令牌"""
        token_data = {
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"]
        }
        return Token(
            access_token=AuthUtils.create_access_token(data=token_data),
            token_type="bearer",
            expires_in=int(timedelta(days=JWT_ACCESS_TOKEN_EXPIRE_DAYS).total_seconds()),
            user_info=user
        )

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        验证令牌

        Args:
            token: JWT令牌字符串

        Returns:
            用户信息字典或None
        """
        # 直接解码：这里不能再回调 service_manager.verify_token_cached，
        # 后者又会调回本方法，形成无限递归（以前靠 RecursionError 被 except 吞掉才勉强返回，
        # 栈一深就退化成 None，所有带鉴权的接口全部 401）。
        # 需要缓存的调用方请直接用 service_manager.verify_token_cached()。
        return AuthUtils.get_current_user_from_token(token)
    
    def refresh_token(self, token: str) -> Optional[Token]:
        """
        刷新令牌
        
        Args:
            token: 当前令牌
            
        Returns:
            新的令牌对象或None
        """
        user = self.verify_token(token)
        if not user:
            return None
        
        # 重新生成令牌
        token_data = {
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"]
        }
        
        access_token = AuthUtils.create_access_token(data=token_data)
        expires_in = int(timedelta(days=JWT_ACCESS_TOKEN_EXPIRE_DAYS).total_seconds())
        
        return Token(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
            user_info=user
        )


# 全局认证服务实例
auth_service = AuthService() 