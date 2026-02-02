"""工具函数"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from ..core.constants import PERSONA_PREFIX

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent


def shorten_prompt(prompt: str, max_len: int = 100) -> str:
    """截断提示词用于显示

    Args:
        prompt: 原始提示词
        max_len: 最大长度

    Returns:
        截断后的提示词
    """
    if len(prompt) <= max_len:
        return prompt
    return prompt[:max_len] + "..."


def generate_persona_id(hint: str = "") -> str:
    """生成人格ID

    Args:
        hint: 可选的提示词（用于生成可读性更好的ID）

    Returns:
        生成的人格ID
    """
    # 清理 hint，只保留字母数字和中文
    clean_hint = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", hint)[:10]
    if clean_hint:
        return f"{PERSONA_PREFIX}{clean_hint}_{uuid.uuid4().hex[:6]}"
    return f"{PERSONA_PREFIX}{uuid.uuid4().hex[:10]}"


def get_session_id(event: "AstrMessageEvent") -> str:
    """从事件中获取会话ID

    Args:
        event: 消息事件

    Returns:
        会话ID
    """
    return str(
        getattr(event, "unified_msg_origin", "")
        or event.get_sender_id()
        or "default"
    )
