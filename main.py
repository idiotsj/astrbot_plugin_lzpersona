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
from astrbot.api.star import Context, Star, register
from astrbot.core.star.star_tools import StarTools

# 导入解耦的模块
from .core import (
    PLUGIN_NAME,
    PLUGIN_DATA_NAME,
    PERSONA_PREFIX,
    DEFAULT_GEN_TEMPLATE,
    DEFAULT_REFINE_TEMPLATE,
    DEFAULT_SHRINK_TEMPLATE,
    SessionState,
    PendingPersona,
    QuickPersonaState,
)
from .services import LLMService, PersonaService
from .utils import shorten_prompt, generate_persona_id, get_session_id


@register(
    "astrbot_plugin_lzpersona", "LZD", "LZ快捷人格生成器 - AI 驱动的人格管理工具", "1.0.0", ""
)
class QuickPersona(Star):
    """快捷人格生成器插件

    通过简单的命令快速生成、优化和管理 AI 人格，无需手动编写复杂的提示词。
    """

    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context

        # 初始化数据目录 - 使用独立的 plugin_data 目录
        base_data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME)).parent.parent
        self.data_dir = base_data_dir / "plugin_data" / PLUGIN_DATA_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 初始化状态管理
        self.state = QuickPersonaState(str(self.data_dir))
        self.state.load()

        # 初始化服务
        self.llm_service = LLMService(context)
        self.persona_service = PersonaService(
            context, self.state, self._get_backup_versions()
        )

        logger.info(f"[lzpersona] 插件初始化完成，数据目录: {self.data_dir}")

    # ==================== 配置获取 ====================

    def _get_cfg(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        # 从 context 获取配置
        try:
            config = self.context.get_config()
            if config is None:
                return default
            return config.get(key, default)
        except Exception:
            return default

    def _get_max_prompt_length(self) -> int:
        return int(self._get_cfg("max_prompt_length", 800) or 800)

    def _get_confirm_before_apply(self) -> bool:
        return bool(self._get_cfg("confirm_before_apply", True))

    def _get_backup_versions(self) -> int:
        return int(self._get_cfg("backup_versions", 5) or 5)

    def _get_auto_compress(self) -> bool:
        return bool(self._get_cfg("auto_compress", True))

    def _get_template(self, template_key: str, default: str) -> str:
        custom = str(self._get_cfg(template_key, "") or "").strip()
        return custom if custom else default

    # ==================== 渲染辅助 ====================

    async def _render_long_text(
        self, event: AstrMessageEvent, title: str, content: str, extra_info: str = ""
    ):
        """将长文本渲染为图片输出"""
        lines = [f"📌 {title}", "=" * 40, "", content]
        if extra_info:
            lines.extend(["", "-" * 40, extra_info])

        text = "\n".join(lines)

        try:
            image_url = await self.text_to_image(text)
            yield event.image_result(image_url)
        except Exception as e:
            logger.warning(f"[lzpersona] 文转图失败，使用纯文本输出: {e}")
            yield event.plain_result(text)

    # ==================== 命令组 ====================

    @filter.command_group("快捷人格", alias={"qp", "quickpersona"})
    def qp(self):
        """快捷人格生成器命令组"""
        pass

    @qp.command("使用帮助", alias={"help", "?"})
    async def cmd_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """快捷人格生成器 - 命令列表

📝 生成与优化
/快捷人格 生成人格 <描述> - 根据描述生成人格
/快捷人格 优化人格 <反馈> - 根据反馈优化当前人格
/快捷人格 压缩人格 [强度] - 压缩提示词(轻度/中度/极限)

🎭 人格画像 (开发中)
/快捷人格 画像生成 - 从转发的聊天记录生成画像
/快捷人格 自省检测 - 自省当前人格

📋 管理
/快捷人格 查看状态 - 查看当前状态
/快捷人格 确认应用 - 应用待确认的人格
/快捷人格 取消操作 - 取消待确认的人格
/快捷人格 历史版本 [人格ID] - 查看历史版本列表
/快捷人格 版本回滚 - 回滚到上一个版本
/快捷人格 人格列表 - 列出所有人格
/快捷人格 查看详情 <人格ID> - 查看人格详情
/快捷人格 选择人格 <人格ID> - 选择人格（后续操作的目标）
/快捷人格 激活人格 [人格ID] - 激活人格到当前对话
/快捷人格 新建对话 [人格ID] - 新建对话并激活人格
/快捷人格 删除人格 <人格ID> - 删除人格

💡 提示：生成人格后需要 /快捷人格 确认应用，然后 /快捷人格 激活人格 让 AI 使用"""
        yield event.plain_result(help_text)

    @qp.command("生成人格", alias={"gen"})
    async def cmd_gen(self, event: AstrMessageEvent, *args):
        """根据描述生成人格"""
        description = " ".join(args).strip()

        if not description:
            yield event.plain_result(
                "请提供人格描述，例如：/快捷人格 生成人格 一个温柔的猫娘"
            )
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        if session.state == SessionState.WAITING_CONFIRM:
            yield event.plain_result(
                "你有一个待确认的人格，请先 /快捷人格 确认应用 或 /快捷人格 取消操作"
            )
            return

        yield event.plain_result(
            f"🔄 正在根据描述生成人格...\n描述: {shorten_prompt(description, 50)}"
        )

        # 构建提示词并调用 LLM
        template = self._get_template("persona_gen_template", DEFAULT_GEN_TEMPLATE)
        prompt = template.format(description=description)
        result = await self.llm_service.call_architect(prompt, event)

        if not result:
            yield event.plain_result("❌ 生成失败，请检查 LLM 配置或稍后重试")
            return

        # 自动压缩
        max_len = self._get_max_prompt_length()
        if len(result) > max_len and self._get_auto_compress():
            yield event.plain_result(
                f"⚠️ 生成的提示词过长({len(result)}字符)，正在自动压缩..."
            )
            shrink_template = self._get_template(
                "persona_shrink_template", DEFAULT_SHRINK_TEMPLATE
            )
            shrink_prompt = shrink_template.format(
                original_prompt=result, intensity="轻度"
            )
            compressed = await self.llm_service.call_architect(shrink_prompt, event)
            if compressed and len(compressed) < len(result):
                result = compressed

        persona_id = generate_persona_id(description)

        if self._get_confirm_before_apply():
            session.state = SessionState.WAITING_CONFIRM
            session.pending_persona = PendingPersona(
                persona_id=persona_id,
                system_prompt=result,
                created_at=time.time(),
                mode="generate",
            )

            yield event.plain_result(
                f"✅ 人格生成完成！\n\n"
                f"📌 人格ID: {persona_id}\n"
                f"📝 提示词 ({len(result)}字符):\n{shorten_prompt(result, 300)}\n\n"
                f"发送 /快捷人格 确认应用 应用此人格\n"
                f"发送 /快捷人格 取消操作 取消"
            )
        else:
            success = await self.persona_service.create_or_update(
                persona_id, result, backup=False
            )
            if success:
                session.current_persona_id = persona_id
                yield event.plain_result(
                    f"✅ 人格已创建并应用！\n\n"
                    f"📌 人格ID: {persona_id}\n"
                    f"📝 提示词 ({len(result)}字符):\n{shorten_prompt(result, 300)}"
                )
            else:
                yield event.plain_result("❌ 应用人格失败，请查看日志")

    @qp.command("确认应用", alias={"apply", "yes"})
    async def cmd_apply(self, event: AstrMessageEvent):
        """应用待确认的人格"""
        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        if session.state != SessionState.WAITING_CONFIRM or not session.pending_persona:
            yield event.plain_result("没有待确认的人格")
            return

        pending = session.pending_persona
        success = await self.persona_service.create_or_update(
            pending.persona_id, pending.system_prompt, backup=True
        )

        if success:
            session.current_persona_id = pending.persona_id
            session.state = SessionState.IDLE
            session.pending_persona = None

            yield event.plain_result(
                f"✅ 人格已应用！\n"
                f"📌 人格ID: {pending.persona_id}\n"
                f"💡 使用 /快捷人格 激活人格 让 AI 使用此人格"
            )
        else:
            yield event.plain_result("❌ 应用失败，请查看日志")

    @qp.command("取消操作", alias={"cancel", "no"})
    async def cmd_cancel(self, event: AstrMessageEvent):
        """取消待确认的人格"""
        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        if session.state != SessionState.WAITING_CONFIRM:
            yield event.plain_result("没有待确认的人格")
            return

        session.state = SessionState.IDLE
        session.pending_persona = None
        yield event.plain_result("✅ 已取消")

    @qp.command("查看状态", alias={"status"})
    async def cmd_status(self, event: AstrMessageEvent):
        """查看当前状态"""
        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        lines = ["📊 当前状态"]
        lines.append(f"会话状态: {session.state.value}")

        if session.current_persona_id:
            lines.append(f"当前人格: {session.current_persona_id}")

        if session.pending_persona:
            p = session.pending_persona
            lines.append("\n📌 待确认人格:")
            lines.append(f"  ID: {p.persona_id}")
            lines.append(f"  模式: {p.mode}")
            lines.append(
                f"  创建于: {datetime.fromtimestamp(p.created_at).strftime('%H:%M:%S')}"
            )
            lines.append(f"  提示词预览: {shorten_prompt(p.system_prompt, 100)}")

        yield event.plain_result("\n".join(lines))

    @qp.command("人格列表", alias={"list", "ls"})
    async def cmd_list(self, event: AstrMessageEvent):
        """列出所有人格"""
        try:
            personas = await self.persona_service.get_all_personas()

            if not personas:
                yield event.plain_result("当前没有人格")
                return

            lines = ["📋 人格列表"]
            for p in personas:
                prefix = "🔹" if p.persona_id.startswith(PERSONA_PREFIX) else "  "
                prompt_preview = shorten_prompt(p.system_prompt, 30)
                lines.append(f"{prefix} {p.persona_id}: {prompt_preview}")

            lines.append(f"\n共 {len(personas)} 个人格 (🔹 表示由本插件创建)")
            yield event.plain_result("\n".join(lines))

        except Exception as e:
            logger.error(f"[lzpersona] 获取人格列表失败: {e}")
            yield event.plain_result("❌ 获取列表失败")

    @qp.command("查看详情", alias={"view"})
    async def cmd_view(self, event: AstrMessageEvent, persona_id: str = ""):
        """查看人格详情"""
        if not persona_id:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)
            persona_id = session.current_persona_id or ""

        if not persona_id:
            yield event.plain_result(
                "请指定人格ID，例如: /快捷人格 查看详情 qp_猫娘_abc123"
            )
            return

        try:
            persona = await self.persona_service.get_persona(persona_id)

            extra_lines = [f"字符数: {len(persona.system_prompt)}"]
            if persona_id in self.state.backups:
                backup_count = len(self.state.backups[persona_id])
                extra_lines.append(f"历史版本: {backup_count} 个")

            async for result in self._render_long_text(
                event,
                f"人格详情: {persona.persona_id}",
                persona.system_prompt,
                "\n".join(extra_lines),
            ):
                yield result

        except ValueError:
            yield event.plain_result(f"❌ 未找到人格: {persona_id}")
        except Exception as e:
            logger.error(f"[lzpersona] 查看人格失败: {e}")
            yield event.plain_result("❌ 查看失败")

    @qp.command("历史版本", alias={"history"})
    async def cmd_history(self, event: AstrMessageEvent, persona_id: str = ""):
        """查看历史版本"""
        if not persona_id:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)
            persona_id = session.current_persona_id or ""

        if not persona_id:
            yield event.plain_result(
                "请指定人格ID，例如: /快捷人格 历史版本 qp_猫娘_abc123"
            )
            return

        backups = self.state.get_all_backups(persona_id)
        if not backups:
            yield event.plain_result(f"❌ 没有找到 {persona_id} 的历史版本")
            return

        lines = [f"📜 {persona_id} 的历史版本 (共 {len(backups)} 个)"]
        lines.append("-" * 30)

        for i, backup in enumerate(backups):
            backup_time = datetime.fromtimestamp(backup.backed_up_at).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            preview = shorten_prompt(backup.system_prompt, 50)
            lines.append(f"{i + 1}. [{backup_time}]")
            lines.append(f"   {preview}")

        lines.append("-" * 30)
        lines.append("💡 使用 /快捷人格 版本回滚 可回滚到最新备份")

        yield event.plain_result("\n".join(lines))

    @qp.command("版本回滚", alias={"rollback"})
    async def cmd_rollback(self, event: AstrMessageEvent, persona_id: str = ""):
        """回滚到上一个版本"""
        if not persona_id:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)
            persona_id = session.current_persona_id or ""

        if not persona_id:
            yield event.plain_result(
                "请指定人格ID，例如: /快捷人格 版本回滚 qp_猫娘_abc123"
            )
            return

        backup = self.state.get_latest_backup(persona_id)
        if not backup:
            yield event.plain_result(f"❌ 没有找到 {persona_id} 的备份")
            return

        try:
            await self.context.persona_manager.update_persona(
                persona_id=persona_id, system_prompt=backup.system_prompt
            )
            self.state.backups[persona_id].pop(0)
            await self.state.save_backups()

            backup_time = datetime.fromtimestamp(backup.backed_up_at).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            yield event.plain_result(
                f"✅ 已回滚到 {backup_time} 的版本\n"
                f"📝 提示词预览: {shorten_prompt(backup.system_prompt, 200)}"
            )

        except Exception as e:
            logger.error(f"[lzpersona] 回滚失败: {e}")
            yield event.plain_result("❌ 回滚失败")

    @qp.command("优化人格", alias={"refine"})
    async def cmd_refine(self, event: AstrMessageEvent, *args):
        """根据反馈优化当前人格"""
        feedback = " ".join(args).strip()

        if not feedback:
            yield event.plain_result(
                "请提供优化反馈，例如：/快捷人格 优化人格 说话再可爱一点"
            )
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)
        persona_id = session.current_persona_id

        if not persona_id:
            yield event.plain_result(
                "请先使用 /快捷人格 选择人格 <人格ID> 选择一个人格"
            )
            return

        try:
            persona = await self.persona_service.get_persona(persona_id)
        except ValueError:
            yield event.plain_result(f"❌ 未找到人格: {persona_id}")
            return

        yield event.plain_result(
            f"🔄 正在根据反馈优化人格...\n反馈: {shorten_prompt(feedback, 50)}"
        )

        template = self._get_template(
            "persona_refine_template", DEFAULT_REFINE_TEMPLATE
        )
        prompt = template.format(
            current_prompt=persona.system_prompt, feedback=feedback
        )
        result = await self.llm_service.call_architect(prompt, event)

        if not result:
            yield event.plain_result("❌ 优化失败，请稍后重试")
            return

        if self._get_confirm_before_apply():
            session.state = SessionState.WAITING_CONFIRM
            session.pending_persona = PendingPersona(
                persona_id=persona_id,
                system_prompt=result,
                created_at=time.time(),
                mode="refine",
                original_prompt=persona.system_prompt,
            )

            yield event.plain_result(
                f"✅ 人格优化完成！\n\n"
                f"📌 人格ID: {persona_id}\n"
                f"📝 优化后提示词 ({len(result)}字符):\n{shorten_prompt(result, 300)}\n\n"
                f"发送 /快捷人格 确认应用 应用此更改\n"
                f"发送 /快捷人格 取消操作 取消"
            )
        else:
            success = await self.persona_service.create_or_update(
                persona_id, result, backup=True
            )
            if success:
                yield event.plain_result(
                    f"✅ 人格已优化！\n📌 人格ID: {persona_id}\n"
                    f"📝 新提示词 ({len(result)}字符):\n{shorten_prompt(result, 300)}"
                )
            else:
                yield event.plain_result("❌ 应用失败，请查看日志")

    @qp.command("压缩人格", alias={"shrink"})
    async def cmd_shrink(self, event: AstrMessageEvent, intensity: str = "轻度"):
        """压缩人格提示词"""
        session_id = get_session_id(event)
        session = self.state.get_session(session_id)
        persona_id = session.current_persona_id

        if not persona_id:
            yield event.plain_result(
                "请先使用 /快捷人格 选择人格 <人格ID> 选择一个人格"
            )
            return

        try:
            persona = await self.persona_service.get_persona(persona_id)
        except ValueError:
            yield event.plain_result(f"❌ 未找到人格: {persona_id}")
            return

        valid_intensities = ["轻度", "中度", "极限"]
        if intensity not in valid_intensities:
            intensity = "轻度"

        original_len = len(persona.system_prompt)
        yield event.plain_result(
            f"🔄 正在压缩人格提示词...\n原始长度: {original_len}字符\n压缩强度: {intensity}"
        )

        template = self._get_template(
            "persona_shrink_template", DEFAULT_SHRINK_TEMPLATE
        )
        prompt = template.format(
            original_prompt=persona.system_prompt, intensity=intensity
        )
        result = await self.llm_service.call_architect(prompt, event)

        if not result:
            yield event.plain_result("❌ 压缩失败，请稍后重试")
            return

        new_len = len(result)
        reduction = (
            round((1 - new_len / original_len) * 100, 1) if original_len > 0 else 0
        )

        if self._get_confirm_before_apply():
            session.state = SessionState.WAITING_CONFIRM
            session.pending_persona = PendingPersona(
                persona_id=persona_id,
                system_prompt=result,
                created_at=time.time(),
                mode="shrink",
                original_prompt=persona.system_prompt,
            )

            yield event.plain_result(
                f"✅ 压缩完成！\n\n"
                f"📊 压缩效果: {original_len} → {new_len} 字符 (减少 {reduction}%)\n"
                f"📝 压缩后提示词:\n{shorten_prompt(result, 300)}\n\n"
                f"发送 /快捷人格 确认应用 应用此更改\n"
                f"发送 /快捷人格 取消操作 取消"
            )
        else:
            success = await self.persona_service.create_or_update(
                persona_id, result, backup=True
            )
            if success:
                yield event.plain_result(
                    f"✅ 压缩完成并已应用！\n"
                    f"📊 压缩效果: {original_len} → {new_len} 字符 (减少 {reduction}%)"
                )
            else:
                yield event.plain_result("❌ 应用失败，请查看日志")

    @qp.command("选择人格", alias={"use"})
    async def cmd_use(self, event: AstrMessageEvent, persona_id: str = ""):
        """选择一个人格"""
        if not persona_id:
            yield event.plain_result(
                "请指定人格ID，例如: /快捷人格 选择人格 qp_猫娘_abc123"
            )
            return

        try:
            await self.persona_service.get_persona(persona_id)
        except ValueError:
            yield event.plain_result(f"❌ 未找到人格: {persona_id}")
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)
        session.current_persona_id = persona_id

        yield event.plain_result(
            f"✅ 已选择人格: {persona_id}\n"
            f"后续的 优化人格/压缩人格 操作将针对此人格\n\n"
            f"💡 使用 /快捷人格 激活人格 激活到当前对话"
        )

    @qp.command("激活人格", alias={"activate"})
    async def cmd_activate(self, event: AstrMessageEvent, persona_id: str = ""):
        """激活人格到当前对话"""
        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        if not persona_id:
            persona_id = session.current_persona_id or ""

        if not persona_id:
            yield event.plain_result(
                "请指定人格ID，例如: /快捷人格 激活人格 qp_猫娘_abc123\n"
                "或先使用 /快捷人格 选择人格 选择一个人格"
            )
            return

        try:
            await self.persona_service.get_persona(persona_id)
        except ValueError:
            yield event.plain_result(f"❌ 未找到人格: {persona_id}")
            return

        umo = getattr(event, "unified_msg_origin", None)
        if not umo:
            yield event.plain_result("❌ 无法获取会话信息")
            return

        success, msg = await self.persona_service.activate_persona(umo, persona_id)
        if success:
            session.current_persona_id = persona_id
            yield event.plain_result(f"✅ {msg}\n📌 AI 的下一条回复将使用新人格")
        else:
            yield event.plain_result(f"❌ 激活失败: {msg}")

    @qp.command("新建对话", alias={"newchat"})
    async def cmd_newchat(self, event: AstrMessageEvent, persona_id: str = ""):
        """新建对话"""
        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        if not persona_id:
            persona_id = session.current_persona_id or ""

        umo = getattr(event, "unified_msg_origin", None)
        if not umo:
            yield event.plain_result("❌ 无法获取会话信息")
            return

        if persona_id:
            try:
                await self.persona_service.get_persona(persona_id)
            except ValueError:
                yield event.plain_result(f"❌ 未找到人格: {persona_id}")
                return

        success, result = await self.persona_service.new_conversation(umo, persona_id)
        if success:
            if persona_id:
                session.current_persona_id = persona_id
                yield event.plain_result(
                    f"✅ 已创建新对话并激活人格\n📌 对话ID: {result}\n🎭 人格: {persona_id}"
                )
            else:
                yield event.plain_result(
                    f"✅ 已创建新对话\n📌 对话ID: {result}\n"
                    f"💡 使用 /快捷人格 激活人格 <人格ID> 指定人格"
                )
        else:
            yield event.plain_result(f"❌ 新建对话失败: {result}")

    @qp.command("删除人格", alias={"delete"})
    async def cmd_delete(self, event: AstrMessageEvent, persona_id: str = ""):
        """删除人格"""
        if not persona_id:
            yield event.plain_result(
                "请指定人格ID，例如: /快捷人格 删除人格 qp_猫娘_abc123"
            )
            return

        try:
            await self.persona_service.get_persona(persona_id)
        except ValueError:
            yield event.plain_result(f"❌ 未找到人格: {persona_id}")
            return

        # 安全检查：只允许删除本插件创建的人格
        if not persona_id.startswith(PERSONA_PREFIX):
            yield event.plain_result(
                f"⚠️ 人格 {persona_id} 不是由本插件创建的\n"
                f"如果确定要删除，请在 AstrBot 面板中操作"
            )
            return

        success = await self.persona_service.delete_persona(persona_id)
        if success:
            # 清理会话中的当前选中
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)
            if session.current_persona_id == persona_id:
                session.current_persona_id = None

            yield event.plain_result(f"✅ 已删除人格: {persona_id}")
        else:
            yield event.plain_result("❌ 删除失败，请查看日志")
