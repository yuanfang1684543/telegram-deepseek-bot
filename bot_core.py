"""
Telegram Bot 核心逻辑 — 对接 DashScope DeepSeek-V4-Pro
"""
import os
import logging
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── DashScope 客户端 ──────────────────────────────────────────────
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

SYSTEM_PROMPT = """你是一个智能助手，运行在 Telegram 机器人中。
请用简洁、友好的方式回答用户问题。支持中文和英文。"""


async def chat_with_deepseek(user_message: str, history: list[dict] | None = None) -> str:
    """调用 DashScope DeepSeek-V4-Pro 进行对话"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            temperature=0.7,
            max_tokens=4096,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DashScope API 调用失败: {e}")
        return f"抱歉，AI 服务暂时不可用，请稍后再试。\n\n错误信息: {str(e)[:200]}"
