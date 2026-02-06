"""用户画像数据模型"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ProfileMode(Enum):
    """画像监测模式"""
    GLOBAL = "global"  # 全局模式：监控目标用户在所有群/私聊的消息
    GROUP = "group"    # 群聊模式：仅监控目标用户在指定群聊的消息


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str                          # 用户ID
    nickname: str = ""                    # 用户昵称
    profile_text: str = ""                # 画像文本描述
    traits: List[str] = field(default_factory=list)        # 特征标签
    interests: List[str] = field(default_factory=list)     # 兴趣爱好
    speaking_style: str = ""              # 说话风格
    emotional_tendency: str = ""          # 情感倾向
    message_count: int = 0                # 已处理的消息数
    last_updated: float = 0               # 最后更新时间戳
    created_at: float = 0                 # 创建时间戳

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "nickname": self.nickname,
            "profile_text": self.profile_text,
            "traits": self.traits,
            "interests": self.interests,
            "speaking_style": self.speaking_style,
            "emotional_tendency": self.emotional_tendency,
            "message_count": self.message_count,
            "last_updated": self.last_updated,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "UserProfile":
        return UserProfile(
            user_id=d.get("user_id", ""),
            nickname=d.get("nickname", ""),
            profile_text=d.get("profile_text", ""),
            traits=d.get("traits", []),
            interests=d.get("interests", []),
            speaking_style=d.get("speaking_style", ""),
            emotional_tendency=d.get("emotional_tendency", ""),
            message_count=d.get("message_count", 0),
            last_updated=d.get("last_updated", 0),
            created_at=d.get("created_at", 0),
        )


@dataclass
class ProfileMonitor:
    """画像监控配置"""
    user_id: str                          # 监控的用户ID
    mode: ProfileMode                     # 监测模式
    group_ids: List[str] = field(default_factory=list)  # 群聊模式时监控的群ID列表
    enabled: bool = True                  # 是否启用
    created_at: float = 0                 # 创建时间
    created_by: str = ""                  # 创建者ID

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "mode": self.mode.value,
            "group_ids": self.group_ids,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    @staticmethod
    def from_dict(d: dict) -> "ProfileMonitor":
        return ProfileMonitor(
            user_id=d.get("user_id", ""),
            mode=ProfileMode(d.get("mode", "global")),
            group_ids=d.get("group_ids", []),
            enabled=d.get("enabled", True),
            created_at=d.get("created_at", 0),
            created_by=d.get("created_by", ""),
        )


@dataclass
class MessageBuffer:
    """消息缓冲区"""
    user_id: str
    messages: List[Dict] = field(default_factory=list)  # 消息列表 [{content, timestamp, group_id, nickname}]
    last_flush: float = field(default_factory=time.time)  # 上次刷新时间（默认为当前时间，避免首次立即触发）

    def add_message(self, content: str, group_id: str = "", nickname: str = ""):
        """添加消息到缓冲区"""
        self.messages.append({
            "content": content,
            "timestamp": time.time(),
            "group_id": group_id,
            "nickname": nickname,
        })

    def should_flush(self, min_messages: int = 10, max_age_seconds: int = 300) -> bool:
        """判断是否应该刷新（触发画像更新）"""
        if not self.messages:
            return False
        
        # 消息数量达到阈值
        if len(self.messages) >= min_messages:
            return True
        
        # 有消息且距离上次刷新超过指定时间
        # 注意：last_flush 初始化为创建时间，避免首次立即触发
        if len(self.messages) >= 3 and (time.time() - self.last_flush) > max_age_seconds:
            # 至少需要 3 条消息才考虑时间触发，避免过于频繁更新
            return True
        
        return False

    def flush(self) -> List[Dict]:
        """刷新缓冲区，返回所有消息并清空"""
        messages = self.messages.copy()
        self.messages.clear()
        self.last_flush = time.time()
        return messages

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "messages": self.messages,
            "last_flush": self.last_flush,
        }

    @staticmethod
    def from_dict(d: dict) -> "MessageBuffer":
        buffer = MessageBuffer(
            user_id=d.get("user_id", ""),
        )
        # 从存储恢复时使用保存的 last_flush，如果没有则使用当前时间
        buffer.last_flush = d.get("last_flush") or time.time()
        buffer.messages = d.get("messages", [])
        return buffer
