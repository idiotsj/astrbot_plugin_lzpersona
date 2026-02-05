"""状态管理模块"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from datetime import datetime
from typing import Optional

from astrbot.api import logger

from .models import PersonaBackup, SessionData


class QuickPersonaState:
    """插件状态管理

    备份存储结构 (独立于插件安装目录，防止卸载时数据丢失):
    data/plugin_data/astrbot_plugin_lzpersona/
    ├── backups/
    │   ├── lz_猫娘_abc123/
    │   │   ├── v001_20260202_123456.txt  # 版本文件: 提示词内容
    │   │   ├── v002_20260202_134500.txt
    │   │   └── ...
    │   └── lz_傲娇_def456/
    │       └── ...
    └── (运行时状态仅存储在内存中，不持久化)
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.backups_dir = os.path.join(data_dir, "backups")

        # session_id -> SessionData (运行时状态，不持久化)
        self.sessions: dict[str, SessionData] = {}
        # persona_id -> list of PersonaBackup (从文件系统加载)
        self.backups: dict[str, list[PersonaBackup]] = {}

        self._save_lock = asyncio.Lock()

        # 确保备份目录存在
        os.makedirs(self.backups_dir, exist_ok=True)

    def _get_persona_backup_dir(self, persona_id: str) -> str:
        """获取人格备份目录"""
        # 清理 persona_id 中的非法字符用于文件夹名
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", persona_id)
        return os.path.join(self.backups_dir, safe_name)

    def _parse_backup_filename(self, filename: str) -> Optional[tuple[int, float]]:
        """解析备份文件名，返回 (版本号, 时间戳)"""
        # 格式: v001_20260202_123456.txt
        match = re.match(r"^v(\d+)_(\d{8})_(\d{6})\.txt$", filename)
        if match:
            version = int(match.group(1))
            date_str = match.group(2)
            time_str = match.group(3)
            try:
                dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                return (version, dt.timestamp())
            except ValueError:
                pass
        return None

    def _generate_backup_filename(self, version: int, timestamp: float) -> str:
        """生成备份文件名"""
        dt = datetime.fromtimestamp(timestamp)
        return f"v{version:03d}_{dt.strftime('%Y%m%d_%H%M%S')}.txt"

    def load(self) -> None:
        """从文件系统加载备份数据"""
        self.backups = {}

        if not os.path.exists(self.backups_dir):
            return

        try:
            # 遍历备份目录下的所有人格文件夹
            for persona_dir_name in os.listdir(self.backups_dir):
                persona_dir = os.path.join(self.backups_dir, persona_dir_name)
                if not os.path.isdir(persona_dir):
                    continue

                backups = []
                for filename in os.listdir(persona_dir):
                    if not filename.endswith(".txt"):
                        continue

                    parsed = self._parse_backup_filename(filename)
                    if not parsed:
                        continue

                    version, timestamp = parsed
                    filepath = os.path.join(persona_dir, filename)

                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            system_prompt = f.read()

                        backups.append(
                            PersonaBackup(
                                persona_id=persona_dir_name,
                                system_prompt=system_prompt,
                                backed_up_at=timestamp,
                            )
                        )
                    except Exception as e:
                        logger.warning(
                            f"[lzpersona] 读取备份文件失败 {filepath}: {e}"
                        )

                # 按时间戳降序排列（最新的在前）
                backups.sort(key=lambda b: b.backed_up_at, reverse=True)
                if backups:
                    self.backups[persona_dir_name] = backups

            logger.info(f"[lzpersona] 已加载 {len(self.backups)} 个人格的备份数据")

        except Exception as e:
            logger.error(f"[lzpersona] 加载备份数据失败: {e}")
            self.backups = {}

    async def save_backups(self) -> None:
        """保存备份数据到文件系统（此方法现在主要用于触发清理过期备份）"""
        # 实际的备份写入在 add_backup 中完成
        pass

    async def save_async(self) -> None:
        """异步保存状态（用于插件卸载时的清理）
        
        由于备份数据是实时写入文件的，此方法主要用于确保一致性
        """
        async with self._save_lock:
            # 备份数据已经实时保存到文件系统，无需额外操作
            # 会话数据是运行时状态，不需要持久化
            logger.debug("[lzpersona] 状态保存完成")

    def get_session(self, session_id: str) -> SessionData:
        """获取会话数据"""
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionData()
        return self.sessions[session_id]

    def add_backup(
        self, persona_id: str, system_prompt: str, max_versions: int = 5
    ) -> None:
        """添加人格备份（同步写入文件）"""
        # 获取或创建人格备份目录
        backup_dir = self._get_persona_backup_dir(persona_id)
        os.makedirs(backup_dir, exist_ok=True)

        # 确定新版本号
        if persona_id not in self.backups:
            self.backups[persona_id] = []

        existing_versions = []
        for filename in os.listdir(backup_dir):
            parsed = self._parse_backup_filename(filename)
            if parsed:
                existing_versions.append(parsed[0])

        new_version = max(existing_versions) + 1 if existing_versions else 1
        timestamp = time.time()

        # 写入备份文件
        filename = self._generate_backup_filename(new_version, timestamp)
        filepath = os.path.join(backup_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(system_prompt)

            # 更新内存中的备份列表
            backup = PersonaBackup(
                persona_id=persona_id,
                system_prompt=system_prompt,
                backed_up_at=timestamp,
            )
            self.backups[persona_id].insert(0, backup)

            logger.info(f"[lzpersona] 已保存备份: {filepath}")

            # 清理过期版本
            self._cleanup_old_backups(persona_id, max_versions)

        except Exception as e:
            logger.error(f"[lzpersona] 保存备份失败: {e}")

    def _cleanup_old_backups(self, persona_id: str, max_versions: int) -> None:
        """清理过期的备份版本"""
        if persona_id not in self.backups:
            return

        backup_dir = self._get_persona_backup_dir(persona_id)
        if not os.path.exists(backup_dir):
            return

        # 获取所有备份文件并按时间排序
        backup_files = []
        for filename in os.listdir(backup_dir):
            parsed = self._parse_backup_filename(filename)
            if parsed:
                backup_files.append((filename, parsed[1]))  # (filename, timestamp)

        backup_files.sort(key=lambda x: x[1], reverse=True)  # 最新的在前

        # 删除超出数量的旧备份
        for filename, _ in backup_files[max_versions:]:
            filepath = os.path.join(backup_dir, filename)
            try:
                os.remove(filepath)
                logger.info(f"[lzpersona] 已删除过期备份: {filepath}")
            except Exception as e:
                logger.warning(f"[lzpersona] 删除备份失败 {filepath}: {e}")

        # 更新内存中的列表
        self.backups[persona_id] = self.backups[persona_id][:max_versions]

    def get_latest_backup(self, persona_id: str) -> Optional[PersonaBackup]:
        """获取最新备份"""
        if persona_id in self.backups and self.backups[persona_id]:
            return self.backups[persona_id][0]
        return None

    def get_all_backups(self, persona_id: str) -> list[PersonaBackup]:
        """获取人格的所有备份"""
        return self.backups.get(persona_id, [])

    def delete_persona_backups(self, persona_id: str) -> None:
        """删除人格的所有备份"""
        # 从内存中移除
        if persona_id in self.backups:
            del self.backups[persona_id]

        # 删除文件夹
        backup_dir = self._get_persona_backup_dir(persona_id)
        if os.path.exists(backup_dir):
            try:
                shutil.rmtree(backup_dir)
                logger.info(f"[lzpersona] 已删除备份目录: {backup_dir}")
            except Exception as e:
                logger.error(f"[lzpersona] 删除备份目录失败: {e}")
