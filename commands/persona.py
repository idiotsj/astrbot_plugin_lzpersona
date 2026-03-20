"""人格管理命令模块"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.util import session_waiter, SessionController
from astrbot.core.star.filter.command import GreedyStr

from ..core import (
    PERSONA_PREFIX,
    SessionState,
    PendingPersona,
    parse_format,
    detect_prompt_format,
    get_format_display_name,
)
from ..utils import shorten_prompt, generate_persona_id, get_session_id

if TYPE_CHECKING:
    from ..main import QuickPersona


class PersonaCommands:
    """人格管理命令混入类
    
    包含所有人格相关的命令处理方法。
    设计为混入类，与主插件类一起使用。
    """

    # ==================== 命令组定义 ====================
    # 注意：命令组装饰器需要在主类中应用

    async def _auto_compress_if_needed(
        self: "QuickPersona",
        event: AstrMessageEvent,
        prompt: str,
        format_type,
        stage_label: str,
    ) -> tuple[str, list[str], bool, int, bool]:
        """在结果超长时尝试自动压缩，并返回提示信息。"""
        max_len = max(1, int(self.config.max_prompt_length))
        result = prompt or ""
        result_len = len(result)
        auto_compress = self.config.auto_compress
        notices: list[str] = []
        compressed_applied = False

        logger.debug(
            f"[lzpersona] {stage_label}自动压缩检查: "
            f"result_len={result_len}, max_len={max_len}, auto_compress={auto_compress}"
        )

        if result_len > max_len and auto_compress:
            notices.append(
                f"⚠️ {stage_label}过长({result_len}字符，限制{max_len})，正在自动压缩..."
            )
            compressed = await self.llm_service.shrink_persona(
                result, "轻度", format_type, event
            )

            if not compressed or not compressed.strip():
                notices.append("⚠️ 自动压缩返回空结果，保留原始结果")
            elif len(compressed) >= result_len:
                notices.append(
                    f"⚠️ 自动压缩后长度未减少({len(compressed)}字符)，保留原始结果"
                )
            elif len(compressed) < max_len * 0.3:
                notices.append(
                    f"⚠️ 自动压缩后过短({len(compressed)}字符)，保留原始结果"
                )
            else:
                result = compressed
                compressed_applied = True
                notices.append(
                    f"✅ 自动压缩完成: {result_len} → {len(result)} 字符"
                )
        elif result_len > max_len:
            notices.append(
                f"⚠️ {stage_label}长度为 {result_len} 字符，已超过限制 {max_len}，且未开启自动压缩"
            )

        within_limit = len(result) <= max_len
        if not within_limit:
            notices.append(
                f"⚠️ 当前结果仍超出长度限制({len(result)}/{max_len})，"
                "建议继续使用 /快捷人格 压缩人格"
            )

        return result, notices, within_limit, result_len, compressed_applied

    async def cmd_help(self: "QuickPersona", event: AstrMessageEvent):
        """显示帮助信息"""
        try:
            help_text = """快捷人格生成器 - 命令列表

🤖 智能入口（推荐）
/快捷人格 智能 <自然语言> - 智能识别意图，自动执行
/快捷人格 <自然语言> - 简写形式，同上

📝 生成与优化
/快捷人格 生成人格 <描述> - 根据描述生成人格
/快捷人格 优化人格 <反馈> - 优化人格（可直接优化未生成的人格）
/快捷人格 压缩人格 [强度] - 压缩提示词(轻度/中度/极限)
/快捷人格 转换格式 <格式> - 转换提示词格式(natural/markdown/xml/json/yaml)

📋 管理
/快捷人格 查看状态 - 查看当前状态
/快捷人格 确认生成 - 确认并保存待确认的人格
/快捷人格 取消操作 - 取消待确认的人格
/快捷人格 人格列表 - 列出所有人格
/快捷人格 选择人格 <人格ID> - 选择人格
/快捷人格 应用人格 [人格ID] - 应用人格到当前对话
/快捷人格 删除人格 <人格ID> - 删除人格

💡 使用流程示例：
  /快捷人格 生成一个傲娇猫娘  → 生成人格
  /快捷人格 让她更傲娇一点    → 直接优化未生成的人格
  /快捷人格 确认              → 满意后保存人格
  /快捷人格 应用              → 让AI使用此人格

📌 别名：qp, quickpersona"""
            yield event.plain_result(help_text)
        finally:
            event.stop_event()

    async def cmd_smart(self: "QuickPersona", event: AstrMessageEvent, query: str = ""):
        """智能意图识别入口"""
        query = str(query).strip()

        if not query:
            async for r in self.cmd_help(event):
                yield r
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        # 构建上下文信息
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

        # 调用 LLM 识别意图
        intent = await self.llm_service.recognize_intent(query, context_info, event)
        action = intent.get("action", "help")

        logger.info(f"[lzpersona] 智能识别: query={query}, intent={intent}")

        # 路由到相应的处理方法
        if action == "generate":
            desc = intent.get("description", "") or query
            async for r in self.cmd_gen(event, desc):
                yield r
        elif action == "refine":
            fb = intent.get("feedback", "") or query
            async for r in self.cmd_refine(event, fb):
                yield r
        elif action == "shrink":
            intensity = intent.get("intensity", "轻度") or "轻度"
            async for r in self.cmd_shrink(event, intensity):
                yield r
        elif action == "list":
            async for r in self.cmd_list(event):
                yield r
        elif action == "view":
            pid = intent.get("persona_id", "")
            async for r in self.cmd_view(event, pid):
                yield r
        elif action == "activate":
            pid = intent.get("persona_id", "")
            if pid:
                async for r in self.cmd_activate(event, pid):
                    yield r
            else:
                yield event.plain_result(
                    "请指定要激活的人格，例如：/快捷人格 智能 切换到猫娘\n"
                    f"可用人格: {persona_list}"
                )
        elif action == "delete":
            pid = intent.get("persona_id", "")
            if pid:
                async for r in self.cmd_delete(event, pid):
                    yield r
            else:
                yield event.plain_result("请指定要删除的人格ID")
        elif action == "rollback":
            async for r in self.cmd_rollback(event):
                yield r
        elif action == "status":
            async for r in self.cmd_status(event):
                yield r
        elif action == "apply":
            async for r in self.cmd_apply(event):
                yield r
        elif action == "cancel":
            async for r in self.cmd_cancel(event):
                yield r
        else:
            async for r in self.cmd_help(event):
                yield r
        
        event.stop_event()

    async def cmd_gen(self: "QuickPersona", event: AstrMessageEvent, description: str = ""):
        """根据描述生成人格（支持引导式生成）"""
        # 优先使用命令解析器传入的参数
        description = str(description).strip()

        # 如果参数为空，尝试从消息中提取（兼容多行描述）
        if not description:
            raw_message = (event.get_message_str() or "").strip()
            # 查找命令关键词后的内容（不依赖特定前缀）
            for keyword in ["生成人格", "gen"]:
                idx = raw_message.lower().find(keyword.lower())
                if idx != -1:
                    description = raw_message[idx + len(keyword):].strip()
                    break

        if not description:
            yield event.plain_result(
                "请提供人格描述，例如：/快捷人格 生成人格 一个温柔的猫娘"
            )
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        if session.state == SessionState.WAITING_CONFIRM:
            yield event.plain_result(
                "你有一个待确认的人格，请先 /快捷人格 确认生成 或 /快捷人格 取消操作"
            )
            return

        # 检查是否启用引导式生成
        if self.config.enable_guided_generation:
            async for r in self._guided_generation(event, description, session):
                yield r
        else:
            async for r in self._quick_generation(event, description, session):
                yield r

    async def _guided_generation(self: "QuickPersona", event: AstrMessageEvent, description: str, session):
        """引导式生成流程"""
        yield event.plain_result(f"🎭 正在分析你的人格描述...\n描述: {description}")

        # 分析缺失字段
        analysis = await self.llm_service.analyze_missing_fields(description, event)
        missing_fields = analysis.get("missing", [])
        provided_fields = analysis.get("provided", [])

        if not missing_fields:
            yield event.plain_result("✅ 描述完整，正在生成人格...")
            async for r in self._quick_generation(event, description, session):
                yield r
            return

        # 构建缺失字段提示信息
        lines = ["📋 检测到以下设定缺失，请选择要补充的内容：", ""]
        for i, field in enumerate(missing_fields, 1):
            label = field.get("label", field.get("field", "未知"))
            hint = field.get("hint", "")
            lines.append(f"{i}️⃣ {label}（{hint}）")

        lines.extend([
            "",
            "💡 回复对应数字（如\"2,3\"）并补充内容",
            "💡 回复\"跳过\"让 AI 自动生成所有缺失部分",
        ])

        yield event.plain_result("\n".join(lines))

        # 保存状态，等待用户回复
        session.state = SessionState.WAITING_MISSING_INPUT
        session.pending_persona = PendingPersona(
            persona_id="",
            system_prompt="",
            created_at=time.time(),
            mode="guided",
            original_description=description,
            missing_fields=missing_fields,
            provided_fields=provided_fields,
        )

        # 使用 session_waiter 等待用户回复
        @session_waiter(timeout=120, record_history_chains=False)
        async def wait_for_missing_input(controller: SessionController, w_event: AstrMessageEvent):
            message_text = w_event.message_str.strip() if w_event.message_str else ""
            if not message_text:
                controller.keep(timeout=120)
                return
            if not controller.future.done():
                controller.future.set_result(w_event)

        try:
            user_reply_event = await wait_for_missing_input(event)
            user_reply = user_reply_event.message_str.strip()
        except TimeoutError:
            session.state = SessionState.IDLE
            session.pending_persona = None
            yield event.plain_result("⏰ 等待超时，已取消生成")
            event.stop_event()
            return

        # 处理用户回复
        async for r in self._process_missing_input(
            event, user_reply, description, missing_fields, provided_fields, session
        ):
            yield r

    async def _process_missing_input(
        self: "QuickPersona", event: AstrMessageEvent, user_reply: str, 
        description: str, missing_fields: list, provided_fields: list, session
    ):
        """处理用户对缺失字段的回复"""
        user_reply = user_reply.strip()

        if user_reply.lower() in ["跳过", "skip", "s"]:
            yield event.plain_result("⏭️ 已跳过，AI 将自动生成缺失部分...")
            auto_generate_fields = [f.get("label", f.get("field")) for f in missing_fields]
            async for r in self._generate_with_supplements(
                event, description, "", auto_generate_fields, session
            ):
                yield r
            return

        # 解析用户选择的字段编号和补充内容
        match = re.match(r'^([\d,，、\s]+)\s*(.*)$', user_reply)
        
        if not match:
            yield event.plain_result("📝 已收到补充信息，正在生成人格...")
            auto_generate_fields = [f.get("label", f.get("field")) for f in missing_fields]
            async for r in self._generate_with_supplements(
                event, description, user_reply, auto_generate_fields, session
            ):
                yield r
            return

        selected_nums_str = match.group(1)
        supplements = match.group(2).strip()

        selected_nums = set()
        for num in re.findall(r'\d+', selected_nums_str):
            selected_nums.add(num)

        user_selected_fields = []
        auto_generate_fields = []

        for i, field in enumerate(missing_fields, 1):
            label = field.get("label", field.get("field"))
            if str(i) in selected_nums:
                user_selected_fields.append(label)
            else:
                auto_generate_fields.append(label)

        if user_selected_fields:
            supplements_info = f"用户为以下字段提供了信息: {', '.join(user_selected_fields)}\n内容: {supplements}"
        else:
            supplements_info = supplements

        yield event.plain_result(
            f"✅ 已收集，正在生成完整人格...\n"
            f"📝 用户补充: {', '.join(user_selected_fields) if user_selected_fields else '无'}\n"
            f"🤖 AI 生成: {', '.join(auto_generate_fields) if auto_generate_fields else '无'}"
        )

        async for r in self._generate_with_supplements(
            event, description, supplements_info, auto_generate_fields, session
        ):
            yield r

    async def _generate_with_supplements(
        self: "QuickPersona", event: AstrMessageEvent, description: str, 
        supplements: str, auto_generate_fields: list, session
    ):
        """根据补充信息生成人格"""
        target_format = self.config.default_format
        result = await self.llm_service.generate_with_supplements(
            description, supplements, auto_generate_fields, event, target_format
        )

        if not result:
            session.state = SessionState.IDLE
            session.pending_persona = None
            yield event.plain_result("❌ 生成失败，请检查 LLM 配置或稍后重试")
            return

        result, notices, within_limit, original_len, compressed_applied = await self._auto_compress_if_needed(
            event, result, target_format, "生成结果"
        )
        for notice in notices:
            yield event.plain_result(notice)

        persona_id = generate_persona_id(description)

        if self.config.confirm_before_apply:
            session.state = SessionState.WAITING_CONFIRM
            session.pending_persona = PendingPersona(
                persona_id=persona_id,
                system_prompt=result,
                created_at=time.time(),
                mode="guided",
            )

            async for r in self.render.render_persona_card(
                event, icon="🎭", title="人格生成完成",
                subtitle="模式: 引导式生成 | 待确认",
                content=result,
                meta_info={
                    "人格ID": persona_id,
                    "字符数": str(len(result)),
                    "格式": get_format_display_name(target_format),
                } | (
                    {
                        "原始长度": str(original_len),
                        "自动压缩": "是",
                    }
                    if compressed_applied
                    else {}
                ),
                footer=(
                    "发送 /快捷人格 确认生成 或 /快捷人格 取消操作"
                    if within_limit
                    else "可继续 /快捷人格 压缩人格，或确认后再手动调整"
                )
            ):
                yield r
        else:
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(
                persona_id, result, backup=False, user_name=user_name
            )
            if success:
                session.state = SessionState.IDLE
                session.pending_persona = None
                session.current_persona_id = persona_id
                async for r in self.render.render_persona_card(
                    event, icon="✅", title="人格已创建并选中",
                    subtitle="模式: 引导式生成",
                    content=result,
                    meta_info={
                        "人格ID": persona_id,
                        "字符数": str(len(result)),
                        "格式": get_format_display_name(target_format),
                    } | (
                        {
                            "原始长度": str(original_len),
                            "自动压缩": "是",
                        }
                        if compressed_applied
                        else {}
                    ),
                    footer=(
                        "使用 /快捷人格 应用人格 让 AI 使用此人格"
                        if within_limit
                        else "当前结果仍超限；可先 /快捷人格 压缩人格，再 /快捷人格 应用人格"
                    ),
                ):
                    yield r
            else:
                session.state = SessionState.IDLE
                session.pending_persona = None
                yield event.plain_result("❌ 保存人格失败，请查看日志")

    async def _quick_generation(self: "QuickPersona", event: AstrMessageEvent, description: str, session):
        """快速生成流程（使用 LLMService 高级方法）"""
        yield event.plain_result(f"🔄 正在根据描述生成人格...\n描述: {description}")

        # 使用 LLMService 高级方法
        target_format = self.config.default_format
        result = await self.llm_service.generate_persona(description, event, target_format)

        if not result:
            yield event.plain_result("❌ 生成失败，请检查 LLM 配置或稍后重试")
            return

        result, notices, within_limit, original_len, compressed_applied = await self._auto_compress_if_needed(
            event, result, target_format, "生成结果"
        )
        for notice in notices:
            yield event.plain_result(notice)

        persona_id = generate_persona_id(description)

        if self.config.confirm_before_apply:
            session.state = SessionState.WAITING_CONFIRM
            session.pending_persona = PendingPersona(
                persona_id=persona_id,
                system_prompt=result,
                created_at=time.time(),
                mode="generate",
            )

            async for r in self.render.render_persona_card(
                event, icon="🎭", title="人格生成完成",
                subtitle="模式: 快速生成 | 待确认",
                content=result,
                meta_info={
                    "人格ID": persona_id,
                    "字符数": str(len(result)),
                    "格式": get_format_display_name(target_format),
                } | (
                    {
                        "原始长度": str(original_len),
                        "自动压缩": "是",
                    }
                    if compressed_applied
                    else {}
                ),
                footer=(
                    "发送 /快捷人格 确认生成 或 /快捷人格 取消操作"
                    if within_limit
                    else "可继续 /快捷人格 压缩人格，或确认后再手动调整"
                )
            ):
                yield r
        else:
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(
                persona_id, result, backup=False, user_name=user_name
            )
            if success:
                session.state = SessionState.IDLE
                session.pending_persona = None
                session.current_persona_id = persona_id
                async for r in self.render.render_persona_card(
                    event, icon="✅", title="人格已创建并选中",
                    subtitle="模式: 快速生成",
                    content=result,
                    meta_info={
                        "人格ID": persona_id,
                        "字符数": str(len(result)),
                        "格式": get_format_display_name(target_format),
                    } | (
                        {
                            "原始长度": str(original_len),
                            "自动压缩": "是",
                        }
                        if compressed_applied
                        else {}
                    ),
                    footer=(
                        "使用 /快捷人格 应用人格 让 AI 使用此人格"
                        if within_limit
                        else "当前结果仍超限；可先 /快捷人格 压缩人格，再 /快捷人格 应用人格"
                    ),
                ):
                    yield r
            else:
                session.state = SessionState.IDLE
                session.pending_persona = None
                yield event.plain_result("❌ 保存人格失败，请查看日志")

    async def cmd_apply(self: "QuickPersona", event: AstrMessageEvent):
        """确认并保存待确认的人格"""
        try:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)

            if session.state != SessionState.WAITING_CONFIRM or not session.pending_persona:
                yield event.plain_result("没有待确认的人格")
                return

            pending = session.pending_persona
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(
                pending.persona_id, pending.system_prompt, backup=True, user_name=user_name
            )

            if success:
                session.current_persona_id = pending.persona_id
                session.state = SessionState.IDLE
                session.pending_persona = None
                yield event.plain_result(
                    f"✅ 人格已保存！\n📌 人格ID: {pending.persona_id}\n"
                    f"💡 使用 /快捷人格 应用人格 让 AI 使用此人格"
                )
            else:
                yield event.plain_result("❌ 保存失败，请查看日志")
        except Exception as e:
            logger.error(f"[lzpersona] 保存人格失败: {e}")
            yield event.plain_result(f"❌ 保存人格失败: {e}")
        finally:
            event.stop_event()

    async def cmd_cancel(self: "QuickPersona", event: AstrMessageEvent):
        """取消待确认的人格"""
        try:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)

            if session.state != SessionState.WAITING_CONFIRM:
                yield event.plain_result("没有待确认的人格")
                return

            session.state = SessionState.IDLE
            session.pending_persona = None
            yield event.plain_result("✅ 已取消")
        finally:
            event.stop_event()

    async def cmd_status(self: "QuickPersona", event: AstrMessageEvent):
        """查看当前状态"""
        try:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)

            lines = ["📊 当前状态", f"会话状态: {session.state.value}"]
            if session.current_persona_id:
                lines.append(f"当前人格: {session.current_persona_id}")

            if session.pending_persona:
                p = session.pending_persona
                lines.append("\n📌 待确认人格:")
                lines.append(f"  ID: {p.persona_id}")
                lines.append(f"  模式: {p.mode}")
                lines.append(f"  创建于: {datetime.fromtimestamp(p.created_at).strftime('%H:%M:%S')}")
                lines.append(f"  提示词预览: {shorten_prompt(p.system_prompt, 100)}")

            yield event.plain_result("\n".join(lines))
        finally:
            event.stop_event()

    async def cmd_list(self: "QuickPersona", event: AstrMessageEvent):
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
            yield event.plain_result(f"❌ 获取列表失败: {e}")
        finally:
            event.stop_event()

    async def cmd_view(self: "QuickPersona", event: AstrMessageEvent, persona_id: str = ""):
        """查看人格详情"""
        if not persona_id:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)
            persona_id = session.current_persona_id or ""

        if not persona_id:
            yield event.plain_result("请指定人格ID，例如: /快捷人格 查看详情 qp_猫娘_abc123")
            return

        try:
            persona = await self.persona_service.get_persona(persona_id)

            extra_lines = [f"字符数: {len(persona.system_prompt)}"]
            if persona_id in self.state.backups:
                backup_count = len(self.state.backups[persona_id])
                extra_lines.append(f"历史版本: {backup_count} 个")

            async for result in self.render.render_long_text(
                event, f"人格详情: {persona.persona_id}",
                persona.system_prompt, "\n".join(extra_lines),
            ):
                yield result
        except ValueError:
            yield event.plain_result(f"❌ 未找到人格: {persona_id}")
        except Exception as e:
            logger.error(f"[lzpersona] 查看人格失败: {e}")
            yield event.plain_result("❌ 查看失败")

    async def cmd_history(self: "QuickPersona", event: AstrMessageEvent, persona_id: str = ""):
        """查看历史版本"""
        if not persona_id:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)
            persona_id = session.current_persona_id or ""

        if not persona_id:
            yield event.plain_result("请指定人格ID，例如: /快捷人格 历史版本 qp_猫娘_abc123")
            return

        backups = self.state.get_all_backups(persona_id)
        if not backups:
            yield event.plain_result(f"❌ 没有找到 {persona_id} 的历史版本")
            return

        lines = [f"📜 {persona_id} 的历史版本 (共 {len(backups)} 个)", "-" * 30]
        for i, backup in enumerate(backups):
            backup_time = datetime.fromtimestamp(backup.backed_up_at).strftime("%Y-%m-%d %H:%M:%S")
            preview = shorten_prompt(backup.system_prompt, 50)
            lines.append(f"{i + 1}. [{backup_time}]")
            lines.append(f"   {preview}")

        lines.extend(["-" * 30, "💡 使用 /快捷人格 版本回滚 可回滚到最新备份"])
        yield event.plain_result("\n".join(lines))

    async def cmd_rollback(self: "QuickPersona", event: AstrMessageEvent, persona_id: str = ""):
        """回滚到上一个版本"""
        try:
            if not persona_id:
                session_id = get_session_id(event)
                session = self.state.get_session(session_id)
                persona_id = session.current_persona_id or ""

            if not persona_id:
                yield event.plain_result("请指定人格ID，例如: /快捷人格 版本回滚 qp_猫娘_abc123")
                return

            backup = self.state.get_latest_backup(persona_id)
            if not backup:
                yield event.plain_result(f"❌ 没有找到 {persona_id} 的备份")
                return

            backup_time = datetime.fromtimestamp(backup.backed_up_at).strftime("%Y-%m-%d %H:%M:%S")
            backup_prompt = backup.system_prompt  # 保存备份内容，防止后续操作失败

            # 先更新人格
            await self.context.persona_manager.update_persona(
                persona_id=persona_id, system_prompt=backup_prompt
            )

            # 更新成功后再删除备份并保存
            if persona_id in self.state.backups and self.state.backups[persona_id]:
                self.state.backups[persona_id].pop(0)
                try:
                    await self.state.save_backups()
                except Exception as e:
                    logger.warning(f"[lzpersona] 保存备份状态失败: {e}，但回滚已成功")

            yield event.plain_result(
                f"✅ 已回滚到 {backup_time} 的版本\n"
                f"📝 提示词预览: {shorten_prompt(backup_prompt, 200)}"
            )
        except Exception as e:
            logger.error(f"[lzpersona] 回滚失败: {e}")
            yield event.plain_result(f"❌ 回滚失败: {e}")
        finally:
            event.stop_event()

    async def cmd_refine(self: "QuickPersona", event: AstrMessageEvent, feedback: str = ""):
        """根据反馈优化当前人格"""
        feedback = str(feedback).strip()

        if not feedback:
            yield event.plain_result("请提供优化反馈，例如：/快捷人格 优化人格 说话再可爱一点")
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        # 检查是否有待确认的人格
        if session.state == SessionState.WAITING_CONFIRM and session.pending_persona:
            pending = session.pending_persona
            current_prompt = pending.system_prompt
            persona_id = pending.persona_id
            is_pending = True
            yield event.plain_result(f"🔄 正在优化待确认的人格...\n📌 人格ID: {persona_id}\n反馈: {feedback}")
        else:
            persona_id = session.current_persona_id
            is_pending = False
            if not persona_id:
                yield event.plain_result("请先使用 /快捷人格 选择人格 <人格ID> 选择一个人格")
                return
            try:
                persona = await self.persona_service.get_persona(persona_id)
                current_prompt = persona.system_prompt
            except ValueError:
                yield event.plain_result(f"❌ 未找到人格: {persona_id}")
                return
            yield event.plain_result(f"🔄 正在根据反馈优化人格...\n反馈: {feedback}")

        # 使用 LLMService 高级方法
        current_format = detect_prompt_format(current_prompt, self.config.default_format)
        result = await self.llm_service.refine_persona(current_prompt, feedback, current_format, event)

        if not result:
            yield event.plain_result("❌ 优化失败，请稍后重试")
            return

        result, notices, within_limit, original_len, compressed_applied = await self._auto_compress_if_needed(
            event, result, current_format, "优化结果"
        )
        for notice in notices:
            yield event.plain_result(notice)

        if self.config.confirm_before_apply:
            session.state = SessionState.WAITING_CONFIRM
            session.pending_persona = PendingPersona(
                persona_id=persona_id, system_prompt=result,
                created_at=time.time(), mode="refine", original_prompt=current_prompt,
            )
            status_hint = "（已更新待确认人格）" if is_pending else ""
            async for r in self.render.render_persona_card(
                event, icon="✨", title=f"人格优化完成{status_hint}",
                subtitle="模式: 优化 | 待确认", content=result,
                meta_info={
                    "人格ID": persona_id,
                    "字符数": str(len(result)),
                    "格式": get_format_display_name(current_format),
                } | (
                    {
                        "原始长度": str(original_len),
                        "自动压缩": "是",
                    }
                    if compressed_applied
                    else {}
                ),
                footer=(
                    "可继续发送反馈优化，或 /快捷人格 确认生成"
                    if within_limit
                    else "可继续反馈优化，或先 /快捷人格 压缩人格"
                )
            ):
                yield r
        else:
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(persona_id, result, backup=True, user_name=user_name)
            if success:
                session.state = SessionState.IDLE
                session.pending_persona = None
                async for r in self.render.render_persona_card(
                    event, icon="✅", title="人格已优化", subtitle="模式: 优化",
                    content=result,
                    meta_info={
                        "人格ID": persona_id,
                        "字符数": str(len(result)),
                        "格式": get_format_display_name(current_format),
                    } | (
                        {
                            "原始长度": str(original_len),
                            "自动压缩": "是",
                        }
                        if compressed_applied
                        else {}
                    ),
                    footer=(
                        "使用 /快捷人格 应用人格 让 AI 使用此人格"
                        if within_limit
                        else "当前结果仍超限；可继续 /快捷人格 压缩人格"
                    ),
                ):
                    yield r
            else:
                yield event.plain_result("❌ 保存失败，请查看日志")

    async def cmd_shrink(self: "QuickPersona", event: AstrMessageEvent, intensity: str = "轻度"):
        """压缩人格提示词"""
        session_id = get_session_id(event)
        session = self.state.get_session(session_id)
        is_pending = False

        if session.state == SessionState.WAITING_CONFIRM and session.pending_persona:
            persona_id = session.pending_persona.persona_id
            current_prompt = session.pending_persona.system_prompt
            is_pending = True
            yield event.plain_result(
                f"🔄 正在压缩待确认的人格...\n📌 人格ID: {persona_id}"
            )
        else:
            persona_id = session.current_persona_id

            if not persona_id:
                yield event.plain_result("请先使用 /快捷人格 选择人格 <人格ID> 选择一个人格")
                return

            try:
                persona = await self.persona_service.get_persona(persona_id)
                current_prompt = persona.system_prompt
            except ValueError:
                yield event.plain_result(f"❌ 未找到人格: {persona_id}")
                return

        valid_intensities = ["轻度", "中度", "极限"]
        if intensity not in valid_intensities:
            intensity = "轻度"

        original_len = len(current_prompt)
        if not is_pending:
            yield event.plain_result(
                f"🔄 正在压缩人格提示词...\n原始长度: {original_len}字符\n压缩强度: {intensity}"
            )
        else:
            yield event.plain_result(
                f"📝 当前待确认版本长度: {original_len}字符\n压缩强度: {intensity}"
            )

        # 使用 LLMService 高级方法
        current_format = detect_prompt_format(current_prompt, self.config.default_format)
        result = await self.llm_service.shrink_persona(current_prompt, intensity, current_format, event)

        if not result or not result.strip():
            yield event.plain_result("❌ 压缩失败：返回空结果")
            return

        new_len = len(result)
        reduction = round((1 - new_len / original_len) * 100, 1) if original_len > 0 else 0

        # 检查压缩效果
        if new_len >= original_len:
            yield event.plain_result(f"⚠️ 压缩后长度未减少({new_len}字符)，建议不使用此结果")
            return

        if new_len < 50:
            yield event.plain_result(f"⚠️ 压缩后过短({new_len}字符)，可能丢失关键信息，建议不使用此结果")
            return

        if new_len > self.config.max_prompt_length:
            yield event.plain_result(
                f"⚠️ 压缩后仍超出长度限制({new_len}/{self.config.max_prompt_length})，"
                "可继续压缩或提高强度"
            )

        if self.config.confirm_before_apply:
            session.state = SessionState.WAITING_CONFIRM
            session.pending_persona = PendingPersona(
                persona_id=persona_id, system_prompt=result,
                created_at=time.time(), mode="shrink", original_prompt=current_prompt,
            )
            async for r in self.render.render_persona_card(
                event,
                icon="📦",
                title="压缩完成（已更新待确认人格）" if is_pending else "压缩完成",
                subtitle=f"强度: {intensity} | 待确认",
                content=result,
                meta_info={
                    "人格ID": persona_id,
                    "压缩效果": f"{original_len} → {new_len} 字符",
                    "减少比例": f"{reduction}%",
                    "格式": get_format_display_name(current_format),
                },
                footer=(
                    "可继续 /快捷人格 优化人格，或 /快捷人格 确认生成"
                    if is_pending
                    else "发送 /快捷人格 确认生成 或 /快捷人格 取消操作"
                )
            ):
                yield r
        else:
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(persona_id, result, backup=True, user_name=user_name)
            if success:
                session.state = SessionState.IDLE
                session.pending_persona = None
                async for r in self.render.render_persona_card(
                    event, icon="✅", title="压缩完成并已保存", subtitle=f"强度: {intensity}",
                    content=result,
                    meta_info={
                        "人格ID": persona_id,
                        "压缩效果": f"{original_len} → {new_len} 字符",
                        "减少比例": f"{reduction}%",
                        "格式": get_format_display_name(current_format),
                    },
                    footer="使用 /快捷人格 应用人格 让 AI 使用此人格",
                ):
                    yield r
            else:
                yield event.plain_result("❌ 保存失败，请查看日志")

    async def cmd_use(self: "QuickPersona", event: AstrMessageEvent, persona_id: str = ""):
        """选择一个人格"""
        if not persona_id:
            yield event.plain_result("请指定人格ID，例如: /快捷人格 选择人格 qp_猫娘_abc123")
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
            f"✅ 已选择人格: {persona_id}\n后续的 优化人格/压缩人格 操作将针对此人格\n\n💡 使用 /快捷人格 应用人格 应用到当前对话"
        )

    async def cmd_activate(self: "QuickPersona", event: AstrMessageEvent, persona_id: str = ""):
        """应用人格到当前对话"""
        try:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)

            if not persona_id:
                persona_id = session.current_persona_id or ""

            if not persona_id:
                yield event.plain_result("请指定人格ID，例如: /快捷人格 应用人格 qp_猫娘_abc123")
                return

            try:
                await self.persona_service.get_persona(persona_id)
            except ValueError:
                yield event.plain_result(f"❌ 未找到人格: {persona_id}")
                return

            # 使用属性访问 unified_msg_origin（推荐方式）
            umo = event.unified_msg_origin
            if not umo:
                yield event.plain_result("❌ 无法获取会话信息")
                return

            success, msg = await self.persona_service.activate_persona(umo, persona_id)
            if success:
                session.current_persona_id = persona_id
                yield event.plain_result(f"✅ {msg}\n📌 AI 的下一条回复将使用新人格")
            else:
                yield event.plain_result(f"❌ 应用失败: {msg}")
        except Exception as e:
            logger.error(f"[lzpersona] 应用人格失败: {e}")
            yield event.plain_result(f"❌ 应用人格失败: {e}")
        finally:
            event.stop_event()

    async def cmd_delete(self: "QuickPersona", event: AstrMessageEvent, persona_id: str = ""):
        """删除人格"""
        try:
            if not persona_id:
                yield event.plain_result("请指定人格ID，例如: /快捷人格 删除人格 qp_猫娘_abc123")
                return

            try:
                await self.persona_service.get_persona(persona_id)
            except ValueError:
                yield event.plain_result(f"❌ 未找到人格: {persona_id}")
                return

            if not persona_id.startswith(PERSONA_PREFIX):
                yield event.plain_result(f"⚠️ 人格 {persona_id} 不是由本插件创建的\n如果确定要删除，请在 AstrBot 面板中操作")
                return

            success = await self.persona_service.delete_persona(persona_id)
            if success:
                session_id = get_session_id(event)
                session = self.state.get_session(session_id)
                if session.current_persona_id == persona_id:
                    session.current_persona_id = None
                yield event.plain_result(f"✅ 已删除人格: {persona_id}")
            else:
                yield event.plain_result("❌ 删除失败，请查看日志")
        except Exception as e:
            logger.error(f"[lzpersona] 删除人格失败: {e}")
            yield event.plain_result(f"❌ 删除人格失败: {e}")
        finally:
            event.stop_event()

    async def cmd_convert_format(self: "QuickPersona", event: AstrMessageEvent, target_format: str = ""):
        """将人格转换为指定格式"""
        if not target_format:
            formats = "natural(自然语言), markdown(MD), xml, json, yaml"
            yield event.plain_result(f"请指定目标格式：{formats}\n例如：/快捷人格 转换格式 markdown")
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        if session.state == SessionState.WAITING_CONFIRM and session.pending_persona:
            current_prompt = session.pending_persona.system_prompt
            persona_id = session.pending_persona.persona_id
        elif session.current_persona_id:
            try:
                persona = await self.persona_service.get_persona(session.current_persona_id)
                current_prompt = persona.system_prompt
                persona_id = session.current_persona_id
            except ValueError:
                yield event.plain_result(f"❌ 未找到人格: {session.current_persona_id}")
                return
        else:
            yield event.plain_result("请先选择或生成一个人格")
            return

        target = parse_format(target_format)
        source = detect_prompt_format(current_prompt, self.config.default_format)
        target_name = get_format_display_name(target)
        source_name = get_format_display_name(source)

        if source == target:
            yield event.plain_result(f"当前人格已经是 {target_name} 格式，无需转换")
            return

        yield event.plain_result(f"🔄 正在将人格转换为 {target_name} 格式...")

        result = await self.llm_service.convert_format(current_prompt, source, target, event)
        if not result:
            yield event.plain_result("❌ 格式转换失败")
            return

        session.state = SessionState.WAITING_CONFIRM
        session.pending_persona = PendingPersona(
            persona_id=persona_id, system_prompt=result,
            created_at=time.time(), mode="convert", original_prompt=current_prompt,
        )

        async for r in self.render.render_persona_card(
            event, icon="🔄", title="格式转换完成",
            subtitle=f"目标格式: {target_name} | 待确认", content=result,
            meta_info={
                "人格ID": persona_id,
                "字符数": str(len(result)),
                "源格式": source_name,
                "目标格式": target_name,
            },
            footer="发送 /快捷人格 确认生成 或 /快捷人格 取消操作"
        ):
            yield r

    async def cmd_newchat(self: "QuickPersona", event: AstrMessageEvent, persona_id: str = ""):
        """新建对话"""
        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        if not persona_id:
            persona_id = session.current_persona_id or ""

        # 使用属性访问 unified_msg_origin（推荐方式）
        umo = event.unified_msg_origin
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
                yield event.plain_result(f"✅ 已创建新对话并应用人格\n📌 对话ID: {result}\n🎭 人格: {persona_id}")
            else:
                yield event.plain_result(f"✅ 已创建新对话\n📌 对话ID: {result}\n💡 使用 /快捷人格 应用人格 <人格ID> 指定人格")
        else:
            yield event.plain_result(f"❌ 新建对话失败: {result}")
