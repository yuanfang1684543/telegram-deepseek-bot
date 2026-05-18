"""
Telegram Bot 核心逻辑 — 对接 DashScope DeepSeek-V4-Pro
支持流式响应、重试机制、角色系统
"""
import os
import time
import logging
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── DashScope 客户端 ──────────────────────────────────────────────
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

# ── 角色预设 ──────────────────────────────────────────────────────
ROLES = {
    "default": "你是一个智能助手，运行在 Telegram 机器人中。请用简洁、友好的方式回答用户问题。支持中文和英文。",
    "coder": "你是一个资深编程专家。请用专业但易懂的方式解答编程问题，提供代码示例时使用 Markdown 代码块。偏好 Python/JavaScript/Go。",
    "translator": "你是一个专业翻译官。用户发送任何语言的内容，你都翻译成中文。如果是中文则翻译成英文。只输出翻译结果，不要额外解释。",
    "teacher": "你是一个耐心的老师。用通俗易懂的方式解释复杂概念，善用比喻和例子。适合各个年龄段的学习者。",
    "writer": "你是一个创意写手。帮助用户润色文字、撰写文章、创作故事。风格灵活多变，根据用户需求调整。",
    "analyst": "你是一个数据分析师。擅长解读数据、分析趋势、提供洞察。回答时注重逻辑和数据支撑。",
}


def get_system_prompt(role: str = "default", custom_prompt: str | None = None) -> str:
    """获取系统提示词"""
    if custom_prompt:
        return custom_prompt
    return ROLES.get(role, ROLES["default"])


# ── 重试装饰器 ────────────────────────────────────────────────────
async def chat_with_deepseek(
    user_message: str,
    history: list[dict] | None = None,
    system_prompt: str | None = None,
    temperature: float = 0.7,
    max_retries: int = 3,
) -> str:
    """调用 DashScope DeepSeek-V4-Pro 进行对话（带重试）"""
    if system_prompt is None:
        system_prompt = ROLES["default"]

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=messages,
                temperature=temperature,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = e
            logger.warning(f"API 调用失败 (第 {attempt + 1}/{max_retries} 次): {e}")
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                time.sleep(wait)

    logger.error(f"API 调用最终失败: {last_error}")
    return f"❌ AI 服务暂时不可用，已重试 {max_retries} 次。请稍后再试。"


# ── 流式响应 ──────────────────────────────────────────────────────
async def chat_stream(
    user_message: str,
    history: list[dict] | None = None,
    system_prompt: str | None = None,
    temperature: float = 0.7,
):
    """流式调用 DeepSeek，逐块 yield 文本"""
    if system_prompt is None:
        system_prompt = ROLES["default"]

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        stream = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            temperature=temperature,
            max_tokens=4096,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        logger.error(f"流式调用失败: {e}")
        yield f"\n\n❌ 流式响应中断: {str(e)[:100]}"
