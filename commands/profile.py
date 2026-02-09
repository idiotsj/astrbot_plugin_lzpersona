"""用户画像命令模块"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core import ProfileMode
from ..utils import shorten_prompt

if TYPE_CHECKING:
    from ..main import QuickPersona


class ProfileCommands:
    """用户画像命令混入类
    
    包含所有画像相关的命令处理方法。
    设计为混入类，与主插件类一起使用。
    """

    async def profile_help(self: "QuickPersona", event: AstrMessageEvent):
        """显示画像功能帮助"""
        help_text = """👤 用户画像功能 - 命令列表

📡 监控管理
/画像 添加监控 <用户ID> [模式] - 添加用户画像监控
  模式: global(全局) 或 group(仅当前群)
/画像 移除监控 <用户ID> - 移除画像监控
/画像 监控列表 - 查看所有监控配置

📊 画像查看
/画像 查看 <用户ID> - 查看用户画像
/画像 列表 - 查看所有画像

🔧 管理操作
/画像 强制更新 <用户ID> - 立即更新画像
/画像 删除 <用户ID> - 删除用户画像
/画像 缓冲状态 <用户ID> - 查看消息缓冲区状态

💡 说明：
- 添加监控后，系统会自动收集目标用户的消息
- 累积一定消息后自动调用 LLM 生成/更新画像
- 画像数据持久化存储，重启不丢失"""
        yield event.plain_result(help_text)

    async def profile_add_monitor(self: "QuickPersona", event: AstrMessageEvent, user_id: str = "", mode: str = "global"):
        """添加用户画像监控"""
        if not user_id:
            yield event.plain_result(
                "请指定用户ID，例如：/画像 添加监控 123456789\n"
                "可选模式: global(全局) 或 group(仅当前群)"
            )
            return
        
        # 解析模式
        if mode.lower() in ["group", "群聊", "群"]:
            profile_mode = ProfileMode.GROUP
            # 获取当前群ID
            umo = getattr(event, "unified_msg_origin", "")
            group_ids = []
            if ":group:" in umo:
                parts = umo.split(":")
                if len(parts) >= 3:
                    group_ids = [parts[2]]
            
            if not group_ids:
                yield event.plain_result("❌ 群聊模式需要在群聊中使用")
                return
        else:
            profile_mode = ProfileMode.GLOBAL
            group_ids = []
        
        creator_id = str(event.get_sender_id() or "")
        
        try:
            await self.profile_service.add_monitor(
                user_id=user_id,
                mode=profile_mode,
                group_ids=group_ids,
                created_by=creator_id,
            )
            
            mode_text = "全局模式" if profile_mode == ProfileMode.GLOBAL else f"群聊模式 (群: {', '.join(group_ids)})"
            yield event.plain_result(
                f"✅ 已添加画像监控\n"
                f"👤 用户ID: {user_id}\n"
                f"📡 模式: {mode_text}\n"
                f"💡 系统将自动收集该用户的消息并生成画像"
            )
        except Exception as e:
            logger.error(f"[lzpersona] 添加监控失败: {e}")
            yield event.plain_result(f"❌ 添加失败: {e}")

    async def profile_remove_monitor(self: "QuickPersona", event: AstrMessageEvent, user_id: str = ""):
        """移除画像监控"""
        if not user_id:
            yield event.plain_result("请指定用户ID，例如：/画像 移除监控 123456789")
            return
        
        success = await self.profile_service.remove_monitor(user_id)
        if success:
            yield event.plain_result(f"✅ 已移除对用户 {user_id} 的监控")
        else:
            yield event.plain_result(f"❌ 未找到用户 {user_id} 的监控配置")

    async def profile_list_monitors(self: "QuickPersona", event: AstrMessageEvent):
        """查看所有监控配置"""
        monitors = await self.profile_service.get_all_monitors()
        
        if not monitors:
            yield event.plain_result("当前没有任何画像监控")
            return
        
        lines = ["📡 画像监控列表", "-" * 30]
        for m in monitors:
            mode_text = "🌐全局" if m.mode == ProfileMode.GLOBAL else f"👥群聊({', '.join(m.group_ids[:2])})"
            status = "✅启用" if m.enabled else "⏸️暂停"
            lines.append(f"• {m.user_id} | {mode_text} | {status}")
        
        lines.append("-" * 30)
        lines.append(f"共 {len(monitors)} 个监控")
        yield event.plain_result("\n".join(lines))

    async def profile_view(self: "QuickPersona", event: AstrMessageEvent, user_id: str = ""):
        """查看用户画像"""
        if not user_id:
            yield event.plain_result("请指定用户ID，例如：/画像 查看 123456789")
            return
        
        profile = await self.profile_service.get_profile(user_id)
        if not profile:
            yield event.plain_result(f"❌ 未找到用户 {user_id} 的画像")
            return
        
        # 准备纯文本备用输出
        last_updated = datetime.fromtimestamp(profile.last_updated).strftime("%Y-%m-%d %H:%M") if profile.last_updated else "从未"
        text_lines = [
            f"👤 用户画像: {profile.nickname or user_id}",
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
        if not user_id:
            yield event.plain_result("请指定用户ID，例如：/画像 强制更新 123456789")
            return
        
        buffer_status = await self.profile_service.get_buffer_status(user_id)
        if buffer_status["message_count"] == 0:
            yield event.plain_result(f"❌ 用户 {user_id} 的消息缓冲区为空，无法更新")
            return
        
        yield event.plain_result(
            f"🔄 正在更新用户 {user_id} 的画像...\n"
            f"📝 待处理消息: {buffer_status['message_count']} 条"
        )
        
        success = await self.profile_service.force_update(user_id, event)
        if success:
            yield event.plain_result(f"✅ 画像已更新！使用 /画像 查看 {user_id} 查看结果")
        else:
            yield event.plain_result("❌ 更新失败，请查看日志")

    async def profile_delete(self: "QuickPersona", event: AstrMessageEvent, user_id: str = ""):
        """删除用户画像"""
        if not user_id:
            yield event.plain_result("请指定用户ID，例如：/画像 删除 123456789")
            return
        
        success = await self.profile_service.delete_profile(user_id)
        if success:
            yield event.plain_result(f"✅ 已删除用户 {user_id} 的画像和监控配置")
        else:
            yield event.plain_result(f"❌ 未找到用户 {user_id} 的画像")

    async def profile_buffer_status(self: "QuickPersona", event: AstrMessageEvent, user_id: str = ""):
        """查看消息缓冲区状态"""
        if not user_id:
            yield event.plain_result("请指定用户ID，例如：/画像 缓冲状态 123456789")
            return
        
        status = await self.profile_service.get_buffer_status(user_id)
        yield event.plain_result(
            f"📦 用户 {user_id} 的缓冲区状态\n"
            f"📝 待处理消息: {status['message_count']} 条\n"
            f"⏰ 上次更新: {status['last_flush'] or '从未'}"
        )
