"""
Webhook 注册工具 — 用于 Vercel 部署后设置 Telegram Webhook
用法: python setup_webhook.py
"""
import os
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # 例如 https://xxx.vercel.app/api/bot
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

if not all([TOKEN, WEBHOOK_URL, WEBHOOK_SECRET]):
    print("❌ 请设置环境变量:")
    print("  TELEGRAM_BOT_TOKEN=xxx")
    print("  WEBHOOK_URL=https://你的域名.vercel.app/api/bot")
    print("  WEBHOOK_SECRET=随机字符串")
    exit(1)

url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
resp = requests.post(url, json={
    "url": WEBHOOK_URL,
    "secret_token": WEBHOOK_SECRET,
    "allowed_updates": ["message"],
})

print(f"状态码: {resp.status_code}")
print(f"响应: {resp.json()}")

# 验证 webhook 状态
info = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo")
print(f"\nWebhook 信息: {info.json()}")
