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


def replace_placeholders(
    prompt: str,
    char_name: str = "",
    user_name: str = "User",
) -> str:
    """替换角色卡中的占位符

    将 SillyTavern 风格的占位符替换为实际值：
    - {{user}} -> 用户名
    - {{char}} -> 角色名
    - {{User}} -> 用户名
    - {{Char}} -> 角色名

    Args:
        prompt: 包含占位符的提示词
        char_name: 角色名（如不提供则保留 {{char}}）
        user_name: 用户名

    Returns:
        替换后的提示词
    """
    result = prompt

    # 替换用户占位符
    result = re.sub(r"\{\{user\}\}", user_name, result, flags=re.IGNORECASE)

    # 替换角色占位符（如果提供了角色名）
    if char_name:
        result = re.sub(r"\{\{char\}\}", char_name, result, flags=re.IGNORECASE)

    return result


def extract_char_name(prompt: str) -> str:
    """从角色卡中提取角色名

    尝试从 Character Card 格式中提取角色名

    Args:
        prompt: 角色卡提示词

    Returns:
        提取的角色名，如果未找到则返回空字符串
    """
    # 尝试从 "Character Card: XXX" 格式提取
    match = re.search(r"Character Card:\s*(.+?)(?:\n|$)", prompt)
    if match:
        return match.group(1).strip()

    # 尝试从 "**Name**: XXX" 格式提取
    match = re.search(r"\*\*Name\*\*:\s*(.+?)(?:\n|$)", prompt)
    if match:
        return match.group(1).strip()

    # 尝试从 "# Role: XXX" 格式提取
    match = re.search(r"#\s*Role:\s*(.+?)(?:\n|$)", prompt)
    if match:
        return match.group(1).strip()

    return ""
