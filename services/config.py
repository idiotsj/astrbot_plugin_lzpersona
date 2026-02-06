"""配置服务 - 统一配置管理"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from astrbot.api.star import Context


class ConfigService:
    """统一配置管理服务"""

    def __init__(self, context: "Context"):
        self.context = context
        self._cache: dict = {}

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        try:
            config = self.context.get_config()
            if config is None:
                return default
            return config.get(key, default)
        except Exception:
            return default

    def get_int(self, key: str, default: int = 0) -> int:
        """获取整数配置"""
        val = self.get(key, default)
        try:
            return int(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置"""
        return bool(self.get(key, default))

    def get_str(self, key: str, default: str = "") -> str:
        """获取字符串配置"""
        val = self.get(key, default)
        return str(val).strip() if val else default

    # ==================== 业务配置快捷方法 ====================

    @property
    def max_prompt_length(self) -> int:
        return self.get_int("max_prompt_length", 800)

    @property
    def confirm_before_apply(self) -> bool:
        return self.get_bool("confirm_before_apply", True)

    @property
    def backup_versions(self) -> int:
        return self.get_int("backup_versions", 5)

    @property
    def auto_compress(self) -> bool:
        return self.get_bool("auto_compress", True)

    @property
    def enable_guided_generation(self) -> bool:
        return self.get_bool("enable_guided_generation", True)

    @property
    def profile_enabled(self) -> bool:
        return self.get_bool("profile_enabled", False)

    def get_template(self, key: str, default: str) -> str:
        """获取模板，如果用户未自定义则返回默认值"""
        custom = self.get_str(key, "")
        return custom if custom else default
