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
    DEFAULT_MISSING_ANALYSIS_TEMPLATE,
    DEFAULT_GUIDED_GEN_TEMPLATE,
)
from .models import SessionState, PendingPersona, PersonaBackup, SessionData, MissingField
from .state import QuickPersonaState
from .profile_models import UserProfile, ProfileMonitor, ProfileMode, MessageBuffer
from .profile_constants import (
    DEFAULT_PROFILE_UPDATE_TEMPLATE,
    DEFAULT_PROFILE_INIT_TEMPLATE,
    PROFILE_CARD_TEMPLATE,
)

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
    "DEFAULT_MISSING_ANALYSIS_TEMPLATE",
    "DEFAULT_GUIDED_GEN_TEMPLATE",
    # 画像模板
    "DEFAULT_PROFILE_UPDATE_TEMPLATE",
    "DEFAULT_PROFILE_INIT_TEMPLATE",
    "PROFILE_CARD_TEMPLATE",
    # 数据模型
    "SessionState",
    "PendingPersona",
    "PersonaBackup",
    "SessionData",
    "MissingField",
    # 画像数据模型
    "UserProfile",
    "ProfileMonitor",
    "ProfileMode",
    "MessageBuffer",
    # 状态管理
    "QuickPersonaState",
]
