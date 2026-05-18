"""
最简版 Bot — 用于验证 Railway 部署
"""
import os
import sys
import logging

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# 启动日志
logger.info("=" * 50)
logger.info("Bot 启动中...")
logger.info(f"Python: {sys.version}")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("DASHSCOPE_API_KEY")
USERNAME = os.getenv("BOT_USERNAME")

logger.info(f"TOKEN 存在: {bool(TOKEN)}, 长度: {len(TOKEN) if TOKEN else 0}")
logger.info(f"API_KEY 存在: {bool(API_KEY)}, 长度: {len(API_KEY) if API_KEY else 0}")
logger.info(f"USERNAME: {USERNAME}")

if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN 未设置！")
    sys.exit(1)

# 测试 Telegram API
import requests
resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe")
logger.info(f"Telegram getMe: {resp.json()}")

# 测试 DashScope API
from openai import OpenAI
client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)
try:
    r = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[{"role": "user", "content": "说你好"}],
        max_tokens=50,
    )
    logger.info(f"DashScope 测试: {r.choices[0].message.content}")
except Exception as e:
    logger.error(f"DashScope 测试失败: {e}")

# 启动 Bot
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot 运行正常！")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        r = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": text}],
            max_tokens=2000,
        )
        reply = r.choices[0].message.content
    except Exception as e:
        reply = f"错误: {e}"
    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    logger.info("🤖 开始 Polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
