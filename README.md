# 🤖 Telegram DeepSeek-V4-Pro 机器人

基于 Telegram Bot API + DashScope DeepSeek-V4-Pro 的智能聊天机器人，支持多轮对话。

## 架构

```
用户 → Telegram → Bot (Webhook/Polling) → DashScope API (DeepSeek-V4-Pro)
```

## 功能

- 💬 智能对话（DeepSeek-V4-Pro）
- 🧠 多轮对话上下文记忆
- 📝 支持 `/start` `/clear` `/help` 命令
- 🌐 支持中文和英文

## 快速开始

### 1. 获取必要 Token

| 项目 | 获取方式 |
|------|---------|
| `TELEGRAM_BOT_TOKEN` | 在 Telegram 找 [@BotFather](https://t.me/BotFather) 创建机器人 |
| `DASHSCOPE_API_KEY` | [阿里云 DashScope 控制台](https://dashscope-intl.aliyuncs.com/) → API-KEY 管理 |

### 2. 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实 Token

# 运行（Polling 模式）
python main.py
```

### 3. 部署到免费平台

#### 方案 A：Render（推荐，最简单）

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com)

1. Fork 本项目到 GitHub
2. 在 Render 创建新的 Web Service，连接仓库
3. 设置环境变量 `TELEGRAM_BOT_TOKEN` 和 `DASHSCOPE_API_KEY`
4. Render 会自动使用 `render.yaml` 配置

#### 方案 B：Railway

```bash
# 安装 Railway CLI
npm i -g @railway/cli

# 部署
railway login
railway init
railway up

# 设置环境变量
railway variables set TELEGRAM_BOT_TOKEN=xxx
railway variables set DASHSCOPE_API_KEY=xxx
```

#### 方案 C：Vercel（Webhook 模式）

1. 在 Vercel 导入项目
2. 设置环境变量：
   - `TELEGRAM_BOT_TOKEN`
   - `DASHSCOPE_API_KEY`
   - `WEBHOOK_SECRET`（随机字符串）
3. 部署后，设置 Telegram Webhook：

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://你的域名.vercel.app/api/bot&secret_token=你的WEBHOOK_SECRET"
```

## 项目结构

```
telegram-deepseek-bot/
├── bot_core.py          # 核心逻辑（DashScope API 调用）
├── main.py              # Polling 模式入口（Render/Railway）
├── api/
│   └── webhook.py       # Webhook 模式入口（Vercel）
├── requirements.txt     # Python 依赖
├── Procfile             # Heroku/Render 进程配置
├── render.yaml          # Render Blueprint 配置
├── vercel.json          # Vercel 部署配置
└── .env.example         # 环境变量模板
```

## API 端点

- **Base URL**: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
- **Model**: `deepseek-v4-pro`
- **协议**: OpenAI 兼容接口
