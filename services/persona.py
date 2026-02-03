"""人格操作服务"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot.api import logger

from ..core.constants import PERSONA_PREFIX
from ..utils.helpers import replace_placeholders, extract_char_name

if TYPE_CHECKING:
    from astrbot.api.star import Context
    from ..core.state import QuickPersonaState


class PersonaService:
    """人格操作服务"""

    def __init__(
        self,
        context: "Context",
        state: "QuickPersonaState",
        backup_versions: int = 5,
    ):
        self.context = context
        self.state = state
        self.backup_versions = backup_versions
        self.persona_manager = context.persona_manager
        self.conversation_manager = context.conversation_manager

    async def create_or_update(
        self,
        persona_id: str,
        system_prompt: str,
        backup: bool = True,
        user_name: str = "User",
    ) -> bool:
        """创建或更新人格

        Args:
            persona_id: 人格ID
            system_prompt: 系统提示词
            backup: 是否备份旧版本
            user_name: 用户名（用于替换占位符）

        Returns:
            是否成功
        """
        try:
            # 替换占位符
            char_name = extract_char_name(system_prompt)
            processed_prompt = replace_placeholders(
                system_prompt, char_name=char_name, user_name=user_name
            )
            # 检查是否已存在
            existing = None
            try:
                existing = await self.persona_manager.get_persona(persona_id)
            except ValueError:
                pass

            if existing:
                # 备份旧版本
                if backup:
                    self.state.add_backup(
                        persona_id, existing.system_prompt, self.backup_versions
                    )
                    await self.state.save_backups()

                # 更新
                await self.persona_manager.update_persona(
                    persona_id=persona_id, system_prompt=processed_prompt
                )
                logger.info(f"[lzpersona] 已更新人格: {persona_id}")
            else:
                # 创建新人格
                await self.persona_manager.create_persona(
                    persona_id=persona_id, system_prompt=processed_prompt
                )
                logger.info(f"[lzpersona] 已创建人格: {persona_id}")

            return True

        except Exception as e:
            logger.error(f"[lzpersona] 创建/更新人格失败: {e}")
            return False

    async def get_persona(self, persona_id: str):
        """获取人格

        Args:
            persona_id: 人格ID

        Returns:
            人格对象

        Raises:
            ValueError: 人格不存在
        """
        return await self.persona_manager.get_persona(persona_id)

    async def get_all_personas(self):
        """获取所有人格"""
        return await self.persona_manager.get_all_personas()

    async def delete_persona(self, persona_id: str) -> bool:
        """删除人格

        Args:
            persona_id: 人格ID

        Returns:
            是否成功
        """
        try:
            await self.persona_manager.delete_persona(persona_id)
            # 清理备份
            self.state.delete_persona_backups(persona_id)
            return True
        except Exception as e:
            logger.error(f"[lzpersona] 删除人格失败: {e}")
            return False

    async def activate_persona(self, umo: str, persona_id: str) -> tuple[bool, str]:
        """激活人格到当前对话

        Args:
            umo: 统一消息源
            persona_id: 人格ID

        Returns:
            (是否成功, 消息)
        """
        try:
            # 获取当前对话ID
            curr_conv_id = await self.conversation_manager.get_curr_conversation_id(
                umo
            )

            if curr_conv_id:
                # 更新现有对话的人格
                await self.conversation_manager.update_conversation(
                    umo=umo, conversation_id=curr_conv_id, persona_id=persona_id
                )
                return True, f"已激活人格: {persona_id}"
            else:
                # 创建新对话并关联人格
                new_conv_id = await self.conversation_manager.new_conversation(
                    umo=umo, persona_id=persona_id, title=f"人格: {persona_id}"
                )
                return True, f"已创建新对话并激活人格: {persona_id}\n对话ID: {new_conv_id}"

        except Exception as e:
            logger.error(f"[lzpersona] 激活人格失败: {e}")
            return False, str(e)

    async def new_conversation(
        self, umo: str, persona_id: str = ""
    ) -> tuple[bool, str]:
        """新建对话

        Args:
            umo: 统一消息源
            persona_id: 可选的人格ID

        Returns:
            (是否成功, 消息或对话ID)
        """
        try:
            new_conv_id = await self.conversation_manager.new_conversation(
                umo=umo,
                persona_id=persona_id if persona_id else None,
                title=f"人格: {persona_id}" if persona_id else None,
            )
            return True, new_conv_id
        except Exception as e:
            logger.error(f"[lzpersona] 新建对话失败: {e}")
            return False, str(e)

    def is_plugin_persona(self, persona_id: str) -> bool:
        """判断是否为本插件创建的人格"""
        return persona_id.startswith(PERSONA_PREFIX)
