"""渲染服务 - 统一处理图片/卡片渲染"""

from __future__ import annotations

from typing import Any, Dict, Callable, TYPE_CHECKING

from astrbot.api import logger

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent


# 人格卡片 HTML 模板
PERSONA_CARD_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body {
            width: 100%; min-height: 100vh; display: flex;
            justify-content: center; align-items: flex-start;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
            padding: 40px 20px;
        }
        .card {
            width: 100%; max-width: 700px;
            background: rgba(255, 255, 255, 0.98);
            border-radius: 12px; padding: 30px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }
        .header {
            display: flex; align-items: center;
            margin-bottom: 20px; padding-bottom: 15px;
            border-bottom: 1.5px solid #eee;
        }
        .icon { font-size: 32px; margin-right: 15px; }
        .title-group { flex-grow: 1; }
        .title { font-size: 22px; font-weight: bold; color: #1a1a1a; }
        .subtitle { font-size: 14px; color: #666; margin-top: 4px; }
        .meta-container {
            display: flex; flex-wrap: wrap; gap: 20px;
            margin-bottom: 25px; padding: 15px;
            background: #f8f9fa; border-radius: 8px;
        }
        .meta-item { font-size: 14px; color: #444; }
        .meta-label { color: #888; margin-right: 5px; }
        .content {
            font-size: 15px; line-height: 1.8; color: #333;
            white-space: pre-wrap; word-wrap: break-word;
            text-align: justify;
        }
        .footer {
            margin-top: 25px; padding-top: 15px;
            border-top: 1px solid #eee;
            font-size: 13px; color: #999;
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
</html>'''


class RenderService:
    """渲染服务 - 统一处理图片和卡片渲染"""

    def __init__(self, plugin):
        """
        Args:
            plugin: 插件实例 (Star 子类)，需要有 html_render 和 text_to_image 方法
        """
        self._plugin = plugin

    @property
    def _html_render(self):
        return self._plugin.html_render

    @property
    def _text_to_image(self):
        return self._plugin.text_to_image

    async def render_persona_card(
        self,
        event: "AstrMessageEvent",
        icon: str,
        title: str,
        subtitle: str,
        content: str,
        meta_info: Dict[str, str] = None,
        footer: str = "",
    ):
        """渲染人格卡片为图片"""
        try:
            image_url = await self._html_render(
                PERSONA_CARD_TEMPLATE,
                {
                    "icon": icon,
                    "title": title,
                    "subtitle": subtitle,
                    "content": content,
                    "meta_info": meta_info or {},
                    "footer": footer,
                },
                options={"full_page": True},
            )
            yield event.image_result(image_url)
        except Exception as e:
            logger.warning(f"[lzpersona] 人格卡片渲染失败: {e}")
            # 降级为纯文本
            lines = [f"{icon} {title}", subtitle, "-" * 30, content]
            if meta_info:
                lines.append("-" * 30)
                for k, v in meta_info.items():
                    lines.append(f"{k}: {v}")
            if footer:
                lines.extend(["-" * 30, footer])
            yield event.plain_result("\n".join(lines))

    async def render_long_text(
        self,
        event: "AstrMessageEvent",
        title: str,
        content: str,
        extra_info: str = "",
    ):
        """将长文本渲染为图片输出"""
        lines = [f"📌 {title}", "=" * 40, "", content]
        if extra_info:
            lines.extend(["", "-" * 40, extra_info])

        text = "\n".join(lines)

        try:
            image_url = await self._text_to_image(text)
            yield event.image_result(image_url)
        except Exception as e:
            logger.warning(f"[lzpersona] 文转图失败: {e}")
            yield event.plain_result(text)
