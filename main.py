"""
Polling 模式 — 升级版 Telegram Bot
新增：流式响应 · Markdown 格式化 · 角色系统 · 群聊支持 · Inline Query
"""
import os
import re
import logging
import html
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, InlineQueryHandler,
)

from bot_core import chat_with_deepseek, chat_stream, ROLES, get_system_prompt

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")  # 用于群聊 @提及 检测

# ── 用户状态 ──────────────────────────────────────────────────────
user_history: dict[int, list[dict]] = {}
user_roles: dict[int, str] = {}        # 用户角色
user_temps: dict[int, float] = {}      # 用户温度参数
MAX_HISTORY = 20


def escape_md(text: str) -> str:
    """转义 MarkdownV2 特殊字符"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


def format_code_blocks(text: str) -> str:
    """将 Markdown 代码块转为 Telegram MarkdownV2 兼容格式"""
    # 将 ```language\n...\n``` 转为 ```\n...\n```
    text = re.sub(r'```(\w+)\n', r'```\n', text)
    return text


# ── 命令处理 ──────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user_roles.setdefault(uid, "default")
    user_temps.setdefault(uid, 0.7)

    welcome = (
        "👋 *你好！我是 DeepSeek\\-V4\\-Pro 助手*\n\n"
        "💬 直接发消息即可对话\n"
        "🔄 支持*流式响应*，边想边回\n"
        "🧠 自动记忆上下文 \\(最近 20 轮\\)\n\n"
        "*命令列表：*\n"
        "/role \\- 切换角色\n"
        "/temp \\- 调整创意度\n"
        "/clear \\- 清除记忆\n"
        "/export \\- 导出对话\n"
        "/help \\- 帮助"
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN_V2)


async def role_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换角色或查看可选角色"""
    uid = update.effective_user.id
    args = context.args

    if not args:
        role_list = "\n".join(
            f"• `{k}` \\- {v[:40]}..." for k, v in ROLES.items()
        )
        current = user_roles.get(uid, "default")
        await update.message.reply_text(
            f"🎭 *当前角色：* `{current}`\n\n"
            f"*可选角色：*\n{role_list}\n\n"
            f"用法： `/role 角色名`\n"
            f"自定义： `/role custom 你的提示词`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    role_name = args[0].lower()

    if role_name == "custom" and len(args) > 1:
        custom_prompt = " ".join(args[1:])
        user_roles[uid] = f"custom:{custom_prompt}"
        await update.message.reply_text(
            f"✅ 已设置*自定义角色*\n提示词： _{escape_md(custom_prompt[:200])}_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    elif role_name in ROLES:
        user_roles[uid] = role_name
        await update.message.reply_text(
            f"✅ 角色切换为： *{role_name}*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        await update.message.reply_text(
            f"❌ 未知角色 `{escape_md(role_name)}`\n"
            f"输入 `/role` 查看可选角色",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def temp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """调整 temperature 参数"""
    uid = update.effective_user.id
    args = context.args
    current = user_temps.get(uid, 0.7)

    if not args:
        await update.message.reply_text(
            f"🌡 *当前创意度：* `{current}`\n\n"
            f"范围： `0.0` \\(严谨\\) ~ `2.0` \\(天马行空\\)\n"
            f"推荐： `0.3` 代码 | `0.7` 通用 | `1.2` 创意\n\n"
            f"用法： `/temp 0.8`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        val = float(args[0])
        val = max(0.0, min(2.0, val))
        user_temps[uid] = val
        desc = "严谨模式 🔒" if val < 0.4 else ("创意模式 🎨" if val > 1.0 else "平衡模式 ⚖️")
        await update.message.reply_text(
            f"✅ 创意度设为： *{val}*  {desc}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except ValueError:
        await update.message.reply_text("❌ 请输入有效数字，如 `/temp 0.8`")


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user_history.pop(uid, None)
    await update.message.reply_text("✅ 对话历史已清除。")


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """导出对话历史"""
    uid = update.effective_user.id
    history = user_history.get(uid, [])

    if not history:
        await update.message.reply_text("📭 暂无对话历史可导出。")
        return

    lines = ["📝 *对话导出*", ""]
    for i in range(0, len(history), 2):
        q = history[i]["content"] if i < len(history) else ""
        a = history[i + 1]["content"] if i + 1 < len(history) else ""
        lines.append(f"*Q{i // 2 + 1}:* {escape_md(q[:100])}")
        lines.append(f"*A{i // 2 + 1}:* {escape_md(a[:100])}")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n\\.\\.\\.\\(内容过长已截断\\)"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "*🤖 DeepSeek\\-V4\\-Pro 助手*\n\n"
        "*💡 核心功能：*\n"
        "• 智能对话 \\- 直接发消息\n"
        "• 流式响应 \\- 边想边回\n"
        "• 多轮记忆 \\- 自动上下文\n\n"
        "*🎭 角色系统：*\n"
        "`/role` \\- 查看/切换角色\n"
        "`/role coder` \\- 编程专家\n"
        "`/role teacher` \\- 耐心老师\n"
        "`/role writer` \\- 创意写手\n"
        "`/role custom 描述` \\- 自定义\n\n"
        "*⚙️ 参数调节：*\n"
        "`/temp 0.3` \\- 严谨模式\n"
        "`/temp 1.2` \\- 创意模式\n\n"
        "*📋 其他：*\n"
        "`/clear` \\- 清除记忆\n"
        "`/export` \\- 导出对话\n\n"
        "*👥 群聊用法：*\n"
        "• @机器人 提问\n"
        "• 回复机器人消息继续对话"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)


# ── 消息处理 ──────────────────────────────────────────────────────

def should_respond(update: Update) -> bool:
    """判断是否应该回复（群聊中需要 @提及 或回复机器人）"""
    if update.effective_chat.type == "private":
        return True

    # 群聊：检查是否 @了机器人 或 回复了机器人消息
    text = update.message.text or update.message.caption or ""
    if f"@{BOT_USERNAME}" in text:
        return True

    # 检查是否回复了机器人的消息
    if update.message.reply_to_message:
        if update.message.reply_to_message.from_user.username == BOT_USERNAME.strip("@"):
            return True

    return False


def clean_mention(text: str) -> str:
    """移除 @机器人 提及"""
    if BOT_USERNAME:
        text = re.sub(rf'@{re.escape(BOT_USERNAME)}\s*', '', text).strip()
    return text


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户消息 — 流式响应版"""
    uid = update.effective_user.id
    text = update.message.text or update.message.caption or ""

    # 群聊判断
    if not should_respond(update):
        return

    text = clean_mention(text)
    if not text:
        return

    # 发送 typing 状态
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # 获取用户配置
    history = user_history.get(uid, [])
    role_key = user_roles.get(uid, "default")
    temperature = user_temps.get(uid, 0.7)

    # 构建 system prompt
    if role_key.startswith("custom:"):
        system_prompt = role_key[7:]
    else:
        system_prompt = get_system_prompt(role_key)

    # ── 流式响应 ──────────────────────────────────────────────
    sent_msg = await update.message.reply_text("🤔 *思考中...*", parse_mode=ParseMode.MARKDOWN_V2)

    full_reply = ""
    last_update = 0
    chunk_buffer = ""

    async for chunk in chat_stream(text, history, system_prompt, temperature):
        chunk_buffer += chunk
        full_reply += chunk

        # 每积累 30 字符或 0.8 秒更新一次消息
        now = __import__("time").time()
        if len(chunk_buffer) >= 30 or (now - last_update > 0.8 and chunk_buffer):
            try:
                display = format_code_blocks(full_reply + " ▌")
                await sent_msg.edit_text(
                    display,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception:
                # Markdown 解析失败时用纯文本
                try:
                    await sent_msg.edit_text(full_reply + " ▌")
                except Exception:
                    pass
            chunk_buffer = ""
            last_update = now

    # ── 最终消息 ──────────────────────────────────────────────
    try:
        final = format_code_blocks(full_reply)
        await sent_msg.edit_text(final, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception:
        try:
            await sent_msg.edit_text(full_reply)
        except Exception:
            # 编辑失败则发送新消息
            await sent_msg.delete()
            await update.message.reply_text(full_reply)

    # 保存历史
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": full_reply})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    user_history[uid] = history


# ── Inline Query ──────────────────────────────────────────────────

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理内联查询 — 在任何聊天中输入 @bot 关键词"""
    query = update.inline_query.query.strip()
    if not query:
        return

    uid = update.inline_query.from_user.id
    history = user_history.get(uid, [])
    role_key = user_roles.get(uid, "default")
    temperature = user_temps.get(uid, 0.7)

    if role_key.startswith("custom:"):
        system_prompt = role_key[7:]
    else:
        system_prompt = get_system_prompt(role_key)

    reply = await chat_with_deepseek(query, history, system_prompt, temperature)

    results = [
        InlineQueryResultArticle(
            id="1",
            title=f"🤖 {reply[:60]}..." if len(reply) > 60 else f"🤖 {reply[:60]}",
            description=reply[:120],
            input_message_content=InputTextMessageContent(
                message_text=f"*Q:* {escape_md(query)}\n\n*A:* {escape_md(reply)}",
                parse_mode=ParseMode.MARKDOWN_V2,
            ),
            thumb_url="https://img.icons8.com/color/96/artificial-intelligence.png",
        )
    ]

    await update.inline_query.answer(results, cache_time=10)


# ── 错误处理 ──────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"异常: {context.error} | update: {update}")


# ── 启动 ──────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # 命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("role", role_cmd))
    app.add_handler(CommandHandler("temp", temp_cmd))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(CommandHandler("export", export_cmd))

    # 消息（支持文本和 caption）
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
        handle_message,
    ))

    # Inline Query
    app.add_handler(InlineQueryHandler(inline_query))

    # 错误处理
    app.add_error_handler(error_handler)

    logger.info("🤖 Bot 启动中 (Polling 模式 - 升级版)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
