"""数据模型定义"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SessionState(Enum):
    """会话状态"""

    IDLE = "idle"  # 空闲
    WAITING_CONFIRM = "waiting_confirm"  # 等待确认
    WAITING_FEEDBACK = "waiting_feedback"  # 等待反馈（优化模式）
    WAITING_MISSING_INPUT = "waiting_missing_input"  # 等待缺失内容输入（引导式生成）


@dataclass
class MissingField:
    """缺失字段信息"""

    field: str  # 字段标识
    label: str  # 显示名称
    hint: str  # 提示信息


@dataclass
class PendingPersona:
    """待确认的人格"""

    persona_id: str
    system_prompt: str
    created_at: float
    mode: str  # "generate", "refine", "clone", "shrink", "guided"
    original_prompt: Optional[str] = None  # 原始提示词（用于对比）
    original_description: Optional[str] = None  # 原始用户描述（引导式生成用）
    missing_fields: Optional[list] = None  # 缺失字段列表（引导式生成用）
    provided_fields: Optional[list] = None  # 已提供字段列表（引导式生成用）


@dataclass
class PersonaBackup:
    """人格备份"""

    persona_id: str
    system_prompt: str
    backed_up_at: float

    def to_dict(self) -> dict:
        return {
            "persona_id": self.persona_id,
            "system_prompt": self.system_prompt,
            "backed_up_at": self.backed_up_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "PersonaBackup":
        return PersonaBackup(
            persona_id=d["persona_id"],
            system_prompt=d["system_prompt"],
            backed_up_at=d.get("backed_up_at", time.time()),
        )


@dataclass
class SessionData:
    """会话数据"""

    state: SessionState = SessionState.IDLE
    pending_persona: Optional[PendingPersona] = None
    current_persona_id: Optional[str] = None  # 当前使用的人格ID
