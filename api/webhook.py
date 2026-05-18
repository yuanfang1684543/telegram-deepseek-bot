"""
Webhook 模式 — 适用于 Vercel Serverless Functions
"""
import os
import json
import logging
from http.server import BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from bot_core import chat_with_deepseek

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", os.urandom(16).hex())

# 用户对话历史（内存存储，适合轻量使用）
user_history: dict[int, list[dict]] = {}
MAX_HISTORY = 20


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 你好！我是 DeepSeek-V4-Pro 助手。\n\n"
        "直接发送消息即可与我对话。\n"
        "支持命令:\n"
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

    # 发送"正在输入"状态
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # 获取历史
    history = user_history.get(uid, [])

    # 调用 AI
    reply = await chat_with_deepseek(text, history)

    # 保存历史
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    user_history[uid] = history

    # 分段发送长消息
    if len(reply) > 4000:
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i + 4000])
    else:
        await update.message.reply_text(reply)


# ── 构建 Application ──────────────────────────────────────────────
_app: Application | None = None


def get_app() -> Application:
    global _app
    if _app is None:
        _app = Application.builder().token(TELEGRAM_TOKEN).build()
        _app.add_handler(CommandHandler("start", start))
        _app.add_handler(CommandHandler("clear", clear_history))
        _app.add_handler(CommandHandler("help", help_cmd))
        _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return _app


# ── Vercel Serverless Handler ─────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    """Vercel Python 运行时使用的 HTTP Handler"""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # 验证 webhook secret
        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret != WEBHOOK_SECRET:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden")
            return

        try:
            data = json.loads(body)
            update = Update.de_json(data, get_app().bot)

            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(get_app().process_update(update))
            loop.close()

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except Exception as e:
            logger.error(f"处理更新失败: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")


# ── 本地开发 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    from http.server import HTTPServer
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), handler)
    logger.info(f"Webhook server running on port {port}")
    server.serve_forever()
