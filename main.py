"""
快捷人格生成器 - AI 驱动的人格管理工具

通过简单的命令快速生成、优化和管理 AI 人格，无需手动编写复杂的提示词。
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.star.star_tools import StarTools

# 导入核心模块
from .core import (
    PLUGIN_NAME,
    PLUGIN_DATA_NAME,
    PERSONA_PREFIX,
    SessionState,
    PendingPersona,
    QuickPersonaState,
    ProfileMode,
    PromptFormat,
    parse_format,
)

# 导入服务
from .services import LLMService, PersonaService, ProfileService, ConfigService, RenderService

# 导入命令处理器
from .commands import PersonaCommands, ProfileCommands

# 导入工具
from .utils import shorten_prompt, generate_persona_id, get_session_id


@register(
    "astrbot_plugin_lzpersona", "idiotsj", "LZ快捷人格生成器 - AI 驱动的人格管理工具", "1.2.0", ""
)
class QuickPersona(Star, PersonaCommands, ProfileCommands):
    """快捷人格生成器插件
    
    通过混入类 (Mixin) 模式组合功能：
    - PersonaCommands: 人格生成、优化、压缩等命令
    - ProfileCommands: 用户画像监控、查看等命令
    """

    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context

        # 初始化数据目录
        base_data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME)).parent.parent
        self.data_dir = base_data_dir / "plugin_data" / PLUGIN_DATA_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 初始化状态管理
        self.state = QuickPersonaState(str(self.data_dir))
        self.state.load()

        # 初始化服务层
        self.config_service = ConfigService(context)
        self.llm_service = LLMService(context)
        self.persona_service = PersonaService(
            context, self.state, self.config_service.backup_versions
        )
        self.profile_service = ProfileService(context, self)
        self.render_service = RenderService(self)

        # 为命令模块提供简短别名
        self.config = self.config_service
        self.render = self.render_service

        logger.info(f"[lzpersona] 插件初始化完成，数据目录: {self.data_dir}")

    async def terminate(self):
        """插件卸载时的清理方法"""
        try:
            await self.state.save_async()
            if hasattr(self, 'profile_service') and self.profile_service._loaded:
                await self.profile_service.save_buffers()
                await self.profile_service.save_profiles()
                await self.profile_service.save_monitors()
            logger.info("[lzpersona] 插件资源已清理")
        except Exception as e:
            logger.error(f"[lzpersona] 清理资源时出错: {e}")

    # ==================== 配置获取（委托给 ConfigService）====================

    def _get_cfg(self, key: str, default: Any = None) -> Any:
        return self.config_service.get(key, default)

    def _get_max_prompt_length(self) -> int:
        return self.config_service.max_prompt_length

    def _get_confirm_before_apply(self) -> bool:
        return self.config_service.confirm_before_apply

    def _get_backup_versions(self) -> int:
        return self.config_service.backup_versions

    def _get_auto_compress(self) -> bool:
        return self.config_service.auto_compress

    def _get_template(self, template_key: str, default: str) -> str:
        return self.config_service.get_template(template_key, default)

    def _get_default_format(self) -> PromptFormat:
        return self.config_service.default_format

    def _get_enable_guided_generation(self) -> bool:
        return self.config_service.enable_guided_generation

    def _get_profile_enabled(self) -> bool:
        return self.config_service.profile_enabled

    # ==================== KV 存储 ====================

    async def get_kv_data(self, key: str, default: Any = None) -> Any:
        """从持久化存储获取数据"""
        try:
            import json
            file_path = self.data_dir / f"{key}.json"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default if default is not None else {}
        except Exception as e:
            logger.warning(f"[lzpersona] 读取 KV 数据失败 ({key}): {e}")
            return default if default is not None else {}

    async def put_kv_data(self, key: str, data: Any) -> bool:
        """保存数据到持久化存储"""
        try:
            import json
            file_path = self.data_dir / f"{key}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"[lzpersona] 保存 KV 数据失败 ({key}): {e}")
            return False

    # ==================== 渲染辅助（委托给 RenderService）====================

    async def _render_long_text(self, event: AstrMessageEvent, title: str, content: str, extra_info: str = ""):
        async for r in self.render_service.render_long_text(event, title, content, extra_info):
            yield r

    async def _render_persona_card(self, event: AstrMessageEvent, icon: str, title: str, subtitle: str,
                                   content: str, meta_info: dict = None, footer: str = ""):
        async for r in self.render_service.render_persona_card(event, icon, title, subtitle, content, meta_info, footer):
            yield r

    # ==================== 命令组定义 ====================

    @filter.command_group("快捷人格", alias={"qp", "quickpersona"})
    def qp(self):
        """快捷人格生成器命令组"""
        pass

    @filter.command_group("画像", alias={"profile", "pf"})
    def profile_cmd(self):
        """用户画像命令组"""
        pass

    # ==================== 消息钩子 ====================

    @filter.on_llm_request()
    async def on_message_for_profile(self, event: AstrMessageEvent, req):
        """监听所有消息用于用户画像更新"""
        if not self._get_profile_enabled():
            return req

        message_text = ""
        for comp in event.message_obj.message:
            if isinstance(comp, Plain):
                message_text += comp.text

        if not message_text.strip():
            return req

        sender_id = str(event.get_sender_id() or "")
        sender_name = event.get_sender_name() or ""
        group_id = ""
        umo = getattr(event, "unified_msg_origin", "")
        if ":group:" in umo:
            parts = umo.split(":")
            if len(parts) >= 3:
                group_id = parts[2]

        try:
            await self.profile_service.process_message(
                user_id=sender_id,
                content=message_text.strip(),
                group_id=group_id,
                nickname=sender_name,
                event=event,
            )
        except Exception as e:
            logger.debug(f"[lzpersona] 画像消息处理失败: {e}")

        return req

    # ==================== 智能入口 ====================

    @filter.command("人格", alias={"persona"})
    async def cmd_smart(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """智能意图识别入口"""
        query = str(query).strip()

        if not query:
            async for r in self.cmd_help(event):
                yield r
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        # 构建上下文
        try:
            personas = await self.persona_service.get_all_personas()
            persona_list = ", ".join([p.persona_id for p in personas[:10]])
            if len(personas) > 10:
                persona_list += f" (共 {len(personas)} 个)"
        except Exception:
            persona_list = "无法获取"

        context_info = {
            "current_persona_id": session.current_persona_id or "无",
            "persona_list": persona_list or "无",
            "session_state": session.state.value,
            "has_pending": "是" if session.pending_persona else "否",
        }

        intent = await self.llm_service.recognize_intent(query, context_info, event)
        action = intent.get("action", "help")

        logger.info(f"[lzpersona] 智能识别: query={query}, intent={intent}")

        # 路由到命令
        handlers = {
            "generate": lambda: self.cmd_gen(event, query if not intent.get("description") else intent["description"]),
            "refine": lambda: self.cmd_refine(event, intent.get("feedback", "") or query),
            "shrink": lambda: self.cmd_shrink(event, intent.get("intensity", "轻度")),
            "list": lambda: self.cmd_list(event),
            "view": lambda: self.cmd_view(event, intent.get("persona_id", "")),
            "activate": lambda: self.cmd_activate(event, intent.get("persona_id", "")),
            "delete": lambda: self.cmd_delete(event, intent.get("persona_id", "")),
            "rollback": lambda: self.cmd_rollback(event),
            "status": lambda: self.cmd_status(event),
            "apply": lambda: self.cmd_apply(event),
            "cancel": lambda: self.cmd_cancel(event),
        }

        handler = handlers.get(action)
        if handler:
            async for r in handler():
                yield r
        else:
            async for r in self.cmd_help(event):
                yield r

        event.stop_event()

    # ==================== 人格命令（委托给 PersonaCommands）====================

    @qp.command("使用帮助", alias={"help", "?"})
    async def cmd_help(self, event: AstrMessageEvent):
        async for r in PersonaCommands.cmd_help(self, event):
            yield r

    @qp.command("生成人格", alias={"gen"})
    async def cmd_gen(self, event: AstrMessageEvent, description: GreedyStr = ""):
        async for r in PersonaCommands.cmd_gen(self, event, description):
            yield r

    @qp.command("确认生成", alias={"confirm", "yes"})
    async def cmd_apply(self, event: AstrMessageEvent):
        async for r in PersonaCommands.cmd_apply(self, event):
            yield r

    @qp.command("取消操作", alias={"cancel", "no"})
    async def cmd_cancel(self, event: AstrMessageEvent):
        async for r in PersonaCommands.cmd_cancel(self, event):
            yield r

    @qp.command("查看状态", alias={"status"})
    async def cmd_status(self, event: AstrMessageEvent):
        async for r in PersonaCommands.cmd_status(self, event):
            yield r

    @qp.command("人格列表", alias={"list", "ls"})
    async def cmd_list(self, event: AstrMessageEvent):
        async for r in PersonaCommands.cmd_list(self, event):
            yield r

    @qp.command("查看详情", alias={"view"})
    async def cmd_view(self, event: AstrMessageEvent, persona_id: str = ""):
        async for r in PersonaCommands.cmd_view(self, event, persona_id):
            yield r

    @qp.command("历史版本", alias={"history"})
    async def cmd_history(self, event: AstrMessageEvent, persona_id: str = ""):
        async for r in PersonaCommands.cmd_history(self, event, persona_id):
            yield r

    @qp.command("版本回滚", alias={"rollback"})
    async def cmd_rollback(self, event: AstrMessageEvent, persona_id: str = ""):
        async for r in PersonaCommands.cmd_rollback(self, event, persona_id):
            yield r

    @qp.command("优化人格", alias={"refine"})
    async def cmd_refine(self, event: AstrMessageEvent, feedback: GreedyStr = ""):
        async for r in PersonaCommands.cmd_refine(self, event, feedback):
            yield r

    @qp.command("转换格式", alias={"format", "convert"})
    async def cmd_convert_format(self, event: AstrMessageEvent, target_format: str = ""):
        async for r in PersonaCommands.cmd_convert_format(self, event, target_format):
            yield r

    @qp.command("压缩人格", alias={"shrink"})
    async def cmd_shrink(self, event: AstrMessageEvent, intensity: str = "轻度"):
        async for r in PersonaCommands.cmd_shrink(self, event, intensity):
            yield r

    @qp.command("选择人格", alias={"use"})
    async def cmd_use(self, event: AstrMessageEvent, persona_id: str = ""):
        async for r in PersonaCommands.cmd_use(self, event, persona_id):
            yield r

    @qp.command("应用人格", alias={"activate", "apply"})
    async def cmd_activate(self, event: AstrMessageEvent, persona_id: str = ""):
        async for r in PersonaCommands.cmd_activate(self, event, persona_id):
            yield r

    @qp.command("新建对话", alias={"newchat"})
    async def cmd_newchat(self, event: AstrMessageEvent, persona_id: str = ""):
        async for r in PersonaCommands.cmd_newchat(self, event, persona_id):
            yield r

    @qp.command("删除人格", alias={"delete"})
    async def cmd_delete(self, event: AstrMessageEvent, persona_id: str = ""):
        async for r in PersonaCommands.cmd_delete(self, event, persona_id):
            yield r

    # ==================== 画像命令（委托给 ProfileCommands）====================

    @profile_cmd.command("帮助", alias={"help", "?"})
    async def profile_help(self, event: AstrMessageEvent):
        async for r in ProfileCommands.profile_help(self, event):
            yield r

    @profile_cmd.command("添加监控", alias={"add", "monitor"})
    async def profile_add_monitor(self, event: AstrMessageEvent, user_id: str = "", mode: str = "global"):
        async for r in ProfileCommands.profile_add_monitor(self, event, user_id, mode):
            yield r

    @profile_cmd.command("移除监控", alias={"remove", "rm"})
    async def profile_remove_monitor(self, event: AstrMessageEvent, user_id: str = ""):
        async for r in ProfileCommands.profile_remove_monitor(self, event, user_id):
            yield r

    @profile_cmd.command("监控列表", alias={"monitors"})
    async def profile_list_monitors(self, event: AstrMessageEvent):
        async for r in ProfileCommands.profile_list_monitors(self, event):
            yield r

    @profile_cmd.command("查看", alias={"view", "show"})
    async def profile_view(self, event: AstrMessageEvent, user_id: str = ""):
        async for r in ProfileCommands.profile_view(self, event, user_id):
            yield r

    @profile_cmd.command("列表", alias={"list", "ls"})
    async def profile_list(self, event: AstrMessageEvent):
        async for r in ProfileCommands.profile_list(self, event):
            yield r

    @profile_cmd.command("强制更新", alias={"update", "refresh"})
    async def profile_force_update(self, event: AstrMessageEvent, user_id: str = ""):
        async for r in ProfileCommands.profile_force_update(self, event, user_id):
            yield r

    @profile_cmd.command("删除", alias={"delete", "del"})
    async def profile_delete(self, event: AstrMessageEvent, user_id: str = ""):
        async for r in ProfileCommands.profile_delete(self, event, user_id):
            yield r

    @profile_cmd.command("缓冲状态", alias={"buffer"})
    async def profile_buffer_status(self, event: AstrMessageEvent, user_id: str = ""):
        async for r in ProfileCommands.profile_buffer_status(self, event, user_id):
            yield r
