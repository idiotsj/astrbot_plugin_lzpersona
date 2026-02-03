"""核心模块"""

from .constants import (
    PLUGIN_NAME,
    PLUGIN_DATA_NAME,
    PERSONA_PREFIX,
    DEFAULT_GEN_TEMPLATE,
    DEFAULT_REFINE_TEMPLATE,
    DEFAULT_SHRINK_TEMPLATE,
    DEFAULT_CLONE_TEMPLATE,
    DEFAULT_INTROSPECT_TEMPLATE,
    DEFAULT_INTENT_TEMPLATE,
)
from .models import SessionState, PendingPersona, PersonaBackup, SessionData
from .state import QuickPersonaState

__all__ = [
    # 常量
    "PLUGIN_NAME",
    "PLUGIN_DATA_NAME",
    "PERSONA_PREFIX",
    # 模板
    "DEFAULT_GEN_TEMPLATE",
    "DEFAULT_REFINE_TEMPLATE",
    "DEFAULT_SHRINK_TEMPLATE",
    "DEFAULT_CLONE_TEMPLATE",
    "DEFAULT_INTROSPECT_TEMPLATE",
    "DEFAULT_INTENT_TEMPLATE",
    # 数据模型
    "SessionState",
    "PendingPersona",
    "PersonaBackup",
    "SessionData",
    # 状态管理
    "QuickPersonaState",
]
