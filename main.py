"""
Polling 模式 — 完整版 Telegram Bot
流式响应 · Markdown · 角色系统 · 群聊 · Inline Query · 重试
"""
import os
import re
import sys
import time
import logging
import requests
from openai import OpenAI
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, InlineQueryHandler,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── 启动诊断 ──────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("DASHSCOPE_API_KEY")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

logger.info(f"Python {sys.version}")
logger.info(f"TOKEN: {'✅' if TOKEN else '❌ 缺失'}")
logger.info(f"API_KEY: {'✅' if API_KEY else '❌ 缺失'}")
logger.info(f"USERNAME: {BOT_USERNAME or '❌ 缺失'}")

if not TOKEN or not API_KEY:
    logger.error("缺少必要环境变量，退出")
    sys.exit(1)

# ── DashScope 客户端 ──────────────────────────────────────────────
client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

ROLES = {
    "default": "你是一个智能助手，运行在 Telegram 中。请用简洁友好的方式回答。支持中英文。",
    "coder": "你是资深编程专家。用专业易懂的方式解答，提供代码示例时使用 ```语言 标记。",
    "translator": "你是专业翻译官。用户发任何语言都翻译成中文，中文则翻译成英文。只输出翻译结果。",
    "teacher": "你是耐心老师。用通俗方式解释复杂概念，善用比喻。适合各年龄段。",
    "writer": "你是创意写手。帮用户润色文字、撰写文章、创作故事。风格灵活。",
    "analyst": "你是数据分析师。擅长解读数据、分析趋势。注重逻辑和数据支撑。",
}

user_history: dict[int, list[dict]] = {}
user_roles: dict[int, str] = {}
user_temps: dict[int, float] = {}
MAX_HISTORY = 20


def escape_md(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)


def format_code_blocks(text: str) -> str:
    return re.sub(r'```(\w+)\n', r'```\n', text)


def should_respond(update: Update) -> bool:
    if update.effective_chat.type == "private":
        return True
    text = update.message.text or update.message.caption or ""
    if BOT_USERNAME and f"@{BOT_USERNAME}" in text:
        return True
    if update.message.reply_to_message:
        ru = update.message.reply_to_message.from_user
        if ru and ru.username == BOT_USERNAME:
            return True
    return False


def clean_mention(text: str) -> str:
    if BOT_USERNAME:
        return re.sub(rf'@{re.escape(BOT_USERNAME)}\s*', '', text).strip()
    return text


# ── 命令 ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_roles.setdefault(uid, "default")
    user_temps.setdefault(uid, 0.7)
    await update.message.reply_text(
        "👋 *你好！DeepSeek\\-V4\\-Pro 助手*\n\n"
        "💬 直接发消息对话\n🔄 流式响应\n🧠 自动记忆上下文\n\n"
        "`/role` 切换角色\n`/temp` 创意度\n`/clear` 清除记忆\n`/help` 帮助",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def role_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if not args:
        rl = "\n".join(f"• `{k}` \\- {v[:30]}..." for k, v in ROLES.items())
        cur = user_roles.get(uid, "default")
        await update.message.reply_text(
            f"🎭 *当前：* `{cur}`\n\n*可选：*\n{rl}\n\n`/role 角色名`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    name = args[0].lower()
    if name == "custom" and len(args) > 1:
        user_roles[uid] = f"custom:{' '.join(args[1:])}"
        await update.message.reply_text("✅ 已设置自定义角色", parse_mode=ParseMode.MARKDOWN_V2)
    elif name in ROLES:
        user_roles[uid] = name
        await update.message.reply_text(f"✅ 角色： *{name}*", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text(f"❌ 未知角色 `{escape_md(name)}`", parse_mode=ParseMode.MARKDOWN_V2)


async def temp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    cur = user_temps.get(uid, 0.7)
    if not args:
        await update.message.reply_text(
            f"🌡 *当前：* `{cur}`\n范围 `0.0`~`2.0`\n`/temp 0.8`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    try:
        v = max(0.0, min(2.0, float(args[0])))
        user_temps[uid] = v
        await update.message.reply_text(f"✅ 创意度： *{v}*", parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await update.message.reply_text("❌ 请输入数字")


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_history.pop(update.effective_user.id, None)
    await update.message.reply_text("✅ 对话历史已清除。")


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    h = user_history.get(uid, [])
    if not h:
        await update.message.reply_text("📭 暂无对话历史。")
        return
    lines = ["📝 *对话导出*\n"]
    for i in range(0, len(h), 2):
        q = h[i]["content"] if i < len(h) else ""
        a = h[i + 1]["content"] if i + 1 < len(h) else ""
        lines.append(f"*Q{i // 2 + 1}:* {escape_md(q[:80])}")
        lines.append(f"*A{i // 2 + 1}:* {escape_md(a[:80])}")
    await update.message.reply_text("\n".join(lines)[:4000], parse_mode=ParseMode.MARKDOWN_V2)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*🤖 DeepSeek\\-V4\\-Pro*\n\n"
        "🎭 `/role` 角色\n🌡 `/temp` 创意度\n"
        "🧹 `/clear` 清除记忆\n📤 `/export` 导出\n\n"
        "👥 群聊： @机器人 提问",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── 消息处理（流式） ──────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    system_prompt = role_key[7:] if role_key.startswith("custom:") else ROLES.get(role_key, ROLES["default"])

    # 流式响应
    sent_msg = await update.message.reply_text("🤔 *思考中...*", parse_mode=ParseMode.MARKDOWN_V2)
    full_reply = ""
    last_update = 0
    chunk_buf = ""

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": text})

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
                c = chunk.choices[0].delta.content
                chunk_buf += c
                full_reply += c
                now = time.time()
                if len(chunk_buf) >= 30 or (now - last_update > 0.8 and chunk_buf):
                    try:
                        await sent_msg.edit_text(
                            format_code_blocks(full_reply + " ▌"),
                            parse_mode=ParseMode.MARKDOWN_V2,
                        )
                    except Exception:
                        try:
                            await sent_msg.edit_text(full_reply + " ▌")
                        except Exception:
                            pass
                    chunk_buf = ""
                    last_update = now
    except Exception as e:
        logger.error(f"流式调用失败: {e}")
        full_reply = f"❌ AI 服务异常: {str(e)[:200]}"

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


# ── Inline Query ──────────────────────────────────────────────────

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query:
        return
    uid = update.inline_query.from_user.id
    history = user_history.get(uid, [])
    role_key = user_roles.get(uid, "default")
    temperature = user_temps.get(uid, 0.7)
    sp = role_key[7:] if role_key.startswith("custom:") else ROLES.get(role_key, ROLES["default"])

    msgs = [{"role": "system", "content": sp}]
    if history:
        msgs.extend(history)
    msgs.append({"role": "user", "content": query})

    try:
        r = client.chat.completions.create(model="deepseek-v4-pro", messages=msgs, temperature=temperature, max_tokens=2000)
        reply = r.choices[0].message.content
    except Exception as e:
        reply = f"错误: {e}"

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


# ── 启动 ──────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("role", role_cmd))
    app.add_handler(CommandHandler("temp", temp_cmd))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, handle_message))
    app.add_handler(InlineQueryHandler(inline_query))

    logger.info("🤖 Bot 启动 (完整版)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
