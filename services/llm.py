"""LLM 调用服务"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, TYPE_CHECKING

from astrbot.api import logger

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.star import Context


class LLMService:
    """LLM 调用封装"""

    def __init__(self, context: "Context"):
        self.context = context

    def _get_cfg(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        try:
            config = self.context.get_config()
            if config is None:
                return default
            return config.get(key, default)
        except Exception:
            return default

    def _get_architect_provider_id(self) -> str:
        """获取架构师模型 Provider ID"""
        return str(self._get_cfg("architect_provider_id", "") or "")

    def _get_architect_timeout(self) -> int:
        """获取架构师超时时间"""
        return int(self._get_cfg("architect_timeout", 60) or 60)

    async def call_architect(
        self, prompt: str, event: "AstrMessageEvent"
    ) -> Optional[str]:
        """调用架构师模型

        Args:
            prompt: 提示词
            event: 消息事件（用于获取 UMO）

        Returns:
            LLM 返回的文本，失败返回 None
        """
        provider_id = self._get_architect_provider_id()
        timeout = self._get_architect_timeout()

        try:
            if provider_id:
                provider = self.context.get_provider_by_id(provider_id)
            else:
                provider = self.context.get_using_provider(
                    umo=getattr(event, "unified_msg_origin", None)
                )

            if not provider or not hasattr(provider, "text_chat"):
                logger.error("[lzpersona] 无法获取 LLM Provider")
                return None

            text_chat = getattr(provider, "text_chat")

            async def _call():
                return await text_chat(
                    prompt=prompt,
                    contexts=[],
                    image_urls=[],
                    func_tool=None,
                    system_prompt="",
                )

            resp = await asyncio.wait_for(_call(), timeout=timeout)
            return (resp.completion_text or "").strip()

        except asyncio.TimeoutError:
            logger.error(f"[lzpersona] LLM 调用超时 ({timeout}s)")
            return None
        except Exception as e:
            logger.error(f"[lzpersona] LLM 调用失败: {e}")
            return None
