"""用户画像服务"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from astrbot.api import logger

from .llm import _extract_json_object
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
    1. 管理画像监��配置
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

        # 标记是否已加载
        self._loaded = False
        # 加载锁，防止并发加载
        self._load_lock = asyncio.Lock()

        # 配置（延迟获取，避免初始化时 config_service 还未就绪）
        self._min_messages_for_update: Optional[int] = None
        self._max_buffer_age: Optional[int] = None
        self._context_size: Optional[int] = None
        self._include_bot_replies: Optional[bool] = None

    def _get_config_int(self, key: str, default: int) -> int:
        """从插件配置获取整数值 - 使用 plugin.config_service"""
        try:
            if hasattr(self.plugin, 'config_service'):
                return self.plugin.config_service.get_int(key, default)
            # 回退到 context.get_config()
            config = self.context.get_config()
            if config:
                return int(config.get(key, default) or default)
        except Exception:
            pass
        return default

    def _get_config_bool(self, key: str, default: bool) -> bool:
        """从插件配置获取布尔值 - 使用 plugin.config_service"""
        try:
            if hasattr(self.plugin, 'config_service'):
                return self.plugin.config_service.get_bool(key, default)
            # 回退到 context.get_config()
            config = self.context.get_config()
            if config:
                val = config.get(key, default)
                if isinstance(val, bool):
                    return val
                if isinstance(val, str):
                    return val.lower() in ("true", "1", "yes")
        except Exception:
            pass
        return default

    @property
    def min_messages_for_update(self) -> int:
        """最小消息数阈值"""
        if self._min_messages_for_update is None:
            self._min_messages_for_update = self._get_config_int("profile_min_messages", 10)
        return self._min_messages_for_update

    @property
    def max_buffer_age(self) -> int:
        """缓冲区最大时间（秒）"""
        if self._max_buffer_age is None:
            self._max_buffer_age = self._get_config_int("profile_max_buffer_age", 300)
        return self._max_buffer_age

    @property
    def context_size(self) -> int:
        """上下文消息条数"""
        if self._context_size is None:
            self._context_size = self._get_config_int("profile_context_size", 20)
        return self._context_size

    @property
    def include_bot_replies(self) -> bool:
        """是否包含机器人回复"""
        if self._include_bot_replies is None:
            self._include_bot_replies = self._get_config_bool("profile_include_bot", True)
        return self._include_bot_replies

    async def load(self):
        """从 KV 存储加载数据"""
        # 使用锁防止并发加载
        async with self._load_lock:
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
        
        # 检查是否需要刷新（使用属性获取配置值）
        if buffer.should_flush(self.min_messages_for_update, self.max_buffer_age):
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
        
        # 获取对话上下文（包含其他用户的消息和机器人回复）
        context_messages = await self._get_conversation_context(user_id, event)
        
        # 格式化目标用户消息
        messages_text = self._format_messages(messages, user_id)
        
        # 格式化对话上下文
        context_text = self._format_context(context_messages, user_id) if context_messages else ""
        
        # 调用 LLM 更新画像
        try:
            if profile.profile_text:
                # 增量更新
                result = await self._call_llm_update(profile, messages_text, context_text, event)
            else:
                # 初始化
                nickname = messages[0].get("nickname", "") if messages else ""
                result = await self._call_llm_init(user_id, nickname, messages_text, context_text, event)
            
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

    async def _get_conversation_context(
        self, 
        user_id: str, 
        event: "AstrMessageEvent" = None
    ) -> List[Dict]:
        """获取对话上下文
        
        从 AstrBot 的 message_history_manager 获取最近的消息历史，
        包括其他用户的消息和机器人回复，用于提供更丰富的上下文给 LLM。
        
        Args:
            user_id: 目标用户 ID
            event: 当前消息事件，用于获取 platform_id 和 session_id
            
        Returns:
            消息列表，每条消息包含 sender_id, sender_name, content, is_target, is_bot
        """
        if not event:
            return []
        
        try:
            # 获取平台 ID 和会话 ID
            platform_id = event.get_platform_id() or ""
            
            # 从 UMO 解析会话 ID（群聊时是 group_id，私聊时是 user_id）
            umo = event.unified_msg_origin or ""
            session_id = ""
            if ":group:" in umo:
                parts = umo.split(":")
                if len(parts) >= 3:
                    session_id = parts[2]
            else:
                session_id = str(event.get_sender_id() or "")
            
            if not platform_id or not session_id:
                logger.debug(f"[lzpersona] 无法获取上下文: platform_id={platform_id}, session_id={session_id}")
                return []
            
            # 通过 context.message_history_manager 获取历史消息
            history_mgr = self.context.message_history_manager
            history_records = await history_mgr.get(
                platform_id=platform_id,
                user_id=session_id,  # 这里的 user_id 实际上是会话 ID
                page=1,
                page_size=self.context_size,
            )
            
            # 转换为标准格式
            context_messages = []
            for record in history_records:
                sender_id = record.sender_id or ""
                sender_name = record.sender_name or ""
                content = self._extract_content_from_record(record.content)
                
                # 判断是否是目标用户
                is_target = sender_id == user_id
                
                # 判断是否是机器人回复
                # AstrBot 存储机器人消息时 sender_id = "bot"
                is_bot = not sender_id or sender_id == "bot" or sender_id.startswith("bot_")
                
                # 如果配置不包含机器人回复，跳过（使用属性获取配置值）
                if is_bot and not self.include_bot_replies:
                    continue
                
                context_messages.append({
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "content": content,
                    "is_target": is_target,
                    "is_bot": is_bot,
                    "timestamp": record.created_at.timestamp() if record.created_at else 0,
                })
            
            logger.debug(f"[lzpersona] 获取到 {len(context_messages)} 条上下文消息")
            return context_messages
            
        except Exception as e:
            logger.warning(f"[lzpersona] 获取对话上下文失败: {e}")
            return []

    def _extract_content_from_record(self, content: Any) -> str:
        """从消息记录中提取文本内容
        
        PlatformMessageHistory.content 是一个 dict/list，需要解析
        """
        if not content:
            return ""
        
        # 如果是字符串，直接返回
        if isinstance(content, str):
            return content
        
        # 如果是列表（消息链），提取所有文本
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    # 常见格式: {"type": "text", "text": "..."} 或 {"type": "Plain", "text": "..."}
                    if item.get("type") in ("text", "Plain", "plain"):
                        texts.append(item.get("text", "") or item.get("data", ""))
                    elif "text" in item:
                        texts.append(item["text"])
                elif isinstance(item, str):
                    texts.append(item)
            return " ".join(texts)
        
        # 如果是字典
        if isinstance(content, dict):
            return content.get("text", "") or content.get("content", "") or str(content)
        
        return str(content)

    def _format_messages(self, messages: List[Dict], target_user_id: str = "") -> str:
        """格式化目标用户消息列表为文本"""
        lines = []
        for msg in messages:
            timestamp = datetime.fromtimestamp(msg.get("timestamp", 0)).strftime("%H:%M")
            content = msg.get("content", "")
            group_id = msg.get("group_id", "")
            nickname = msg.get("nickname", "")
            location = f"[群{group_id}]" if group_id else "[私聊]"
            name_tag = f"({nickname})" if nickname else ""
            lines.append(f"{location} {timestamp} {name_tag}: {content}")
        return "\n".join(lines)

    def _format_context(self, context_messages: List[Dict], target_user_id: str) -> str:
        """格式化对话上下文为文本
        
        包含其他用户的消息和机器人回复，用于 LLM 理解对话场景
        """
        if not context_messages:
            return ""
        
        lines = []
        for msg in context_messages:
            timestamp = datetime.fromtimestamp(msg.get("timestamp", 0)).strftime("%H:%M")
            content = msg.get("content", "")
            sender_name = msg.get("sender_name", "")
            is_target = msg.get("is_target", False)
            is_bot = msg.get("is_bot", False)
            
            # 标记角色
            if is_bot:
                role = "[机器人]"
            elif is_target:
                role = f"[目标用户:{sender_name}]" if sender_name else "[目标用户]"
            else:
                role = f"[{sender_name}]" if sender_name else "[其他用户]"
            
            lines.append(f"{timestamp} {role}: {content}")
        
        return "\n".join(lines)

    async def _call_llm_update(
        self, 
        profile: UserProfile, 
        messages_text: str,
        context_text: str = "",
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
        # 构建带上下文的消息部分
        if context_text:
            messages_with_context = f"""### 对话上下文（包含其他参与者的消息，帮助理解互动模式）
```
{context_text}
```

### 目标用户的新消息
{messages_text}"""
        else:
            messages_with_context = messages_text
        
        prompt = DEFAULT_PROFILE_UPDATE_TEMPLATE.format(
            current_profile=current_profile,
            new_messages=messages_with_context,
        )
        
        return await self._call_llm_and_parse(prompt, event)

    async def _call_llm_init(
        self,
        user_id: str,
        nickname: str,
        messages_text: str,
        context_text: str = "",
        event: "AstrMessageEvent" = None
    ) -> Optional[Dict]:
        """调用 LLM 初始化画像"""
        # 构建带上下文的消息部分
        if context_text:
            messages_with_context = f"""### 对话上下文（包含其他参与者的消息，帮助理解互动模式和社交风格）
```
{context_text}
```

### 目标用户的消息
{messages_text}"""
        else:
            messages_with_context = messages_text
        
        prompt = DEFAULT_PROFILE_INIT_TEMPLATE.format(
            user_id=user_id,
            nickname=nickname or "未知",
            messages=messages_with_context,
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
        
        # 使用 llm.py 中支持嵌套的 JSON 提取函数
        parsed = _extract_json_object(result)
        if parsed is None:
            logger.warning(f"[lzpersona] 画像解析失败, 原文: {result[:200]}...")
        return parsed

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
