"""
JSONPlaceholder API Client

Author: Andrew Wang
"""

import json
from typing import Optional, List
from core.http_core.client import APIClient
from .models import (
    User, Post, Comment, Todo,
    UsersApiResponse, UserApiResponse, PostsApiResponse, CommentsApiResponse, TodosApiResponse,
    format_user, format_post, format_comment, format_todo,
    format_user_summary, format_post_summary, format_comment_summary, format_todo_summary
)


class JSONPlaceholderClient:
    """JSONPlaceholder API Client"""
    
    def __init__(self):
        self.client = APIClient("https://jsonplaceholder.typicode.com")
    
    def get_users(self) -> Optional[UsersApiResponse]:
        """Get all users"""
        data = self.client.get("/users")
        if data and isinstance(data, list):
            return UsersApiResponse.from_list(data)
        return None
    
    def get_user(self, user_id: int) -> Optional[UserApiResponse]:
        """Get specific user by ID"""
        data = self.client.get(f"/users/{user_id}")
        if data:
            return UserApiResponse.from_dict(data)
        return None
    
    def get_user_posts(self, user_id: int) -> Optional[PostsApiResponse]:
        """Get user's posts"""
        data = self.client.get(f"/users/{user_id}/posts")
        if data and isinstance(data, list):
            return PostsApiResponse.from_list(data)
        return None
    
    def get_user_todos(self, user_id: int) -> Optional[TodosApiResponse]:
        """Get user's todos"""
        data = self.client.get(f"/users/{user_id}/todos")
        if data and isinstance(data, list):
            return TodosApiResponse.from_list(data)
        return None
