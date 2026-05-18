"""
Webhook 模式 — 升级版（适用于 Vercel Serverless Functions）
新增：角色系统 · 群聊支持 · Inline Query · 流式响应
"""
import os
import re
import json
import time
import logging
from http.server import BaseHTTPRequestHandler
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, InlineQueryHandler,
)

from bot_core import chat_with_deepseek, chat_stream, ROLES, get_system_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", os.urandom(16).hex())

user_history: dict[int, list[dict]] = {}
user_roles: dict[int, str] = {}
user_temps: dict[int, float] = {}
MAX_HISTORY = 20


def escape_md(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


def format_code_blocks(text: str) -> str:
    text = re.sub(r'```(\w+)\n', r'```\n', text)
    return text


def should_respond(update: Update) -> bool:
    if update.effective_chat.type == "private":
        return True
    text = update.message.text or update.message.caption or ""
    if f"@{BOT_USERNAME}" in text:
        return True
    if update.message.reply_to_message:
        if update.message.reply_to_message.from_user.username == BOT_USERNAME.strip("@"):
            return True
    return False


def clean_mention(text: str) -> str:
    if BOT_USERNAME:
        text = re.sub(rf'@{re.escape(BOT_USERNAME)}\s*', '', text).strip()
    return text


# ── Handlers ──────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user_roles.setdefault(uid, "default")
    user_temps.setdefault(uid, 0.7)
    await update.message.reply_text(
        "👋 *你好！我是 DeepSeek\\-V4\\-Pro 助手*\n\n"
        "💬 直接发消息即可对话\n"
        "🔄 支持*流式响应*\n"
        "🧠 自动记忆上下文\n\n"
        "/role \\- 切换角色\n/temp \\- 调整创意度\n"
        "/clear \\- 清除记忆\n/help \\- 帮助",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def role_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    args = context.args
    if not args:
        role_list = "\n".join(f"• `{k}`" for k in ROLES)
        current = user_roles.get(uid, "default")
        await update.message.reply_text(
            f"🎭 *当前角色：* `{current}`\n\n*可选：*\n{role_list}\n\n`/role 角色名`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    role_name = args[0].lower()
    if role_name == "custom" and len(args) > 1:
        custom_prompt = " ".join(args[1:])
        user_roles[uid] = f"custom:{custom_prompt}"
        await update.message.reply_text(f"✅ 已设置*自定义角色*", parse_mode=ParseMode.MARKDOWN_V2)
    elif role_name in ROLES:
        user_roles[uid] = role_name
        await update.message.reply_text(f"✅ 角色切换为： *{role_name}*", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text(f"❌ 未知角色 `{escape_md(role_name)}`", parse_mode=ParseMode.MARKDOWN_V2)


async def temp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    args = context.args
    current = user_temps.get(uid, 0.7)
    if not args:
        await update.message.reply_text(
            f"🌡 *当前创意度：* `{current}`\n范围 `0.0`~`2.0`\n用法： `/temp 0.8`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    try:
        val = max(0.0, min(2.0, float(args[0])))
        user_temps[uid] = val
        await update.message.reply_text(f"✅ 创意度设为： *{val}*", parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await update.message.reply_text("❌ 请输入有效数字")


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user_history.pop(uid, None)
    await update.message.reply_text("✅ 对话历史已清除。")


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    history = user_history.get(uid, [])
    if not history:
        await update.message.reply_text("📭 暂无对话历史。")
        return
    lines = ["📝 *对话导出*", ""]
    for i in range(0, len(history), 2):
        q = history[i]["content"] if i < len(history) else ""
        a = history[i + 1]["content"] if i + 1 < len(history) else ""
        lines.append(f"*Q{i // 2 + 1}:* {escape_md(q[:80])}")
        lines.append(f"*A{i // 2 + 1}:* {escape_md(a[:80])}")
        lines.append("")
    text = "\n".join(lines)[:4000]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*🤖 DeepSeek\\-V4\\-Pro 助手*\n\n"
        "`/role` \\- 切换角色\n`/temp` \\- 调整创意度\n"
        "`/clear` \\- 清除记忆\n`/export` \\- 导出对话\n\n"
        "*群聊：* @机器人 提问",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    text = update.message.text or update.message.caption or ""
    if not should_respond(update):
        return
    text = clean_mention(text)
    if not text:
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history = user_history.get(uid, [])
    role_key = user_roles.get(uid, "default")
    temperature = user_temps.get(uid, 0.7)
    system_prompt = role_key[7:] if role_key.startswith("custom:") else get_system_prompt(role_key)

    # 流式响应
    sent_msg = await update.message.reply_text("🤔 *思考中...*", parse_mode=ParseMode.MARKDOWN_V2)
    full_reply = ""
    last_update = 0
    chunk_buffer = ""

    async for chunk in chat_stream(text, history, system_prompt, temperature):
        chunk_buffer += chunk
        full_reply += chunk
        now = time.time()
        if len(chunk_buffer) >= 30 or (now - last_update > 0.8 and chunk_buffer):
            try:
                await sent_msg.edit_text(format_code_blocks(full_reply + " ▌"), parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                try:
                    await sent_msg.edit_text(full_reply + " ▌")
                except Exception:
                    pass
            chunk_buffer = ""
            last_update = now

    try:
        await sent_msg.edit_text(format_code_blocks(full_reply), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception:
        try:
            await sent_msg.edit_text(full_reply)
        except Exception:
            await sent_msg.delete()
            await update.message.reply_text(full_reply)

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": full_reply})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    user_history[uid] = history


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query.query.strip()
    if not query:
        return
    uid = update.inline_query.from_user.id
    history = user_history.get(uid, [])
    role_key = user_roles.get(uid, "default")
    temperature = user_temps.get(uid, 0.7)
    system_prompt = role_key[7:] if role_key.startswith("custom:") else get_system_prompt(role_key)
    reply = await chat_with_deepseek(query, history, system_prompt, temperature)
    results = [
        InlineQueryResultArticle(
            id="1", title=f"🤖 {reply[:60]}",
            description=reply[:120],
            input_message_content=InputTextMessageContent(
                message_text=f"*Q:* {escape_md(query)}\n\n*A:* {escape_md(reply)}",
                parse_mode=ParseMode.MARKDOWN_V2,
            ),
        )
    ]
    await update.inline_query.answer(results, cache_time=10)


# ── App 构建 ──────────────────────────────────────────────────────
_app: Application | None = None


def get_app() -> Application:
    global _app
    if _app is None:
        _app = Application.builder().token(TELEGRAM_TOKEN).build()
        _app.add_handler(CommandHandler("start", start))
        _app.add_handler(CommandHandler("help", help_cmd))
        _app.add_handler(CommandHandler("role", role_cmd))
        _app.add_handler(CommandHandler("temp", temp_cmd))
        _app.add_handler(CommandHandler("clear", clear_history))
        _app.add_handler(CommandHandler("export", export_cmd))
        _app.add_handler(MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND, handle_message))
        _app.add_handler(InlineQueryHandler(inline_query))
    return _app


# ── HTTP Handler ──────────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
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
            logger.error(f"处理失败: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")


if __name__ == "__main__":
    from http.server import HTTPServer
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), handler)
    logger.info(f"Webhook server running on port {port}")
    server.serve_forever()
