# TrendForge 后端部署指南

TrendForge 是一个 **FastAPI + SQLite + Chroma** 的 Python 后端，`python main.py serve` 即可本地运行。
要让**公网其他人也能调用**，选下面任一方案。推荐 **Render**（最简单，免费层够演示）。

> ⚠️ 重要：WorkBuddy 自带的 CloudStudio 部署工具**只能托管静态文件**（静态文件服务器），
> 跑不了 Python 后端进程。所以后端必须部署到能跑 Python 的云平台，CloudStudio 只用于部署前端控制台。

---

## 方案 A：Render（推荐，5 分钟，免费层）

1. 把 `src/trendforge/` 整个目录推到 GitHub 仓库
2. 登录 https://render.com → New → **Blueprint**
3. 选你的仓库，Render 会自动识别 `render.yaml`
4. 在环境变量里填至少一家 LLM key（如 `TF_OPENAI_API_KEY=sk-xxx`）
5. 点 Create → 等 2-3 分钟构建完成 → 拿到 `https://trendforge-api.onrender.com`
6. 访问 `https://trendforge-api.onrender.com/docs` 即 Swagger 文档

**特点**：免费层 512MB 内存，15 分钟无请求自动休眠（首次唤醒约 30 秒）。数据每次部署重新 seed（演示够用）。

---

## 方案 B：Fly.io（全球节点，免费额度）

```bash
# 安装 flyctl 后
cd src/trendforge
fly launch          # 首次：选区域、确认配置
fly secrets set TF_OPENAI_API_KEY=sk-xxx
fly secrets set TF_LLM_VENDOR=openai
fly deploy
# 得到 https://trendforge-api.fly.dev
```

**特点**：香港/东京节点国内访问快，支持持久卷（数据不丢），免费额度够个人用。

---

## 方案 C：任意云主机 + Docker（自托管）

```bash
# 把 src/trendforge 上传到服务器，然后：
cd src/trendforge
cp .env.example .env       # 编辑填入 LLM key
docker compose up -d       # 后台启动
# 访问 http://你的服务器IP:8000/docs
```

**特点**：完全可控，数据持久化（`./data` 卷），适合生产。需自行配置域名 + HTTPS（用 Caddy/Nginx 反代）。

---

## 方案 D：ngrok 内网穿透（临时演示，秒开）

本地已跑 `uvicorn` 时，另开终端：

```bash
ngrok http 8000
# 得到 https://xxxx.ngrok-free.app → 直接分享给别人
```

**特点**：60 秒拿到公网地址，但**你的电脑必须开机且服务在跑**，关机即失效。适合给朋友演示。

---

## 环境变量速查

| 变量 | 必填 | 说明 |
|---|---|---|
| `TF_LLM_VENDOR` | 是 | `openai`/`anthropic`/`deepseek`/`kimi`/`qwen`/`glm` 之一 |
| `TF_<VENDOR>_API_KEY` | 是 | 对应厂商的 key，如 `TF_OPENAI_API_KEY`（6 家可同时配） |
| `TF_LLM_MODEL` | 否 | 覆盖厂商默认模型 |
| `TF_EMBEDDING_API_KEY` | 否 | 配置则用云端 embedding；不配用本地 MiniLM（零配置） |
| `PORT` | 自动 | 云平台自动注入，无需手动设 |

**不配 LLM key 也能用**：RAG 检索、数据分析、Prompt 管理、A/B 实验、API 文档全部可用。
只有 `POST /api/content/run-topic`（内容生产）需要 key。

---

## 部署后验证

```bash
# 替换 URL 为你的部署地址
export API=https://trendforge-api.onrender.com
curl $API/api/health                          # 健康检查
curl $API/api/llm/vendors                     # 查看已配置的 LLM 厂商
curl "$API/api/llm/test?vendor=openai"        # 测试厂商连通性
curl "$API/api/rag/search?q=GPT-6&top_k=3"    # RAG 检索
curl "$API/api/analytics/funnel"              # 数据看板
```
