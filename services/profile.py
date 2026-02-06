"""用户画像服务"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from astrbot.api import logger

from ..core.profile_models import (
    UserProfile,
    ProfileMonitor,
    ProfileMode,
    MessageBuffer,
)
from ..core.profile_constants import (
    DEFAULT_PROFILE_UPDATE_TEMPLATE,
    DEFAULT_PROFILE_INIT_TEMPLATE,
)

if TYPE_CHECKING:
    from astrbot.api.star import Context
    from astrbot.api.event import AstrMessageEvent


class ProfileService:
    """用户画像服务
    
    负责：
    1. 管理画像监控配置
    2. 收集目标用户消息到缓冲区
    3. 调用 LLM 更新画像
    4. 持久化存储画像数据
    """

    # KV 存储的键前缀
    KV_PROFILES = "user_profiles"      # 用户画像数据
    KV_MONITORS = "profile_monitors"   # 监控配置
    KV_BUFFERS = "message_buffers"     # 消息缓冲区

    def __init__(self, context: "Context", plugin_instance):
        self.context = context
        self.plugin = plugin_instance  # 用于调用 KV 存储和 LLM
        
        # 内存缓存
        self._profiles: Dict[str, UserProfile] = {}
        self._monitors: Dict[str, ProfileMonitor] = {}
        self._buffers: Dict[str, MessageBuffer] = {}
        
        # 配置（从插件配置获取）
        self._min_messages_for_update = self._get_config_int("profile_min_messages", 10)
        self._max_buffer_age = self._get_config_int("profile_max_buffer_age", 300)
        
        # 标记是否已加载
        self._loaded = False

    def _get_config_int(self, key: str, default: int) -> int:
        """从插件配置获取整数值"""
        try:
            config = self.context.get_config()
            if config:
                return int(config.get(key, default) or default)
        except Exception:
            pass
        return default

    async def load(self):
        """从 KV 存储加载数据"""
        if self._loaded:
            return
        
        try:
            # 加载画像数据
            profiles_data = await self.plugin.get_kv_data(self.KV_PROFILES, {})
            for user_id, data in profiles_data.items():
                self._profiles[user_id] = UserProfile.from_dict(data)
            
            # 加载监控配置
            monitors_data = await self.plugin.get_kv_data(self.KV_MONITORS, {})
            for user_id, data in monitors_data.items():
                self._monitors[user_id] = ProfileMonitor.from_dict(data)
            
            # 加载消息缓冲区
            buffers_data = await self.plugin.get_kv_data(self.KV_BUFFERS, {})
            for user_id, data in buffers_data.items():
                self._buffers[user_id] = MessageBuffer.from_dict(data)
            
            self._loaded = True
            logger.info(f"[lzpersona] 画像服务已加载: {len(self._profiles)} 个画像, {len(self._monitors)} 个监控")
        except Exception as e:
            logger.error(f"[lzpersona] 加载画像数据失败: {e}")

    async def save_profiles(self):
        """保存画像数据"""
        try:
            data = {uid: p.to_dict() for uid, p in self._profiles.items()}
            await self.plugin.put_kv_data(self.KV_PROFILES, data)
        except Exception as e:
            logger.error(f"[lzpersona] 保存画像数据失败: {e}")

    async def save_monitors(self):
        """保存监控配置"""
        try:
            data = {uid: m.to_dict() for uid, m in self._monitors.items()}
            await self.plugin.put_kv_data(self.KV_MONITORS, data)
        except Exception as e:
            logger.error(f"[lzpersona] 保存监控配置失败: {e}")

    async def save_buffers(self):
        """保存消息缓冲区"""
        try:
            data = {uid: b.to_dict() for uid, b in self._buffers.items()}
            await self.plugin.put_kv_data(self.KV_BUFFERS, data)
        except Exception as e:
            logger.error(f"[lzpersona] 保存缓冲区失败: {e}")

    # ==================== 监控管理 ====================

    async def add_monitor(
        self, 
        user_id: str, 
        mode: ProfileMode,
        group_ids: List[str] = None,
        created_by: str = ""
    ) -> ProfileMonitor:
        """添加用户画像监控"""
        await self.load()
        
        monitor = ProfileMonitor(
            user_id=user_id,
            mode=mode,
            group_ids=group_ids or [],
            enabled=True,
            created_at=time.time(),
            created_by=created_by,
        )
        self._monitors[user_id] = monitor
        await self.save_monitors()
        
        # 初始化空画像
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(
                user_id=user_id,
                created_at=time.time(),
            )
            await self.save_profiles()
        
        # 初始化缓冲区
        if user_id not in self._buffers:
            self._buffers[user_id] = MessageBuffer(user_id=user_id)
        
        logger.info(f"[lzpersona] 添加画像监控: {user_id}, 模式: {mode.value}")
        return monitor

    async def remove_monitor(self, user_id: str) -> bool:
        """移除画像监控"""
        await self.load()
        
        if user_id in self._monitors:
            del self._monitors[user_id]
            await self.save_monitors()
            logger.info(f"[lzpersona] 移除画像监控: {user_id}")
            return True
        return False

    async def get_monitor(self, user_id: str) -> Optional[ProfileMonitor]:
        """获取监控配置"""
        await self.load()
        return self._monitors.get(user_id)

    async def get_all_monitors(self) -> List[ProfileMonitor]:
        """获取所有监控配置"""
        await self.load()
        return list(self._monitors.values())

    async def is_monitored(self, user_id: str, group_id: str = "") -> bool:
        """检查用户是否在监控列表中"""
        await self.load()
        
        monitor = self._monitors.get(user_id)
        if not monitor or not monitor.enabled:
            return False
        
        if monitor.mode == ProfileMode.GLOBAL:
            return True
        
        # 群聊模式：检查是否在指定群列表中
        if monitor.mode == ProfileMode.GROUP:
            return group_id in monitor.group_ids
        
        return False

    # ==================== 消息处理 ====================

    async def process_message(
        self, 
        user_id: str, 
        content: str, 
        group_id: str = "",
        nickname: str = "",
        event: "AstrMessageEvent" = None
    ) -> bool:
        """处理用户消息
        
        Returns:
            是否触发了画像更新
        """
        await self.load()
        
        # 检查是否在监控列表中
        if not await self.is_monitored(user_id, group_id):
            return False
        
        # 添加到缓冲区
        if user_id not in self._buffers:
            self._buffers[user_id] = MessageBuffer(user_id=user_id)
        
        buffer = self._buffers[user_id]
        buffer.add_message(content, group_id, nickname)
        
        # 更新昵称
        if nickname and user_id in self._profiles:
            self._profiles[user_id].nickname = nickname
        
        # 检查是否需要刷新
        if buffer.should_flush(self._min_messages_for_update, self._max_buffer_age):
            await self._update_profile(user_id, event)
            return True
        
        # 定期保存缓冲区
        if len(buffer.messages) % 5 == 0:
            await self.save_buffers()
        
        return False

    async def _update_profile(self, user_id: str, event: "AstrMessageEvent" = None):
        """更新用户画像"""
        buffer = self._buffers.get(user_id)
        if not buffer or not buffer.messages:
            return
        
        messages = buffer.flush()
        await self.save_buffers()
        
        profile = self._profiles.get(user_id)
        if not profile:
            profile = UserProfile(user_id=user_id, created_at=time.time())
            self._profiles[user_id] = profile
        
        # 格式化消息
        messages_text = self._format_messages(messages)
        
        # 调用 LLM 更新画像
        try:
            if profile.profile_text:
                # 增量更新
                result = await self._call_llm_update(profile, messages_text, event)
            else:
                # 初始化
                nickname = messages[0].get("nickname", "") if messages else ""
                result = await self._call_llm_init(user_id, nickname, messages_text, event)
            
            if result:
                # 更新画像
                profile.profile_text = result.get("profile_text", profile.profile_text)
                profile.traits = result.get("traits", profile.traits)
                profile.interests = result.get("interests", profile.interests)
                profile.speaking_style = result.get("speaking_style", profile.speaking_style)
                profile.emotional_tendency = result.get("emotional_tendency", profile.emotional_tendency)
                profile.message_count += len(messages)
                profile.last_updated = time.time()
                
                await self.save_profiles()
                logger.info(f"[lzpersona] 画像已更新: {user_id}, 累计消息: {profile.message_count}")
        except Exception as e:
            logger.error(f"[lzpersona] 更新画像失败: {e}")
            # 将消息放回缓冲区并保存（使用 extend 保持顺序，避免重复）
            # 注意：只有在缓冲区为空时才放回，防止多次失败导致重复
            if not buffer.messages:
                buffer.messages.extend(messages)
            await self.save_buffers()

    def _format_messages(self, messages: List[Dict]) -> str:
        """格式化消息列表为文本"""
        lines = []
        for msg in messages:
            timestamp = datetime.fromtimestamp(msg.get("timestamp", 0)).strftime("%H:%M")
            content = msg.get("content", "")
            group_id = msg.get("group_id", "")
            location = f"[群{group_id}]" if group_id else "[私聊]"
            lines.append(f"{location} {timestamp}: {content}")
        return "\n".join(lines)

    async def _call_llm_update(
        self, 
        profile: UserProfile, 
        messages_text: str,
        event: "AstrMessageEvent" = None
    ) -> Optional[Dict]:
        """调用 LLM 更新画像"""
        current_profile = f"""
画像描述: {profile.profile_text}
性格特征: {', '.join(profile.traits)}
兴趣爱好: {', '.join(profile.interests)}
说话风格: {profile.speaking_style}
情感倾向: {profile.emotional_tendency}
"""
        prompt = DEFAULT_PROFILE_UPDATE_TEMPLATE.format(
            current_profile=current_profile,
            new_messages=messages_text,
        )
        
        return await self._call_llm_and_parse(prompt, event)

    async def _call_llm_init(
        self,
        user_id: str,
        nickname: str,
        messages_text: str,
        event: "AstrMessageEvent" = None
    ) -> Optional[Dict]:
        """调用 LLM 初始化画像"""
        prompt = DEFAULT_PROFILE_INIT_TEMPLATE.format(
            user_id=user_id,
            nickname=nickname or "未知",
            messages=messages_text,
        )
        
        return await self._call_llm_and_parse(prompt, event)

    async def _call_llm_and_parse(
        self, 
        prompt: str, 
        event: "AstrMessageEvent" = None
    ) -> Optional[Dict]:
        """调用 LLM 并解析结果"""
        # 使用插件已有的 LLMService 实例，避免重复创建
        result = await self.plugin.llm_service.call_architect(prompt, event)
        
        if not result:
            return None
        
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[^{}]*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(result)
        except json.JSONDecodeError as e:
            logger.warning(f"[lzpersona] 画像解析失败: {e}")
            return None

    # ==================== 画像查询 ====================

    async def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """获取用户画像"""
        await self.load()
        return self._profiles.get(user_id)

    async def get_all_profiles(self) -> List[UserProfile]:
        """获取所有用户画像"""
        await self.load()
        return list(self._profiles.values())

    async def delete_profile(self, user_id: str) -> bool:
        """删除用户画像"""
        await self.load()
        
        deleted = False
        if user_id in self._profiles:
            del self._profiles[user_id]
            await self.save_profiles()
            deleted = True
        
        if user_id in self._monitors:
            del self._monitors[user_id]
            await self.save_monitors()
        
        if user_id in self._buffers:
            del self._buffers[user_id]
            await self.save_buffers()
        
        return deleted

    async def force_update(self, user_id: str, event: "AstrMessageEvent" = None) -> bool:
        """强制更新画像（刷新当前缓冲区）"""
        await self.load()
        
        buffer = self._buffers.get(user_id)
        if not buffer or not buffer.messages:
            return False
        
        await self._update_profile(user_id, event)
        return True

    async def get_buffer_status(self, user_id: str) -> Dict:
        """获取缓冲区状态"""
        await self.load()
        
        buffer = self._buffers.get(user_id)
        if not buffer:
            return {"message_count": 0, "last_flush": None}
        
        return {
            "message_count": len(buffer.messages),
            "last_flush": datetime.fromtimestamp(buffer.last_flush).strftime("%Y-%m-%d %H:%M:%S") if buffer.last_flush else None,
        }
