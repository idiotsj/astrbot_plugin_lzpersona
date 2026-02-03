"""LLM 调用服务"""

from __future__ import annotations

import asyncio
import json
import re
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

    async def recognize_intent(
        self, query: str, context_info: dict, event: "AstrMessageEvent"
    ) -> dict:
        """识别用户意图

        Args:
            query: 用户输入
            context_info: 上下文信息（当前人格、人格列表等）
            event: 消息事件

        Returns:
            意图字典，包含 action 和相关参数
        """
        from ..core import DEFAULT_INTENT_TEMPLATE

        prompt = DEFAULT_INTENT_TEMPLATE.format(
            current_persona_id=context_info.get("current_persona_id", "无"),
            persona_list=context_info.get("persona_list", "无"),
            session_state=context_info.get("session_state", "空闲"),
            has_pending=context_info.get("has_pending", "否"),
            query=query,
        )

        result = await self.call_architect(prompt, event)

        if not result:
            return {"action": "help", "error": "LLM 调用失败"}

        # 解析 JSON
        try:
            # 尝试提取 JSON 部分
            json_match = re.search(r'\{[^{}]*\}', result, re.DOTALL)
            if json_match:
                intent = json.loads(json_match.group())
            else:
                intent = json.loads(result)

            # 确保有 action 字段
            if "action" not in intent:
                intent["action"] = "help"

            # 清理空字段
            for key in ["description", "feedback", "persona_id", "intensity"]:
                if key not in intent:
                    intent[key] = ""

            return intent

        except json.JSONDecodeError as e:
            logger.warning(f"[lzpersona] 意图解析失败: {e}, 原文: {result}")
            # 尝试简单的关键词匹配作为降级方案
            return self._fallback_intent_match(query)

    def _fallback_intent_match(self, query: str) -> dict:
        """降级的关键词意图匹配"""
        query_lower = query.lower()

        # 简单关键词匹配
        if any(kw in query_lower for kw in ["生成", "创建", "新建一个"]):
            return {"action": "generate", "description": query}
        elif any(kw in query_lower for kw in ["优化", "改进", "调整", "修改"]):
            return {"action": "refine", "feedback": query}
        elif any(kw in query_lower for kw in ["压缩", "精简", "缩短"]):
            return {"action": "shrink", "intensity": "轻度"}
        elif any(kw in query_lower for kw in ["列表", "显示", "所有", "查看全部"]):
            return {"action": "list"}
        elif any(kw in query_lower for kw in ["切换", "激活", "使用", "启用"]):
            return {"action": "activate", "persona_id": ""}
        elif any(kw in query_lower for kw in ["删除", "移除"]):
            return {"action": "delete", "persona_id": ""}
        elif any(kw in query_lower for kw in ["回滚", "恢复", "撤销"]):
            return {"action": "rollback"}
        elif any(kw in query_lower for kw in ["状态", "当前"]):
            return {"action": "status"}
        elif any(kw in query_lower for kw in ["确认", "应用", "是", "好的"]):
            return {"action": "apply"}
        elif any(kw in query_lower for kw in ["取消", "不要", "算了"]):
            return {"action": "cancel"}
        else:
            return {"action": "help"}
