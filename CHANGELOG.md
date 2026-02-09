# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.8] - 2026-02-10

### 修复
- 🐛 **人格激活失败修复** - 修复 `activate_persona` 和 `new_conversation` 中的参数名错误
  - 原代码使用 `umo=` 参数，现修正为 `unified_msg_origin=` 符合 AstrBot API 规范
- 🐛 **配置调试增强** - 首次获取 `max_prompt_length` 时打印完整配置信息，便于排查配置不生效问题

---

## [2.0.7] - 2026-02-10

### 改进
- 📝 **自动压缩调试日志** - 添加 logger.debug 日志输出 result_len/max_len/auto_compress 值，便于定位问题

---

## [2.0.6] - 2026-02-10

### 修复
- 🐛 **自动压缩反馈增强** - 生成人格时自动压缩现在会：
  - 显示压缩前后的字符数变化 (如 "2000 → 1500 字符")
  - 压缩失败或效果不佳时提示用户
  - 同时修复了 `_generate_with_supplements` 和 `_quick_generation` 两处逻辑

---

## [2.0.5] - 2026-02-10

### 修复
- 🐛 **画像服务配置获取修复** - 改用延迟属性获取配置，避免初始化时 `config_service` 未就绪
  - `min_messages_for_update`、`max_buffer_age`、`context_size`、`include_bot_replies` 改为属性方法
  - 优先使用 `plugin.config_service`，回退到 `context.get_config()`
- 🐛 **画像渲染调用修复** - 命令模块使用 `render_service.render_persona_card()` 替代不存在的 `self.html_render()`
- 🐛 **属性访问一致性修复** - `should_flush()`、上下文获取等处统一使用属性方法而非私有变量

### 改进
- ⚡ **代码清理** - 移除 `commands/profile.py` 中未使用的 `PROFILE_CARD_TEMPLATE` 导入

---

## [2.0.4] - 2026-02-08

### 改进
- 📝 **画像分析指引增强** - LLM 提示词新增详细的上下文分析指导
  - 互动模式分析：识别用户是主动发起话题还是被动回应
  - 社交关系分析：分析与群内其他成员、机器人的关系
  - 表达方式分析：语气词、表情符号、网络用语等
  - 情绪变化分析：不同话题下的情绪状态变化

---

## [2.0.3] - 2026-02-08

### 新增
- ✨ **画像对话上下文** - 更新画像时自动获取对话上下文
  - 从 `message_history_manager` 获取会话历史
  - 包含其他用户消息和机器人回复，帮助分析互动模式
  - 新增 `profile_context_size` 配置：上下文消息条数（默认 20）
  - 新增 `profile_include_bot` 配置：是否包含机器人回复（默认 true）

### 修复
- 🐛 **JSON 解析统一** - 画像服务复用 `llm.py` 中的 `_extract_json_object()` 函数，支持嵌套 JSON
- 🐛 **机器人消息识别** - 修复机器人回复识别逻辑，正确匹配 `sender_id == "bot"` 格式

### 改进
- ⚡ **LLM 提示词增强** - 画像更新和初始化时提供对话上下文，提高画像质量

---

## [2.0.2] - 2026-02-06

### 改进
- ⚡ **命令解析重构** - 使用正则表达式替换硬编码命令前缀列表（响应 Linus 评审意见）
- ⚡ **LLM 调用重试机制** - 新增 `llm_max_retries` 配置项，失败时自动重试（响应 Tony 评审意见）
- 📝 **JSON 解析器文档完善** - 更新 `_extract_json_object()` 函数注释，明确支持字符串内转义大括号的处理

### 新增配置
- `llm_max_retries`: LLM 调用最大重试次数（默认 2）

---

## [2.0.1] - 2026-02-06

### 修复
- 🐛 **数据持久化路径修复** - 直接使用 `StarTools.get_data_dir()` 返回的规范路径，不再手动操作父目录
- 🐛 **JSON 解析健壮性** - 新增 `_extract_json_object()` 函数支持嵌套 JSON 对象提取，替代简单正则表达式
- 🐛 **HTML 渲染返回值验证** - 画像卡片渲染增加空值检查，失败时降级为纯文本输出
- 🐛 **备份文件容错处理** - 加载备份时统计并汇总跳过的损坏文件数量，提醒数据完整性问题

---

## [2.0.0] - 2026-02-06

### 🎉 重大更新

#### 新增功能
- ✨ **用户画像系统** - 全新的用户画像功能
  - 支持监控指定用户的聊天消息
  - 从对话中自动提取用户特征
  - 支持 global/group/private 三种监控模式
  - 美观的画像展示卡片
  - `/画像` 命令组管理用户画像

- ✨ **智能意图识别** - `/人格` 命令智能入口
  - 自然语言理解用户意图
  - 自动路由到对应的命令
  - 支持生成、优化、切换、删除等操作

- ✨ **引导式生成** - 更智能的人格生成流程
  - 分析描述中的缺失字段
  - 引导用户补充关键信息
  - 支持跳过让 AI 自动生成

- ✨ **多格式支持** - 人格提示词格式化
  - 支持 Natural/Markdown/XML/JSON/YAML 格式
  - `/快捷人格 转换格式` 命令格式互转
  - 可配置默认格式

- ✨ **会话级并发控制**
  - 添加会话锁防止并发操作
  - `get_session_lock()` 和 `acquire_session()` API

#### 架构改进
- 🏗️ **模块化重构** - 代码结构优化
  - 分离 commands/services/core/utils 模块
  - PersonaCommands 和 ProfileCommands 混入类
  - LLMService 高级方法封装
  - 配置管理独立为 ConfigService

- 🔧 **LLMService 高级方法**
  - `generate_persona()` - 生成人格
  - `refine_persona()` - 优化人格
  - `shrink_persona()` - 压缩人格
  - `convert_format()` - 格式转换
  - `generate_with_supplements()` - 带补充信息生成

- 📦 **状态管理优化**
  - 备份数据实时写入文件系统
  - 独立于插件安装目录存储
  - 会话状态运行时管理

### 修复
- 🐛 配置 Schema 类型修复：模板字段改为 `text` 类型
- 🐛 格式字段添加 `options` 下拉选择
- 🐛 UMO 获取方式改用 `event.unified_msg_origin` 属性访问

### 变更
- ⚡ 移除未使用的模板常量导入
- ⚡ 命令统一使用 LLMService 高级方法

---

## [1.1.0] - 2026-02-05

### 新增
- ✨ 用户画像功能框架
- ✨ 格式转换基础支持

### 修复
- 🐛 修复命令解析问题

---

## [1.0.1] - 2026-02-04

### 修复与优化
- 🐛 修复命令解析截断问题，优化用户体验
- ⚡ 精简生成模板并添加防注入逻辑
- 🔧 更新压缩模板为角色卡架构师模式，添加占位符替换逻辑
- 🐛 使用 GreedyStr 替代 *args 解决参数解析错误
- 🐛 修复 `__init__` 签名，移除多余的 config 参数

---

## [1.0.0] - 2026-02-02

### 🎉 初始版本

#### 功能
- 🎭 **人格生成** - 根据简单描述自动生成完整的人格提示词
- 🔧 **人格优化** - 根据反馈智能调整现有人格
- 📦 **提示词瘦身** - 压缩提示词以节省 Token（支持轻度/中度/极限三档）
- ✅ **确认机制** - 生成后预览，确认后才应用，避免误操作
- 💾 **版本备份** - 自动备份历史版本，支持一键回滚
- 🔗 **原生对接** - 与 AstrBot 原生 Persona 系统无缝集成

#### 命令
- `/快捷人格 生成人格` - 生成人格
- `/快捷人格 优化人格` - 优化人格
- `/快捷人格 压缩人格` - 压缩人格
- `/快捷人格 确认生成` - 确认保存
- `/快捷人格 取消操作` - 取消操作
- `/快捷人格 人格列表` - 列表
- `/快捷人格 应用人格` - 激活
- `/快捷人格 历史版本` - 历史
- `/快捷人格 版本回滚` - 回滚
