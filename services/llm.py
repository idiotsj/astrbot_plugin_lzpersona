"""LLM 调用服务"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional, TYPE_CHECKING

from astrbot.api import logger

from ..core import (
    PromptFormat,
    parse_format,
    get_generate_template,
    get_format_hint,
    get_format_display_name,
    FORMAT_CONVERT_TEMPLATE,
    REFINE_TEMPLATE_WITH_FORMAT,
    SHRINK_TEMPLATE_WITH_FORMAT,
    GENERATE_WITH_SUPPLEMENTS_TEMPLATE,
)

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.star import Context


def _extract_json_object(text: str) -> Optional[dict]:
    """从文本中提取完整的 JSON 对象（支持嵌套和字符串内的大括号）
    
    Args:
        text: 可能包含 JSON 的文本
        
    Returns:
        解析后的字典，失败返回 None
    """
    # 先尝试直接解析整个文本
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    
    # 查找第一个 { 并匹配完整的 JSON 对象
    start = text.find('{')
    if start == -1:
        return None
    
    brace_count = 0
    in_string = False
    escape_next = False
    
    for i in range(start, len(text)):
        c = text[i]
        
        # 处理转义字符
        if escape_next:
            escape_next = False
            continue
        
        if c == '\\':
            escape_next = True
            continue
        
        # 处理字符串边界
        if c == '"':
            in_string = not in_string
            continue
        
        # 字符串内的字符不计入大括号计数
        if in_string:
            continue
        
        # 计数大括号
        if c == '{':
            brace_count += 1
        elif c == '}':
            brace_count -= 1
            if brace_count == 0:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    return None
    
    return None


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

    def _get_max_retries(self) -> int:
        """获取最大重试次数"""
        return int(self._get_cfg("llm_max_retries", 2) or 2)

    async def call_architect(
        self, prompt: str, event: "AstrMessageEvent"
    ) -> Optional[str]:
        """调用架构师模型（带重试机制）

        Args:
            prompt: 提示词
            event: 消息事件（用于获取 UMO）

        Returns:
            LLM 返回的文本，失败返回 None
        """
        provider_id = self._get_architect_provider_id()
        timeout = self._get_architect_timeout()
        max_retries = self._get_max_retries()

        # 获取 Provider
        if provider_id:
            provider = self.context.get_provider_by_id(provider_id)
        else:
            provider = self.context.get_using_provider(
                umo=event.unified_msg_origin if event else None
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

        # 带重试的调用
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                resp = await asyncio.wait_for(_call(), timeout=timeout)
                return (resp.completion_text or "").strip()
            except asyncio.TimeoutError:
                last_error = f"超时 ({timeout}s)"
                if attempt < max_retries:
                    logger.warning(f"[lzpersona] LLM 调用{last_error}，重试 {attempt + 1}/{max_retries}")
                    await asyncio.sleep(1)  # 重试前短暂等待
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    logger.warning(f"[lzpersona] LLM 调用失败: {e}，重试 {attempt + 1}/{max_retries}")
                    await asyncio.sleep(1)

        logger.error(f"[lzpersona] LLM 调用最终失败 (重试{max_retries}次): {last_error}")
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

        # 解析 JSON（使用支持嵌套的提取方法）
        intent = _extract_json_object(result)
        
        if intent is None:
            logger.warning(f"[lzpersona] 意图解析失败, 原文: {result}")
            # 尝试简单的关键词匹配作为降级方案
            return self._fallback_intent_match(query)

        # 确保有 action 字段
        if "action" not in intent:
            intent["action"] = "help"

        # 清理空字段
        for key in ["description", "feedback", "persona_id", "intensity"]:
            if key not in intent:
                intent[key] = ""

        return intent

    async def analyze_missing_fields(
        self, description: str, event: "AstrMessageEvent"
    ) -> dict:
        """分析用户描述中缺失的字段

        Args:
            description: 用户的人格描述
            event: 消息事件

        Returns:
            包含 provided 和 missing 字段的字典
        """
        from ..core import DEFAULT_MISSING_ANALYSIS_TEMPLATE

        prompt = DEFAULT_MISSING_ANALYSIS_TEMPLATE.format(description=description)

        result = await self.call_architect(prompt, event)

        if not result:
            logger.warning("[lzpersona] 缺失字段分析失败，返回默认结果")
            return self._get_default_missing_fields()

        # 使用支持嵌套的 JSON 提取方法
        analysis = _extract_json_object(result)
        
        if analysis is None:
            logger.warning(f"[lzpersona] 缺失字段分析 JSON 解析失败")
            return self._get_default_missing_fields()

        # 验证结构
        if "provided" not in analysis or "missing" not in analysis:
            logger.warning("[lzpersona] 分析结果缺少必要字段")
            return self._get_default_missing_fields()

        return analysis

    def _get_default_missing_fields(self) -> dict:
        """返回默认的缺失字段列表"""
        return {
            "provided": [],
            "missing": [
                {"field": "appearance", "label": "外貌特征", "hint": "如发色、服装风格"},
                {"field": "user_identity", "label": "用户身份", "hint": "如主人、朋友、邻居"},
                {"field": "speech_style", "label": "说话风格", "hint": "语气、口癖、常用词"},
                {"field": "background", "label": "背景故事", "hint": "职业或简要经历"},
                {"field": "initial_attitude", "label": "初始态度", "hint": "对用户是友好还是冷淡"},
            ]
        }

    async def generate_with_supplements(
        self, description: str, supplements: str, auto_generate_fields: list, 
        event: "AstrMessageEvent", format_type: PromptFormat = PromptFormat.NATURAL
    ) -> Optional[str]:
        """根据用户描述和补充内容生成人格

        Args:
            description: 原始用户描述
            supplements: 用户补充的内容
            auto_generate_fields: 需要由 AI 自动生成的字段列表
            event: 消息事件
            format_type: 输出格式

        Returns:
            生成的人格提示词
        """
        # 格式化自动生成字段
        auto_fields_str = ", ".join(auto_generate_fields) if auto_generate_fields else "无"
        
        format_name = get_format_display_name(format_type)
        format_hint = get_format_hint(format_type)

        prompt = GENERATE_WITH_SUPPLEMENTS_TEMPLATE.format(
            description=description,
            supplements=supplements if supplements else "无",
            auto_generate_fields=auto_fields_str,
            format_type=format_name,
            format_structure_hint=format_hint,
        )

        return await self.call_architect(prompt, event)

    async def generate_persona(
        self, description: str, event: "AstrMessageEvent", 
        format_type: PromptFormat = PromptFormat.NATURAL
    ) -> Optional[str]:
        """根据描述生成指定格式的人格

        Args:
            description: 人格描述
            event: 消息事件
            format_type: 输出格式

        Returns:
            生成的人格提示词
        """
        template = get_generate_template(format_type)
        prompt = template.format(description=description)
        return await self.call_architect(prompt, event)

    async def convert_format(
        self, original_prompt: str, source_format: PromptFormat, 
        target_format: PromptFormat, event: "AstrMessageEvent"
    ) -> Optional[str]:
        """将人格提示词从一种格式转换为另一种格式

        Args:
            original_prompt: 原始人格提示词
            source_format: 源格式
            target_format: 目标格式
            event: 消息事件

        Returns:
            转换后的人格提示词
        """
        if source_format == target_format:
            return original_prompt

        source_name = get_format_display_name(source_format)
        target_name = get_format_display_name(target_format)
        target_hint = get_format_hint(target_format)

        prompt = FORMAT_CONVERT_TEMPLATE.format(
            source_format=source_name,
            original_prompt=original_prompt,
            target_format=target_name,
            format_structure_hint=target_hint,
        )

        return await self.call_architect(prompt, event)

    async def refine_persona(
        self, current_prompt: str, feedback: str, 
        format_type: PromptFormat, event: "AstrMessageEvent"
    ) -> Optional[str]:
        """根据反馈优化人格（保持格式）

        Args:
            current_prompt: 当前人格提示词
            feedback: 用户反馈
            format_type: 当前格式
            event: 消息事件

        Returns:
            优化后的人格提示词
        """
        format_name = get_format_display_name(format_type)

        prompt = REFINE_TEMPLATE_WITH_FORMAT.format(
            format_type=format_name,
            current_prompt=current_prompt,
            feedback=feedback,
        )

        return await self.call_architect(prompt, event)

    async def shrink_persona(
        self, original_prompt: str, intensity: str, 
        format_type: PromptFormat, event: "AstrMessageEvent"
    ) -> Optional[str]:
        """压缩人格提示词（保持格式）

        Args:
            original_prompt: 原始人格提示词
            intensity: 压缩强度（轻度/中度/极限）
            format_type: 当前格式
            event: 消息事件

        Returns:
            压缩后的人格提示词
        """
        format_name = get_format_display_name(format_type)

        prompt = SHRINK_TEMPLATE_WITH_FORMAT.format(
            format_type=format_name,
            original_prompt=original_prompt,
            intensity=intensity,
        )

        return await self.call_architect(prompt, event)

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
