"""用户画像相关常量和模板"""

# 画像更新提示词模板
DEFAULT_PROFILE_UPDATE_TEMPLATE = """你是一个用户画像分析专家。请根据用户的聊天记录更新其画像。

## 当前画像
{current_profile}

## 新的聊天记录
{new_messages}

## 分析指引
在分析时，请特别注意以下方面：

### 从对话上下文中（如果有）
- **互动模式**: 目标用户如何与他人互动？是主动发起话题还是被动回应？
- **社交关系**: 与群内其他成员的关系如何？语气是亲近还是疏远？
- **回复习惯**: 对机器人的回复有什么反应？是否会追问、吐槽或表达满意？

### 从目标用户消息中
- **话题偏好**: 经常聊什么话题？有什么持续的兴趣？
- **表达方式**: 使用的语气词、表情符号、网络用语等
- **情绪变化**: 不同话题下的情绪状态是否有变化？

## 任务
1. 分析这些新消息，提取有价值的信息
2. 结合现有画像，生成更新后的画像
3. 保持画像简洁精炼，突出重点

## 输出格式（严格JSON）
{{
    "profile_text": "综合性的用户画像描述（100-300字）",
    "traits": ["性格特征1", "性格特征2", ...],
    "interests": ["兴趣爱好1", "兴趣爱好2", ...],
    "speaking_style": "说话风格描述",
    "emotional_tendency": "情感倾向描述"
}}

只输出JSON，不要有其他内容。"""

# 画像初始化提示词模板
DEFAULT_PROFILE_INIT_TEMPLATE = """你是一个用户画像分析专家。请根据用户的聊天记录创建初始画像。

## 用户信息
- 用户ID: {user_id}
- 昵称: {nickname}

## 聊天记录
{messages}

## 分析指引
在分析时，请特别注意以下方面：

### 从对话上下文中（如果有）
- **互动模式**: 目标用户如何与他人互动？是主动发起话题还是被动回应？
- **社交风格**: 对他人的回应是热情、冷淡还是中性？
- **群内角色**: 在群内扮演什么角色？是活跃分子还是潜水党？

### 从目标用户消息中
- **自我表达**: 用户如何展示自己？有什么特殊的口癖或表达习惯？
- **话题偏好**: 主动聊什么话题？对什么领域表现出兴趣？
- **情绪基调**: 整体情绪是积极、消极还是中性？

## 任务
分析这些消息，创建一个初始用户画像。

## 输出格式（严格JSON）
{{
    "profile_text": "综合性的用户画像描述（100-300字）",
    "traits": ["性格特征1", "性格特征2", ...],
    "interests": ["兴趣爱好1", "兴趣爱好2", ...],
    "speaking_style": "说话风格描述",
    "emotional_tendency": "情感倾向描述"
}}

只输出JSON，不要有其他内容。"""

# 画像查看卡片模板
PROFILE_CARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        html, body {
            width: 100%;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: flex-start;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
            padding: 40px 20px;
        }

        .card {
            width: 100%;
            max-width: 700px;
            background: rgba(255, 255, 255, 0.98);
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }

        .header {
            display: flex;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1.5px solid #eee;
        }
        .avatar { 
            width: 60px; 
            height: 60px; 
            border-radius: 50%; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
            color: white;
            margin-right: 15px;
        }
        .title-group { flex-grow: 1; }
        .title { font-size: 22px; font-weight: bold; color: #1a1a1a; }
        .subtitle { font-size: 14px; color: #666; margin-top: 4px; }

        .section {
            margin-bottom: 20px;
        }
        .section-title {
            font-size: 14px;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
        }
        .section-title::before {
            content: '';
            width: 4px;
            height: 16px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 2px;
            margin-right: 8px;
        }

        .profile-text {
            font-size: 15px;
            line-height: 1.8;
            color: #333;
            text-align: justify;
        }

        .tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .tag {
            background: linear-gradient(135deg, #667eea20 0%, #764ba220 100%);
            color: #667eea;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 13px;
        }

        .meta-info {
            font-size: 13px;
            color: #888;
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid #eee;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <div class="avatar">{{ avatar_emoji }}</div>
            <div class="title-group">
                <div class="title">{{ nickname }}</div>
                <div class="subtitle">用户ID: {{ user_id }}</div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">📝 画像描述</div>
            <div class="profile-text">{{ profile_text }}</div>
        </div>

        {% if traits %}
        <div class="section">
            <div class="section-title">🏷️ 性格特征</div>
            <div class="tags">
                {% for trait in traits %}
                <span class="tag">{{ trait }}</span>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% if interests %}
        <div class="section">
            <div class="section-title">💡 兴趣爱好</div>
            <div class="tags">
                {% for interest in interests %}
                <span class="tag">{{ interest }}</span>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% if speaking_style %}
        <div class="section">
            <div class="section-title">💬 说话风格</div>
            <div class="profile-text">{{ speaking_style }}</div>
        </div>
        {% endif %}

        {% if emotional_tendency %}
        <div class="section">
            <div class="section-title">❤️ 情感倾向</div>
            <div class="profile-text">{{ emotional_tendency }}</div>
        </div>
        {% endif %}

        <div class="meta-info">
            📊 已分析 {{ message_count }} 条消息 | ⏰ 最后更新: {{ last_updated }}
        </div>
    </div>
</body>
</html>
"""
