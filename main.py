"""
快捷人格生成器 - AI 驱动的人格管理工具

通过简单的命令快速生成、优化和管理 AI 人格，无需手动编写复杂的提示词。
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.util import session_waiter, SessionController
from astrbot.api.message_components import Plain, Image
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
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
    # 画像相关
    ProfileMode,
    PROFILE_CARD_TEMPLATE,
)
from .services import LLMService, PersonaService, ProfileService
from .utils import shorten_prompt, generate_persona_id, get_session_id

# 经过优化的人格卡片 HTML 模板
PERSONA_CARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        html, body {
            width: 100%;
            min-height: 100vh;
            /* 修正点 1: 使用 flex 布局让子元素居中 */
            display: flex;
            justify-content: center; /* 水平居中 */
            align-items: flex-start; /* 顶部对齐，防止长内容被截断 */
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
            padding: 40px 20px;
        }

        /* 修正点 2: 卡片容器 */
        .card {
            width: 100%;
            max-width: 700px; /* 宽度可以根据需要微调 */
            background: rgba(255, 255, 255, 0.98);
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }

        /* 头部样式优化 */
        .header {
            display: flex;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1.5px solid #eee;
        }
        .icon { font-size: 32px; margin-right: 15px; }
        .title-group { flex-grow: 1; }
        .title { font-size: 22px; font-weight: bold; color: #1a1a1a; }
        .subtitle { font-size: 14px; color: #666; margin-top: 4px; }

        /* 元数据区（ID、字数等） */
        .meta-container {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin-bottom: 25px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        .meta-item { font-size: 14px; color: #444; }
        .meta-label { color: #888; margin-right: 5px; }

        /* 内容区：支持换行和保留空格 */
        .content {
            font-size: 15px;
            line-height: 1.8;
            color: #333;
            white-space: pre-wrap; /* 关键：保留换行 */
            word-wrap: break-word;
            text-align: justify; /* 两端对齐，更美观 */
        }

        /* 底部操作提示 */
        .footer {
            margin-top: 25px;
            padding-top: 15px;
            border-top: 1px solid #eee;
            font-size: 13px;
            color: #999;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <span class="icon">{{ icon }}</span>
            <div class="title-group">
                <div class="title">{{ title }}</div>
                <div class="subtitle">{{ subtitle }}</div>
            </div>
        </div>
        
        {% if meta_info %}
        <div class="meta-container">
            {% for key, value in meta_info.items() %}
            <div class="meta-item">
                <span class="meta-label">{{ key }}:</span>
                <span class="meta-value">{{ value }}</span>
            </div>
            {% endfor %}
        </div>
        {% endif %}
        
        <div class="content">{{ content }}</div>
        
        {% if footer %}
        <div class="footer">{{ footer }}</div>
        {% endif %}
    </div>
</body>
</html>
"""


@register(
    "astrbot_plugin_lzpersona", "idiotsj", "LZ快捷人格生成器 - AI 驱动的人格管理工具", "1.0.4", ""
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
        
        # 初始化画像服务
        self.profile_service = ProfileService(context, self)

        logger.info(f"[lzpersona] 插件初始化完成，数据目录: {self.data_dir}")

    async def terminate(self):
        """插件卸载时的清理方法"""
        try:
            # 保存状态
            await self.state.save_async()
            
            # 保存画像服务的缓冲区数据
            if hasattr(self, 'profile_service') and self.profile_service._loaded:
                await self.profile_service.save_buffers()
                await self.profile_service.save_profiles()
                await self.profile_service.save_monitors()
            
            logger.info("[lzpersona] 插件资源已清理")
        except Exception as e:
            logger.error(f"[lzpersona] 清理资源时出错: {e}")

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

    async def _render_persona_card(
        self, event: AstrMessageEvent, 
        icon: str, title: str, subtitle: str,
        content: str, meta_info: dict = None, footer: str = ""
    ):
        """渲染人格卡片为图片"""
        try:
            image_url = await self.html_render(
                PERSONA_CARD_TEMPLATE,
                {
                    "icon": icon,
                    "title": title,
                    "subtitle": subtitle,
                    "content": content,
                    "meta_info": meta_info or {},
                    "footer": footer,
                },
                options={
                    "full_page": True,  # 截取整页，让 body 的 inline-block 自适应宽度
                }
            )
            yield event.image_result(image_url)
        except Exception as e:
            logger.warning(f"[lzpersona] 人格卡片渲染失败，使用纯文本输出: {e}")
            # 降级为纯文本
            lines = [f"{icon} {title}", subtitle, "-" * 30, content]
            if meta_info:
                lines.append("-" * 30)
                for k, v in meta_info.items():
                    lines.append(f"{k}: {v}")
            if footer:
                lines.append("-" * 30)
                lines.append(footer)
            yield event.plain_result("\n".join(lines))

    # ==================== 命令组 ====================

    @filter.command_group("快捷人格", alias={"qp", "quickpersona"})
    def qp(self):
        """快捷人格生成器命令组"""
        pass

    @qp.command("使用帮助", alias={"help", "?"})
    async def cmd_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """快捷人格生成器 - 命令列表

🤖 智能入口（推荐）
/人格 <自然语言> - 智能识别意图，自动执行

📝 生成与优化
/快捷人格 生成人格 <描述> - 根据描述生成人格
/快捷人格 优化人格 <反馈> - 优化人格（可直接优化未生成的人格）
/快捷人格 压缩人格 [强度] - 压缩提示词(轻度/中度/极限)

📋 管理
/快捷人格 查看状态 - 查看当前状态
/快捷人格 确认生成 - 确认并保存待确认的人格
/快捷人格 取消操作 - 取消待确认的人格
/快捷人格 人格列表 - 列出所有人格
/快捷人格 选择人格 <人格ID> - 选择人格
/快捷人格 应用人格 [人格ID] - 应用人格到当前对话
/快捷人格 删除人格 <人格ID> - 删除人格

💡 使用流程示例：
  /人格 生成一个傲娇猫娘  → 生成人格
  /人格 让她更傲娇一点    → 直接优化未生成的人格
  /人格 确认              → 满意后保存人格
  /人格 应用              → 让AI使用此人格"""
        yield event.plain_result(help_text)

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
                    "请指定要激活的人格，例如：/人格 切换到猫娘\n"
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

    def _get_enable_guided_generation(self) -> bool:
        """是否启用引导式生成"""
        return bool(self._get_cfg("enable_guided_generation", True))

    @qp.command("生成人格", alias={"gen"})
    async def cmd_gen(self, event: AstrMessageEvent, description: GreedyStr = ""):
        """根据描述生成人格（支持引导式生成）"""
        # 直接从原始消息中提取描述，避免命令解析器截断问题
        raw_message = event.get_message_str().strip()
        
        # 定义可能的命令前缀组合
        prefixes = [
            "/快捷人格 生成人格 ", "快捷人格 生成人格 ",
            "/qp 生成人格 ", "qp 生成人格 ",
            "/quickpersona 生成人格 ", "quickpersona 生成人格 ",
            "/快捷人格 gen ", "快捷人格 gen ",
            "/qp gen ", "qp gen ",
            "/quickpersona gen ", "quickpersona gen ",
        ]
        
        # 尝试从原始消息中提取描述部分
        extracted = False
        for prefix in prefixes:
            # 使用不区分大小写的比较（仅对英文部分）
            if raw_message.startswith(prefix) or raw_message.lower().startswith(prefix.lower()):
                description = raw_message[len(prefix):].strip()
                extracted = True
                break
        
        if not extracted:
            # 如果没有匹配到前缀，使用解析器的结果
            description = str(description).strip()

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
        if self._get_enable_guided_generation():
            async for r in self._guided_generation(event, description, session):
                yield r
        else:
            async for r in self._quick_generation(event, description, session):
                yield r

    async def _guided_generation(
        self, event: AstrMessageEvent, description: str, session
    ):
        """引导式生成流程"""
        yield event.plain_result(
            f"🎭 正在分析你的人格描述...\n描述: {description}"
        )

        # 分析缺失字段
        analysis = await self.llm_service.analyze_missing_fields(description, event)
        missing_fields = analysis.get("missing", [])
        provided_fields = analysis.get("provided", [])

        if not missing_fields:
            # 没有缺失字段，直接生成
            yield event.plain_result("✅ 描述完整，正在生成人格...")
            async for r in self._quick_generation(event, description, session):
                yield r
            return

        # 构建缺失字段提示信息
        lines = ["📋 检测到以下设定缺失，请选择要补充的内容：", ""]
        field_map = {}  # 用于存储序号到字段的映射
        for i, field in enumerate(missing_fields, 1):
            label = field.get("label", field.get("field", "未知"))
            hint = field.get("hint", "")
            lines.append(f"{i}️⃣ {label}（{hint}）")
            field_map[str(i)] = field

        lines.extend([
            "",
            "💡 回复对应数字（如\"2,3\"）并补充内容",
            "💡 回复\"跳过\"让 AI 自动生成所有缺失部分",
        ])

        yield event.plain_result("\n".join(lines))

        # 保存状态，等待用户回复
        session.state = SessionState.WAITING_MISSING_INPUT
        session.pending_persona = PendingPersona(
            persona_id="",  # 稍后生成
            system_prompt="",  # 稍后生成
            created_at=time.time(),
            mode="guided",
            original_description=description,
            missing_fields=missing_fields,
            provided_fields=provided_fields,
        )

        # 使用 session_waiter 等待用户回复
        @session_waiter(timeout=120, record_history_chains=False)
        async def wait_for_missing_input(
            controller: SessionController,
            w_event: AstrMessageEvent,
        ):
            # 过滤掉空消息（如"正在输入"通知）
            message_text = w_event.message_str.strip() if w_event.message_str else ""
            if not message_text:
                # 保持会话，继续等待有效消息
                controller.keep(timeout=120)
                return
            
            # 收到有效消息，设置 future 结果
            if not controller.future.done():
                controller.future.set_result(w_event)

        try:
            user_reply_event = await wait_for_missing_input(event)
            user_reply = user_reply_event.message_str.strip()
        except TimeoutError:
            session.state = SessionState.IDLE
            session.pending_persona = None
            yield event.plain_result("⏰ 等待超时，已取消生成")
            return

        # 处理用户回复
        async for r in self._process_missing_input(
            event, user_reply, description, missing_fields, provided_fields, session
        ):
            yield r

    async def _process_missing_input(
        self, event: AstrMessageEvent, user_reply: str, 
        description: str, missing_fields: list, provided_fields: list, session
    ):
        """处理用户对缺失字段的回复"""
        user_reply = user_reply.strip()

        if user_reply.lower() in ["跳过", "skip", "s"]:
            # 用户选择跳过，让 AI 自动生成所有缺失部分
            yield event.plain_result("⏭️ 已跳过，AI 将自动生成缺失部分...")
            auto_generate_fields = [f.get("label", f.get("field")) for f in missing_fields]
            async for r in self._generate_with_supplements(
                event, description, "", auto_generate_fields, session
            ):
                yield r
            return

        # 解析用户选择的字段编号和补充内容
        # 期望格式: "2,3 主人，喜欢在句尾加nya" 或 "1、2 ..." 或 "1，2 ..."
        import re
        
        # 支持中英文逗号、顿号、空格作为分隔符
        # 匹配 "数字[分隔符]数字[分隔符]... 内容" 的格式
        match = re.match(r'^([\d,，、\s]+)\s*(.*)$', user_reply)
        
        if not match:
            # 如果格式不正确，将整个回复作为补充内容，让 AI 生成所有缺失字段
            yield event.plain_result("📝 已收到补充信息，正在生成人格...")
            auto_generate_fields = [f.get("label", f.get("field")) for f in missing_fields]
            async for r in self._generate_with_supplements(
                event, description, user_reply, auto_generate_fields, session
            ):
                yield r
            return

        selected_nums_str = match.group(1)
        supplements = match.group(2).strip()

        # 解析选中的字段编号
        selected_nums = set()
        for num in re.findall(r'\d+', selected_nums_str):
            selected_nums.add(num)

        # 确定哪些字段由用户补充，哪些由 AI 生成
        user_selected_fields = []
        auto_generate_fields = []

        for i, field in enumerate(missing_fields, 1):
            label = field.get("label", field.get("field"))
            if str(i) in selected_nums:
                user_selected_fields.append(label)
            else:
                auto_generate_fields.append(label)

        # 构建补充信息说明
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
        self, event: AstrMessageEvent, description: str, 
        supplements: str, auto_generate_fields: list, session
    ):
        """根据补充信息生成人格"""
        result = await self.llm_service.generate_with_supplements(
            description, supplements, auto_generate_fields, event
        )

        if not result:
            session.state = SessionState.IDLE
            session.pending_persona = None
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
                mode="guided",
            )

            # 使用图片卡片展示
            async for r in self._render_persona_card(
                event,
                icon="🎭",
                title=f"人格生成完成",
                subtitle=f"模式: 引导式生成 | 待确认",
                content=result,
                meta_info={"人格ID": persona_id, "字符数": str(len(result))},
                footer="发送 /快捷人格 确认生成 或 /快捷人格 取消操作"
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
                async for r in self._render_persona_card(
                    event,
                    icon="✅",
                    title=f"人格已创建并应用",
                    subtitle=f"模式: 引导式生成",
                    content=result,
                    meta_info={"人格ID": persona_id, "字符数": str(len(result))},
                ):
                    yield r
            else:
                session.state = SessionState.IDLE
                session.pending_persona = None
                yield event.plain_result("❌ 应用人格失败，请查看日志")

    async def _quick_generation(self, event: AstrMessageEvent, description: str, session):
        """快速生成流程（原有逻辑）"""
        yield event.plain_result(
            f"🔄 正在根据描述生成人格...\n描述: {description}"
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

            # 使用图片卡片展示
            async for r in self._render_persona_card(
                event,
                icon="🎭",
                title=f"人格生成完成",
                subtitle=f"模式: 快速生成 | 待确认",
                content=result,
                meta_info={"人格ID": persona_id, "字符数": str(len(result))},
                footer="发送 /快捷人格 确认生成 或 /快捷人格 取消操作"
            ):
                yield r
        else:
            # 获取用户名用于占位符替换
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(
                persona_id, result, backup=False, user_name=user_name
            )
            if success:
                session.current_persona_id = persona_id
                async for r in self._render_persona_card(
                    event,
                    icon="✅",
                    title=f"人格已创建并应用",
                    subtitle=f"模式: 快速生成",
                    content=result,
                    meta_info={"人格ID": persona_id, "字符数": str(len(result))},
                ):
                    yield r
            else:
                yield event.plain_result("❌ 应用人格失败，请查看日志")

    @qp.command("确认生成", alias={"confirm", "yes"})
    async def cmd_apply(self, event: AstrMessageEvent):
        """确认并保存待确认的人格"""
        try:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)

            if session.state != SessionState.WAITING_CONFIRM or not session.pending_persona:
                yield event.plain_result("没有待确认的人格")
                return

            pending = session.pending_persona
            # 获取用户名用于占位符替换
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(
                pending.persona_id, pending.system_prompt, backup=True, user_name=user_name
            )

            if success:
                session.current_persona_id = pending.persona_id
                session.state = SessionState.IDLE
                session.pending_persona = None

                yield event.plain_result(
                    f"✅ 人格已保存！\n"
                    f"📌 人格ID: {pending.persona_id}\n"
                    f"💡 使用 /快捷人格 应用人格 让 AI 使用此人格"
                )
            else:
                yield event.plain_result("❌ 保存失败，请查看日志")
        except Exception as e:
            logger.error(f"[lzpersona] 保存人格失败: {e}")
            yield event.plain_result(f"❌ 保存人格失败: {e}")
        finally:
            event.stop_event()

    @qp.command("取消操作", alias={"cancel", "no"})
    async def cmd_cancel(self, event: AstrMessageEvent):
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

    @qp.command("查看状态", alias={"status"})
    async def cmd_status(self, event: AstrMessageEvent):
        """查看当前状态"""
        try:
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
        finally:
            event.stop_event()

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
            yield event.plain_result(f"❌ 获取列表失败: {e}")
        finally:
            event.stop_event()

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
        try:
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
            yield event.plain_result(f"❌ 回滚失败: {e}")
        finally:
            event.stop_event()

    @qp.command("优化人格", alias={"refine"})
    async def cmd_refine(self, event: AstrMessageEvent, feedback: GreedyStr = ""):
        """根据反馈优化当前人格（支持对待确认人格直接优化）"""
        feedback = str(feedback).strip()

        if not feedback:
            yield event.plain_result(
                "请提供优化反馈，例如：/快捷人格 优化人格 说话再可爱一点"
            )
            return

        session_id = get_session_id(event)
        session = self.state.get_session(session_id)

        # 检查是否有待确认的人格，如果有则直接对其进行优化
        if session.state == SessionState.WAITING_CONFIRM and session.pending_persona:
            pending = session.pending_persona
            current_prompt = pending.system_prompt
            persona_id = pending.persona_id
            is_pending = True

            yield event.plain_result(
                f"🔄 正在优化待确认的人格...\n"
                f"📌 人格ID: {persona_id}\n"
                f"反馈: {feedback}"
            )
        else:
            # 否则对已选择的人格进行优化
            persona_id = session.current_persona_id
            is_pending = False

            if not persona_id:
                yield event.plain_result(
                    "请先使用 /快捷人格 选择人格 <人格ID> 选择一个人格\n"
                    "或者先生成一个人格后直接反馈优化"
                )
                return

            try:
                persona = await self.persona_service.get_persona(persona_id)
                current_prompt = persona.system_prompt
            except ValueError:
                yield event.plain_result(f"❌ 未找到人格: {persona_id}")
                return

            yield event.plain_result(
                f"🔄 正在根据反馈优化人格...\n反馈: {feedback}"
            )

        template = self._get_template(
            "persona_refine_template", DEFAULT_REFINE_TEMPLATE
        )
        prompt = template.format(
            current_prompt=current_prompt, feedback=feedback
        )
        result = await self.llm_service.call_architect(prompt, event)

        if not result:
            yield event.plain_result("❌ 优化失败，请稍后重试")
            return

        if self._get_confirm_before_apply():
            # 更新待确认人格（无论之前是否有待确认状态）
            session.state = SessionState.WAITING_CONFIRM
            session.pending_persona = PendingPersona(
                persona_id=persona_id,
                system_prompt=result,
                created_at=time.time(),
                mode="refine",
                original_prompt=current_prompt,
            )

            status_hint = "（已更新待确认人格）" if is_pending else ""
            async for r in self._render_persona_card(
                event,
                icon="✨",
                title=f"人格优化完成{status_hint}",
                subtitle=f"模式: 优化 | 待确认",
                content=result,
                meta_info={"人格ID": persona_id, "字符数": str(len(result))},
                footer="可继续发送反馈优化，或 /快捷人格 确认生成"
            ):
                yield r
        else:
            # 获取用户名用于占位符替换
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(
                persona_id, result, backup=True, user_name=user_name
            )
            if success:
                async for r in self._render_persona_card(
                    event,
                    icon="✅",
                    title=f"人格已优化",
                    subtitle=f"模式: 优化",
                    content=result,
                    meta_info={"人格ID": persona_id, "字符数": str(len(result))},
                ):
                    yield r
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

            async for r in self._render_persona_card(
                event,
                icon="📦",
                title=f"压缩完成",
                subtitle=f"强度: {intensity} | 待确认",
                content=result,
                meta_info={
                    "人格ID": persona_id,
                    "压缩效果": f"{original_len} → {new_len} 字符",
                    "减少比例": f"{reduction}%"
                },
                footer="发送 /快捷人格 确认生成 或 /快捷人格 取消操作"
            ):
                yield r
        else:
            # 获取用户名用于占位符替换
            user_name = event.get_sender_name() or "User"
            success = await self.persona_service.create_or_update(
                persona_id, result, backup=True, user_name=user_name
            )
            if success:
                async for r in self._render_persona_card(
                    event,
                    icon="✅",
                    title=f"压缩完成并已应用",
                    subtitle=f"强度: {intensity}",
                    content=result,
                    meta_info={
                        "人格ID": persona_id,
                        "压缩效果": f"{original_len} → {new_len} 字符",
                        "减少比例": f"{reduction}%"
                    },
                ):
                    yield r
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
            f"💡 使用 /快捷人格 应用人格 应用到当前对话"
        )

    @qp.command("应用人格", alias={"activate", "apply"})
    async def cmd_activate(self, event: AstrMessageEvent, persona_id: str = ""):
        """应用人格到当前对话"""
        try:
            session_id = get_session_id(event)
            session = self.state.get_session(session_id)

            if not persona_id:
                persona_id = session.current_persona_id or ""

            if not persona_id:
                yield event.plain_result(
                    "请指定人格ID，例如: /快捷人格 应用人格 qp_猫娘_abc123\n"
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
                yield event.plain_result(f"❌ 应用失败: {msg}")

        except Exception as e:
            logger.error(f"[lzpersona] 应用人格失败: {e}")
            yield event.plain_result(f"❌ 应用人格失败: {e}")
        finally:
            event.stop_event()

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
                    f"✅ 已创建新对话并应用人格\n📌 对话ID: {result}\n🎭 人格: {persona_id}"
                )
            else:
                yield event.plain_result(
                    f"✅ 已创建新对话\n📌 对话ID: {result}\n"
                    f"💡 使用 /快捷人格 应用人格 <人格ID> 指定人格"
                )
        else:
            yield event.plain_result(f"❌ 新建对话失败: {result}")

    @qp.command("删除人格", alias={"delete"})
    async def cmd_delete(self, event: AstrMessageEvent, persona_id: str = ""):
        """删除人格"""
        try:
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

        except Exception as e:
            logger.error(f"[lzpersona] 删除人格失败: {e}")
            yield event.plain_result(f"❌ 删除人格失败: {e}")
        finally:
            event.stop_event()

    # ==================== 用户画像功能 ====================

    def _get_profile_enabled(self) -> bool:
        """是否启用用户画像功能"""
        return bool(self._get_cfg("profile_enabled", False))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_for_profile(self, event: AstrMessageEvent):
        """监听所有消息用于用户画像更新（静默运行，不阻止事件传播）
        
        使用 event_message_type 过滤器监听所有类型的消息事件，
        这样可以在消息到达时就进行处理，而不是等到 LLM 响应后。
        """
        if not self._get_profile_enabled():
            return  # 不调用 stop_event()，让事件继续传播
        
        # 提取消息文本
        message_text = ""
        for comp in event.message_obj.message:
            if isinstance(comp, Plain):
                message_text += comp.text
        
        if not message_text.strip():
            return  # 不调用 stop_event()，让事件继续传播
        
        # 获取发送者信息
        sender_id = str(event.get_sender_id() or "")
        sender_name = event.get_sender_name() or ""
        
        # 获取群ID（如果是群聊）
        group_id = ""
        umo = getattr(event, "unified_msg_origin", "")
        if ":group:" in umo:
            parts = umo.split(":")
            if len(parts) >= 3:
                group_id = parts[2]
        
        # 处理消息（静默，不产生任何输出，不阻止事件传播）
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
        
        # 注意：不调用 event.stop_event()，让事件继续传播到其他处理器

    # ==================== 画像命令组 ====================

    @filter.command_group("画像", alias={"profile", "pf"})
    def profile_cmd(self):
        """用户画像命令组"""
        pass

    @profile_cmd.command("帮助", alias={"help", "?"})
    async def profile_help(self, event: AstrMessageEvent):
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

    @profile_cmd.command("添加监控", alias={"add", "monitor"})
    async def profile_add_monitor(self, event: AstrMessageEvent, user_id: str = "", mode: str = "global"):
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
            monitor = await self.profile_service.add_monitor(
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

    @profile_cmd.command("移除监控", alias={"remove", "rm"})
    async def profile_remove_monitor(self, event: AstrMessageEvent, user_id: str = ""):
        """移除画像监控"""
        if not user_id:
            yield event.plain_result("请指定用户ID，例如：/画像 移除监控 123456789")
            return
        
        success = await self.profile_service.remove_monitor(user_id)
        if success:
            yield event.plain_result(f"✅ 已移除对用户 {user_id} 的监控")
        else:
            yield event.plain_result(f"❌ 未找到用户 {user_id} 的监控配置")

    @profile_cmd.command("监控列表", alias={"monitors"})
    async def profile_list_monitors(self, event: AstrMessageEvent):
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

    @profile_cmd.command("查看", alias={"view", "show"})
    async def profile_view(self, event: AstrMessageEvent, user_id: str = ""):
        """查看用户画像"""
        if not user_id:
            yield event.plain_result("请指定用户ID，例如：/画像 查看 123456789")
            return
        
        profile = await self.profile_service.get_profile(user_id)
        if not profile:
            yield event.plain_result(f"❌ 未找到用户 {user_id} 的画像")
            return
        
        # 渲染画像卡片
        try:
            last_updated = datetime.fromtimestamp(profile.last_updated).strftime("%Y-%m-%d %H:%M") if profile.last_updated else "从未"
            
            image_url = await self.html_render(
                PROFILE_CARD_TEMPLATE,
                {
                    "avatar_emoji": "👤",
                    "nickname": profile.nickname or "未知",
                    "user_id": profile.user_id,
                    "profile_text": profile.profile_text or "暂无画像描述",
                    "traits": profile.traits,
                    "interests": profile.interests,
                    "speaking_style": profile.speaking_style,
                    "emotional_tendency": profile.emotional_tendency,
                    "message_count": profile.message_count,
                    "last_updated": last_updated,
                },
                options={"full_page": True}
            )
            yield event.image_result(image_url)
        except Exception as e:
            logger.warning(f"[lzpersona] 画像卡片渲染失败: {e}")
            # 降级为纯文本
            lines = [
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
            yield event.plain_result("\n".join(lines))

    @profile_cmd.command("列表", alias={"list", "ls"})
    async def profile_list(self, event: AstrMessageEvent):
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

    @profile_cmd.command("强制更新", alias={"update", "refresh"})
    async def profile_force_update(self, event: AstrMessageEvent, user_id: str = ""):
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

    @profile_cmd.command("删除", alias={"delete", "del"})
    async def profile_delete(self, event: AstrMessageEvent, user_id: str = ""):
        """删除用户画像"""
        if not user_id:
            yield event.plain_result("请指定用户ID，例如：/画像 删除 123456789")
            return
        
        success = await self.profile_service.delete_profile(user_id)
        if success:
            yield event.plain_result(f"✅ 已删除用户 {user_id} 的画像和监控配置")
        else:
            yield event.plain_result(f"❌ 未找到用户 {user_id} 的画像")

    @profile_cmd.command("缓冲状态", alias={"buffer"})
    async def profile_buffer_status(self, event: AstrMessageEvent, user_id: str = ""):
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
