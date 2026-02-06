"""
人格提示词格式模板

支持多种输出格式：自然语言、Markdown、XML、JSON、YAML
每种格式都确保保留所有人格特征信息
"""

from enum import Enum


class PromptFormat(Enum):
    """人格提示词格式枚举"""
    NATURAL = "natural"      # 自然语言（默认）
    MARKDOWN = "markdown"    # Markdown 结构化
    XML = "xml"              # XML 标签格式
    JSON = "json"            # JSON 结构化
    YAML = "yaml"            # YAML 格式


# 格式别名映射
FORMAT_ALIASES = {
    # 自然语言
    "natural": PromptFormat.NATURAL,
    "自然语言": PromptFormat.NATURAL,
    "text": PromptFormat.NATURAL,
    "txt": PromptFormat.NATURAL,
    # Markdown
    "markdown": PromptFormat.MARKDOWN,
    "md": PromptFormat.MARKDOWN,
    # XML
    "xml": PromptFormat.XML,
    # JSON
    "json": PromptFormat.JSON,
    # YAML
    "yaml": PromptFormat.YAML,
    "yml": PromptFormat.YAML,
}


def parse_format(format_str: str) -> PromptFormat:
    """解析格式字符串为枚举值"""
    return FORMAT_ALIASES.get(format_str.lower().strip(), PromptFormat.NATURAL)


# ==================== 生成模板 ====================

# 自然语言格式生成模板
GENERATE_TEMPLATE_NATURAL = """你是一位专业的 AI 人格设计师。请根据以下描述，生成一个完整、生动、有个性的人格设定。

用户描述：{description}

要求：
1. 使用自然流畅的语言描述人格
2. 包含以下要素（如果用户未提供，请合理创造）：
   - 基本身份（姓名、年龄、身份）
   - 性格特点（核心性格、行为模式）
   - 说话风格（语气、口癖、常用词汇）
   - 与用户的关系设定
   - 情感表达方式
3. 保持人格一致性和可信度
4. 直接输出人格设定内容，不要添加解释性文字

请生成人格设定："""

# Markdown 格式生成模板
GENERATE_TEMPLATE_MARKDOWN = """你是一位专业的 AI 人格设计师。请根据以下描述，使用 Markdown 格式生成结构化的人格设定。

用户描述：{description}

要求：
1. 使用标准 Markdown 格式
2. 必须包含以下章节结构：
   ```markdown
   # 角色名称
   
   ## 基本信息
   - **姓名**: 
   - **年龄**: 
   - **身份**: 
   - **外貌特征**: 
   
   ## 性格特点
   - 核心性格特征
   - 行为模式
   
   ## 说话风格
   - 语气特点
   - 口癖/常用语
   - 表情符号使用偏好
   
   ## 关系设定
   - 与用户的关系
   - 互动方式
   
   ## 情感表达
   - 开心时的表现
   - 害羞时的表现
   - 生气时的表现
   
   ## 背景故事
   简要的背景描述
   
   ## 行为准则
   - 应该做什么
   - 避免做什么
   ```
3. 如果用户未提供某些信息，请合理创造
4. 直接输出 Markdown 内容，不要添加解释

请生成人格设定："""

# XML 格式生成模板
GENERATE_TEMPLATE_XML = """你是一位专业的 AI 人格设计师。请根据以下描述，使用 XML 格式生成结构化的人格设定。

用户描述：{description}

要求：
1. 使用标准 XML 格式
2. 必须遵循以下结构：
   ```xml
   <persona>
     <identity>
       <name>角色名称</name>
       <age>年龄</age>
       <role>身份</role>
       <appearance>外貌描述</appearance>
     </identity>
     
     <personality>
       <core_traits>
         <trait>核心性格1</trait>
         <trait>核心性格2</trait>
       </core_traits>
       <behavior_patterns>
         <pattern>行为模式描述</pattern>
       </behavior_patterns>
     </personality>
     
     <speech_style>
       <tone>语气描述</tone>
       <verbal_tics>口癖/常用语</verbal_tics>
       <emoji_usage>表情符号使用偏好</emoji_usage>
     </speech_style>
     
     <relationship>
       <with_user>与用户的关系</with_user>
       <interaction_style>互动方式</interaction_style>
     </relationship>
     
     <emotional_expressions>
       <happy>开心时的表现</happy>
       <shy>害羞时的表现</shy>
       <angry>生气时的表现</angry>
     </emotional_expressions>
     
     <background>背景故事</background>
     
     <guidelines>
       <do>应该做的事</do>
       <avoid>避免做的事</avoid>
     </guidelines>
   </persona>
   ```
3. 如果用户未提供某些信息，请合理创造
4. 直接输出 XML 内容，不要添加解释

请生成人格设定："""

# JSON 格式生成模板
GENERATE_TEMPLATE_JSON = """你是一位专业的 AI 人格设计师。请根据以下描述，使用 JSON 格式生成结构化的人格设定。

用户描述：{description}

要求：
1. 使用标准 JSON 格式
2. 必须遵循以下结构：
   ```json
   {{
     "persona": {{
       "identity": {{
         "name": "角色名称",
         "age": "年龄",
         "role": "身份",
         "appearance": "外貌描述"
       }},
       "personality": {{
         "core_traits": ["核心性格1", "核心性格2"],
         "behavior_patterns": ["行为模式描述"]
       }},
       "speech_style": {{
         "tone": "语气描述",
         "verbal_tics": ["口癖1", "常用语2"],
         "emoji_usage": "表情符号使用偏好"
       }},
       "relationship": {{
         "with_user": "与用户的关系",
         "interaction_style": "互动方式"
       }},
       "emotional_expressions": {{
         "happy": "开心时的表现",
         "shy": "害羞时的表现",
         "angry": "生气时的表现"
       }},
       "background": "背景故事",
       "guidelines": {{
         "do": ["应该做的事1", "应该做的事2"],
         "avoid": ["避免做的事1", "避免做的事2"]
       }}
     }}
   }}
   ```
3. 如果用户未提供某些信息，请合理创造
4. 确保 JSON 格式有效，可被解析
5. 直接输出 JSON 内容，不要添加解释

请生成人格设定："""

# YAML 格式生成模板
GENERATE_TEMPLATE_YAML = """你是一位专业的 AI 人格设计师。请根据以下描述，使用 YAML 格式生成结构化的人格设定。

用户描述：{description}

要求：
1. 使用标准 YAML 格式
2. 必须遵循以下结构：
   ```yaml
   persona:
     identity:
       name: 角色名称
       age: 年龄
       role: 身份
       appearance: 外貌描述
     
     personality:
       core_traits:
         - 核心性格1
         - 核心性格2
       behavior_patterns:
         - 行为模式描述
     
     speech_style:
       tone: 语气描述
       verbal_tics:
         - 口癖1
         - 常用语2
       emoji_usage: 表情符号使用偏好
     
     relationship:
       with_user: 与用户的关系
       interaction_style: 互动方式
     
     emotional_expressions:
       happy: 开心时的表现
       shy: 害羞时的表现
       angry: 生气时的表现
     
     background: 背景故事
     
     guidelines:
       do:
         - 应该做的事1
         - 应该做的事2
       avoid:
         - 避免做的事1
         - 避免做的事2
   ```
3. 如果用户未提供某些信息，请合理创造
4. 确保 YAML 格式有效，缩进正确
5. 直接输出 YAML 内容，不要添加解释

请生成人格设定："""


# ==================== 格式转换模板 ====================

FORMAT_CONVERT_TEMPLATE = """你是一位专业的格式转换专家。请将以下人格设定从当前格式转换为目标格式。

【重要】转换时必须：
1. 保留所有原有内容和特征，不能遗漏任何信息
2. 保持语义完全一致
3. 如果原格式缺少某些结构字段，保持为空或使用"未设定"
4. 不要添加原文没有的新内容
5. 不要修改任何人格特征

原始人格设定（{source_format}格式）：
{original_prompt}

目标格式：{target_format}

{format_structure_hint}

请输出转换后的人格设定（仅输出转换结果，不要添加解释）："""


# 格式结构提示
FORMAT_STRUCTURE_HINTS = {
    PromptFormat.NATURAL: """目标格式说明：
使用自然流畅的语言描述，保持段落结构清晰，不使用特殊格式标记。""",
    
    PromptFormat.MARKDOWN: """目标格式说明：
使用 Markdown 格式，包含标题(#)、列表(-)、加粗(**)等元素。
结构包含：基本信息、性格特点、说话风格、关系设定、情感表达、背景故事、行为准则。""",
    
    PromptFormat.XML: """目标格式说明：
使用 XML 标签格式，根标签为 <persona>。
内部包含：<identity>, <personality>, <speech_style>, <relationship>, <emotional_expressions>, <background>, <guidelines>。""",
    
    PromptFormat.JSON: """目标格式说明：
使用 JSON 格式，根对象包含 "persona" 键。
内部包含：identity, personality, speech_style, relationship, emotional_expressions, background, guidelines。
确保 JSON 格式有效。""",
    
    PromptFormat.YAML: """目标格式说明：
使用 YAML 格式，根键为 persona。
内部包含：identity, personality, speech_style, relationship, emotional_expressions, background, guidelines。
注意正确的缩进（2空格）。""",
}


# ==================== 优化模板（带格式保持） ====================

REFINE_TEMPLATE_WITH_FORMAT = """你是一位专业的 AI 人格设计师。请根据反馈优化以下人格设定。

【重要】优化时必须：
1. 保持原有格式（{format_type}格式）不变
2. 保留所有未被反馈涉及的原有特征
3. 只修改反馈明确指出需要调整的部分
4. 不要删除任何原有设定（除非反馈明确要求删除）

当前人格设定：
{current_prompt}

用户反馈：{feedback}

请输出优化后的人格设定（保持{format_type}格式）："""


# ==================== 压缩模板（带格式保持） ====================

SHRINK_TEMPLATE_WITH_FORMAT = """你是一位专业的文本压缩专家。请压缩以下人格设定，同时保持其核心特征。

【重要】压缩时必须：
1. 保持原有格式（{format_type}格式）不变
2. 保留所有核心人格特征
3. 删除冗余描述，合并相似内容
4. 压缩强度：{intensity}
   - 轻度：保留大部分细节，只删除明显冗余
   - 中度：精简描述，保留关键特征
   - 极限：只保留最核心的设定

原始人格设定：
{original_prompt}

请输出压缩后的人格设定（保持{format_type}格式）："""


# ==================== 带补充信息生成模板 ====================

GENERATE_WITH_SUPPLEMENTS_TEMPLATE = """你是一位专业的 AI 人格设计师。请根据以下信息生成完整的人格设定。

用户描述：{description}

用户补充信息：{supplements}

需要 AI 自动生成的部分：{auto_generate_fields}

输出格式要求：{format_type}

{format_structure_hint}

要求：
1. 整合用户提供的所有信息
2. 为缺失部分创造合理的设定
3. 确保人格一致性和完整性
4. 使用指定的格式输出

请生成人格设定："""


def get_generate_template(format_type: PromptFormat) -> str:
    """获取对应格式的生成模板"""
    templates = {
        PromptFormat.NATURAL: GENERATE_TEMPLATE_NATURAL,
        PromptFormat.MARKDOWN: GENERATE_TEMPLATE_MARKDOWN,
        PromptFormat.XML: GENERATE_TEMPLATE_XML,
        PromptFormat.JSON: GENERATE_TEMPLATE_JSON,
        PromptFormat.YAML: GENERATE_TEMPLATE_YAML,
    }
    return templates.get(format_type, GENERATE_TEMPLATE_NATURAL)


def get_format_hint(format_type: PromptFormat) -> str:
    """获取格式结构提示"""
    return FORMAT_STRUCTURE_HINTS.get(format_type, "")


def get_format_display_name(format_type: PromptFormat) -> str:
    """获取格式的显示名称"""
    names = {
        PromptFormat.NATURAL: "自然语言",
        PromptFormat.MARKDOWN: "Markdown",
        PromptFormat.XML: "XML",
        PromptFormat.JSON: "JSON",
        PromptFormat.YAML: "YAML",
    }
    return names.get(format_type, "自然语言")
