"""
Polling 模式 — 适用于 Render / Railway 等长期运行平台
"""
import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from bot_core import chat_with_deepseek

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

user_history: dict[int, list[dict]] = {}
MAX_HISTORY = 20


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 你好！我是 DeepSeek-V4-Pro 助手。\n\n"
        "直接发送消息即可与我对话。\n"
        "/start - 开始对话\n"
        "/clear - 清除对话历史\n"
        "/help - 帮助信息"
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user_history.pop(uid, None)
    await update.message.reply_text("✅ 对话历史已清除。")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 DeepSeek-V4-Pro 助手\n\n"
        "• 直接发送消息开始对话\n"
        "• /clear 清除上下文\n"
        "• 支持多轮对话（自动记忆上下文）"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    text = update.message.text

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history = user_history.get(uid, [])
    reply = await chat_with_deepseek(text, history)

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    user_history[uid] = history

    if len(reply) > 4000:
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i + 4000])
    else:
        await update.message.reply_text(reply)


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot 启动中 (Polling 模式)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
