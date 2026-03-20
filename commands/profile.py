"""用户画像命令模块"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import At

from ..core import ProfileMode
from ..utils import shorten_prompt

if TYPE_CHECKING:
    from ..main import QuickPersona


class ProfileCommands:
    """用户画像命令混入类
    
    包含所有画像相关的命令处理方法。
    设计为混入类，与主插件类一起使用。
    """

    _GROUP_MODE_ALIASES = {"group", "群聊", "群"}
    _GLOBAL_MODE_ALIASES = {"global", "全局"}
    _GROUP_SCOPE_ALIASES = {"current", "group", "当前群", "群聊", "群"}
    _GLOBAL_SCOPE_ALIASES = {"all", "global", "全部", "全局"}

    def _extract_mentioned_user_ids(self, event: AstrMessageEvent) -> list[str]:
        """提取消息链中的 @ 用户，自动跳过机器人自己。"""
        self_id = str(event.get_self_id() or "")
        message_obj = getattr(event, "message_obj", None)
        message_chain = getattr(message_obj, "message", None) or []

        user_ids: list[str] = []
        for comp in message_chain:
            if not isinstance(comp, At):
                continue

            target_id = str(getattr(comp, "qq", "") or "").strip()
            if not target_id or target_id == "all" or (self_id and target_id == self_id):
                continue
            if target_id not in user_ids:
                user_ids.append(target_id)
        return user_ids

    def _normalize_target_user_id(self, user_id: str) -> str:
        """标准化命令中的目标用户 ID。"""
        normalized = str(user_id or "").strip()
        if normalized.startswith("@"):
            normalized = normalized[1:].strip()
        return normalized

    def _resolve_target_user_id(self, event: AstrMessageEvent, user_id: str = "") -> str:
        """优先使用显式参数，其次使用消息中的 @ 用户。"""
        normalized = self._normalize_target_user_id(user_id)
        if normalized:
            return normalized

        mentioned_ids = self._extract_mentioned_user_ids(event)
        return mentioned_ids[0] if mentioned_ids else ""

    def _get_current_group_id(self, event: AstrMessageEvent) -> str:
        """获取当前消息所在群号；私聊返回空字符串。"""
        extractor = getattr(self, "_extract_profile_group_id", None)
        if callable(extractor):
            return extractor(event)
        return ""

    async def profile_help(self: "QuickPersona", event: AstrMessageEvent):
        """显示画像功能帮助"""
        help_text = """👤 用户画像功能 - 命令列表

📡 监控管理
/画像 添加监控 <用户ID/@用户> [模式] - 添加用户画像监控
  模式: global(全局) 或 group(仅当前群，群聊默认)
/画像 移除监控 <用户ID/@用户> [范围] - 移除画像监控
  范围: current(仅当前群，群聊默认) 或 all(全部)
/画像 监控列表 - 查看所有监控配置

📊 画像查看
/画像 查看 <用户ID/@用户> - 查看用户画像
/画像 列表 - 查看所有画像

🔧 管理操作
/画像 强制更新 <用户ID/@用户> - 立即更新画像
/画像 删除 <用户ID/@用户> - 删除用户画像
/画像 缓冲状态 <用户ID/@用户> - 查看消息缓冲区状态

💡 说明：
- 群聊里推荐直接 @用户，默认只监控当前群
- 同一用户可在多个群追加 group 监控，不会互相覆盖
- 斜杠命令消息不会写入画像，减少群聊噪音
- 累积一定消息后自动调用 LLM 生成/更新画像
- 画像数据持久化存储，重启不丢失"""
        yield event.plain_result(help_text)

    async def profile_add_monitor(self: "QuickPersona", event: AstrMessageEvent, user_id: str = "", mode: str = ""):
        """添加用户画像监控"""
        mentioned_ids = self._extract_mentioned_user_ids(event)
        normalized_user_id = self._normalize_target_user_id(user_id)
        normalized_mode = str(mode or "").strip().lower()

        # AstrBot 命令参数里 @ 用户通常不会映射到字符串参数，
        # 因此允许 `/画像 添加监控 @用户 group` 这种写法把模式“左移”回来。
        if (
            not normalized_mode
            and mentioned_ids
            and normalized_user_id.lower() in (self._GROUP_MODE_ALIASES | self._GLOBAL_MODE_ALIASES)
        ):
            normalized_mode = normalized_user_id.lower()
            normalized_user_id = ""

        target_user_id = normalized_user_id or (mentioned_ids[0] if mentioned_ids else "")
        if not target_user_id:
            yield event.plain_result(
                "请指定用户ID或直接 @用户，例如：/画像 添加监控 123456789\n"
                "群聊中可直接使用：/画像 添加监控 @某人"
            )
            return

        current_group_id = self._get_current_group_id(event)
        all_mode_aliases = self._GROUP_MODE_ALIASES | self._GLOBAL_MODE_ALIASES
        if not mentioned_ids and not normalized_mode and normalized_user_id.lower() in all_mode_aliases:
            yield event.plain_result("❌ 请先指定用户ID或 @用户，再选择 global/group 模式")
            return
        if normalized_mode and normalized_mode not in all_mode_aliases:
            yield event.plain_result("❌ 模式仅支持 global(全局) 或 group(当前群)")
            return

        # 群聊里默认用 group，私聊默认用 global，降低误监控范围。
        if normalized_mode in self._GROUP_MODE_ALIASES or (not normalized_mode and current_group_id):
            profile_mode = ProfileMode.GROUP
            if not current_group_id:
                yield event.plain_result("❌ 群聊模式需要在群聊中使用")
                return
            group_ids = [current_group_id]
        else:
            profile_mode = ProfileMode.GLOBAL
            group_ids = []

        creator_id = str(event.get_sender_id() or "")
        existing_monitor = await self.profile_service.get_monitor(target_user_id)
        previous_groups = set(existing_monitor.group_ids) if existing_monitor else set()

        try:
            monitor = await self.profile_service.add_monitor(
                user_id=target_user_id,
                mode=profile_mode,
                group_ids=group_ids,
                created_by=creator_id,
            )

            if monitor.mode == ProfileMode.GLOBAL:
                mode_text = "全局模式"
                if existing_monitor and existing_monitor.mode == ProfileMode.GLOBAL:
                    detail_text = "💡 该用户原本已是全局监控，本次保持全局范围"
                elif existing_monitor and profile_mode == ProfileMode.GROUP:
                    detail_text = "💡 该用户原本已是全局监控，本次未收窄监控范围"
                else:
                    detail_text = "💡 系统会收集该用户在所有群/私聊中的文本消息"
            else:
                total_groups = len(monitor.group_ids)
                mode_text = f"群聊模式 (当前覆盖 {total_groups} 个群)"
                if current_group_id and current_group_id not in previous_groups:
                    detail_text = f"💡 当前群 {current_group_id} 已加入监控范围"
                else:
                    detail_text = "💡 当前群已在监控范围内"

            action_text = "已更新" if existing_monitor else "已添加"
            yield event.plain_result(
                f"✅ {action_text}画像监控\n"
                f"👤 用户ID: {target_user_id}\n"
                f"📡 模式: {mode_text}\n"
                f"{detail_text}"
            )
        except Exception as e:
            logger.error(f"[lzpersona] 添加监控失败: {e}")
            yield event.plain_result(f"❌ 添加失败: {e}")

    async def profile_remove_monitor(self: "QuickPersona", event: AstrMessageEvent, user_id: str = "", scope: str = ""):
        """移除画像监控"""
        target_user_id = self._resolve_target_user_id(event, user_id)
        if not target_user_id:
            yield event.plain_result("请指定用户ID或直接 @用户，例如：/画像 移除监控 123456789")
            return

        current_group_id = self._get_current_group_id(event)
        current_scope = str(scope or "").strip().lower()
        all_scope_aliases = self._GROUP_SCOPE_ALIASES | self._GLOBAL_SCOPE_ALIASES
        if current_scope and current_scope not in all_scope_aliases:
            yield event.plain_result("❌ 范围仅支持 current(当前群) 或 all(全部)")
            return
        if current_scope in self._GROUP_SCOPE_ALIASES and not current_group_id:
            yield event.plain_result("❌ current 范围只能在群聊中使用")
            return

        monitor = await self.profile_service.get_monitor(target_user_id)
        if not monitor:
            yield event.plain_result(f"❌ 未找到用户 {target_user_id} 的监控配置")
            return

        if current_scope in self._GROUP_SCOPE_ALIASES and monitor.mode != ProfileMode.GROUP:
            yield event.plain_result("❌ 该用户当前是全局监控，无法只移除当前群，请改用 all")
            return

        remove_current_group = (
            monitor.mode == ProfileMode.GROUP
            and current_group_id
            and current_scope not in self._GLOBAL_SCOPE_ALIASES
        )

        result = await self.profile_service.remove_monitor_scope(
            target_user_id,
            group_id=current_group_id if remove_current_group else "",
        )

        if result == "removed_group":
            remaining_monitor = await self.profile_service.get_monitor(target_user_id)
            remaining_count = len(remaining_monitor.group_ids) if remaining_monitor else 0
            yield event.plain_result(
                f"✅ 已将用户 {target_user_id} 从当前群的监控范围移除\n"
                f"📡 该用户仍在 {remaining_count} 个群中被监控"
            )
            return

        if result == "removed":
            if remove_current_group and current_group_id:
                yield event.plain_result(f"✅ 已移除用户 {target_user_id} 在当前群的最后一个监控范围")
            else:
                yield event.plain_result(f"✅ 已移除对用户 {target_user_id} 的监控")
            return

        if result == "group_not_found":
            yield event.plain_result(f"❌ 用户 {target_user_id} 当前并未在本群开启监控")
            return

        yield event.plain_result(f"❌ 未找到用户 {target_user_id} 的监控配置")

    async def profile_list_monitors(self: "QuickPersona", event: AstrMessageEvent):
        """查看所有监控配置"""
        monitors = await self.profile_service.get_all_monitors()
        
        if not monitors:
            yield event.plain_result("当前没有任何画像监控")
            return
        
        lines = ["📡 画像监控列表", "-" * 30]
        for m in monitors:
            if m.mode == ProfileMode.GLOBAL:
                mode_text = "🌐全局"
            elif len(m.group_ids) <= 2:
                mode_text = f"👥群聊({', '.join(m.group_ids)})"
            else:
                mode_text = f"👥群聊({', '.join(m.group_ids[:2])} 等{len(m.group_ids)}群)"
            status = "✅启用" if m.enabled else "⏸️暂停"
            lines.append(f"• {m.user_id} | {mode_text} | {status}")
        
        lines.append("-" * 30)
        lines.append(f"共 {len(monitors)} 个监控")
        yield event.plain_result("\n".join(lines))

    async def profile_view(self: "QuickPersona", event: AstrMessageEvent, user_id: str = ""):
        """查看用户画像"""
        target_user_id = self._resolve_target_user_id(event, user_id)
        if not target_user_id:
            yield event.plain_result("请指定用户ID或直接 @用户，例如：/画像 查看 123456789")
            return

        profile = await self.profile_service.get_profile(target_user_id)
        if not profile:
            yield event.plain_result(f"❌ 未找到用户 {target_user_id} 的画像")
            return
        
        # 准备纯文本备用输出
        last_updated = datetime.fromtimestamp(profile.last_updated).strftime("%Y-%m-%d %H:%M") if profile.last_updated else "从未"
        text_lines = [
            f"👤 用户画像: {profile.nickname or target_user_id}",
            "-" * 30,
            f"📝 画像描述: {profile.profile_text or '暂无'}",
            f"🏷️ 性格特征: {', '.join(profile.traits) if profile.traits else '暂无'}",
            f"💡 兴趣爱好: {', '.join(profile.interests) if profile.interests else '暂无'}",
            f"💬 说话风格: {profile.speaking_style or '暂无'}",
            f"❤️ 情感倾向: {profile.emotional_tendency or '暂无'}",
            "-" * 30,
            f"📊 已分析消息: {profile.message_count} 条",
        ]
        
        # 尝试渲染画像卡片（使用 render_service）
        try:
            async for result in self.render_service.render_persona_card(
                event,
                icon="👤",
                title=profile.nickname or "未知用户",
                subtitle=f"用户ID: {profile.user_id}",
                content=profile.profile_text or "暂无画像描述",
                meta_info={
                    "性格特征": ", ".join(profile.traits) if profile.traits else "暂无",
                    "兴趣爱好": ", ".join(profile.interests) if profile.interests else "暂无",
                    "说话风格": profile.speaking_style or "暂无",
                    "情感倾向": profile.emotional_tendency or "暂无",
                    "已分析消息": f"{profile.message_count} 条",
                },
                footer=f"更新时间: {last_updated}",
            ):
                yield result
                return  # 成功渲染后返回
        except Exception as e:
            logger.warning(f"[lzpersona] 画像卡片渲染失败: {e}")
            # 降级为纯文本
            yield event.plain_result("\n".join(text_lines))

    async def profile_list(self: "QuickPersona", event: AstrMessageEvent):
        """查看所有画像"""
        profiles = await self.profile_service.get_all_profiles()
        
        if not profiles:
            yield event.plain_result("当前没有任何用户画像")
            return
        
        lines = ["👥 用户画像列表", "-" * 30]
        for p in profiles:
            name = p.nickname or p.user_id
            preview = shorten_prompt(p.profile_text, 30) if p.profile_text else "暂无描述"
            lines.append(f"• {name}: {preview}")
        
        lines.append("-" * 30)
        lines.append(f"共 {len(profiles)} 个画像")
        yield event.plain_result("\n".join(lines))

    async def profile_force_update(self: "QuickPersona", event: AstrMessageEvent, user_id: str = ""):
        """强制更新画像"""
        target_user_id = self._resolve_target_user_id(event, user_id)
        if not target_user_id:
            yield event.plain_result("请指定用户ID或直接 @用户，例如：/画像 强制更新 123456789")
            return

        buffer_status = await self.profile_service.get_buffer_status(target_user_id)
        if buffer_status["message_count"] == 0:
            yield event.plain_result(f"❌ 用户 {target_user_id} 的消息缓冲区为空，无法更新")
            return
        
        yield event.plain_result(
            f"🔄 正在更新用户 {target_user_id} 的画像...\n"
            f"📝 待处理消息: {buffer_status['message_count']} 条"
        )
        
        success = await self.profile_service.force_update(target_user_id, event)
        if success:
            yield event.plain_result(f"✅ 画像已更新！使用 /画像 查看 {target_user_id} 查看结果")
        else:
            yield event.plain_result("❌ 更新失败，请查看日志")

    async def profile_delete(self: "QuickPersona", event: AstrMessageEvent, user_id: str = ""):
        """删除用户画像"""
        target_user_id = self._resolve_target_user_id(event, user_id)
        if not target_user_id:
            yield event.plain_result("请指定用户ID或直接 @用户，例如：/画像 删除 123456789")
            return

        success = await self.profile_service.delete_profile(target_user_id)
        if success:
            yield event.plain_result(f"✅ 已删除用户 {target_user_id} 的画像和监控配置")
        else:
            yield event.plain_result(f"❌ 未找到用户 {target_user_id} 的画像")

    async def profile_buffer_status(self: "QuickPersona", event: AstrMessageEvent, user_id: str = ""):
        """查看消息缓冲区状态"""
        target_user_id = self._resolve_target_user_id(event, user_id)
        if not target_user_id:
            yield event.plain_result("请指定用户ID或直接 @用户，例如：/画像 缓冲状态 123456789")
            return

        status = await self.profile_service.get_buffer_status(target_user_id)
        yield event.plain_result(
            f"📦 用户 {target_user_id} 的缓冲区状态\n"
            f"📝 待处理消息: {status['message_count']} 条\n"
            f"⏰ 上次更新: {status['last_flush'] or '从未'}"
        )
