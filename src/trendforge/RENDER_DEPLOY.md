# TrendForge Render 部署指南（2分钟拿公网地址）

> 最低成本方案：Render 免费层 + 数据打包进镜像 + 4 个核心 API。
> 部署后任何人都能通过公网地址实时调用 /search /generate /workflow /stats。

## 前置准备

1. 把整个仓库推到 GitHub（仓库根目录需有 `render.yaml`，现已就位）
2. 注册 [Render](https://render.com)（免费账号即可，可用 GitHub 登录）
3. 准备好智谱 GLM API Key（`id.secret` 格式）

## 部署步骤

### 1. 创建 Blueprint
- Render 控制台 → **New** → **Blueprint**
- 选择你的 GitHub 仓库
- Render 会自动读取**仓库根目录**的 `render.yaml`，识别出 `trendforge-api` 服务

### 2. 填入 LLM Key
- 在环境变量中找到 `TF_GLM_API_KEY`，填入你的智谱 key
- 其余变量（`TF_LLM_VENDOR=glm`、`TF_LLM_MODEL=glm-5.2`）已由 render.yaml 预填

### 3. 等待构建（首次约 3-5 分钟）
- Render 拉 Docker 镜像 → 装依赖 → 预下载 embedding 模型 → 打包数据
- 构建日志会显示进度，看到 `Running...` 即部署成功

### 4. 拿到公网地址
- 部署完成后，Render 给你一个地址，形如：
  ```
  https://trendforge-api.onrender.com
  ```
- 这就是你的 **Realtime API** 公网入口

## 验证（部署后）

```bash
# 健康检查
curl https://trendforge-api.onrender.com/api/health

# ① 数据统计
curl https://trendforge-api.onrender.com/stats
# → {"news_documents":268,"news_chunks":877,"prompts":3,...}

# ② RAG 检索
curl -X POST https://trendforge-api.onrender.com/search \
  -H "Content-Type: application/json" \
  -d '{"query":"OpenAI GPT","top_k":5}'

# ③ 实时生成（8步Workflow，约60-120秒）
curl -X POST https://trendforge-api.onrender.com/generate \
  -H "Content-Type: application/json" \
  -d '{"topic":"OpenAI GPT-6 launch","country":"US"}'

# ④ Workflow 日志
curl -X POST https://trendforge-api.onrender.com/workflow \
  -H "Content-Type: application/json" \
  -d '{"topic":"AI芯片市场","country":"CN"}'

# Swagger 文档
open https://trendforge-api.onrender.com/docs
```

## 免费层限制与应对

| 限制 | 说明 | 应对 |
|------|------|------|
| 512MB 内存 | chroma+onnx+8步LLM 刚好够 | 已优化，单次生成无压力 |
| 15分钟休眠 | 无请求后休眠，冷启动~30s | 演示前先 curl 一下唤醒 |
| 无持久磁盘 | 重启不丢数据（数据打包在镜像里） | 想要每日增量采集升级付费层挂 disk |
| 数据静态 | 镜像里是部署时的 268 篇快照 | 重新部署会重新打包最新数据 |

## 为什么这样设计（产品视角）

- **/search**：证明 RAG 知识库真的能查
- **/generate**：证明 Multi-Agent Workflow 真的能跑出内容
- **/workflow**：证明 Agent 协作过程可观测（决策日志）
- **/stats**：证明数据是真实的，不是写死的

这 4 个接口让面试官从"静态 Demo"升级到"可信产品"的认知——**它真的会工作**。

## 接入前端门户

部署拿到地址后，在 `build/api.html` 的"连接后端"输入框填入该地址，门户的检索/生成按钮即调用真实服务。

## 升级到生产（可选）

想每日增量采集 + 数据持久增长，取消 render.yaml 注释的 disk 段，升级到 Starter 层（$7/月）：
```yaml
    plan: starter
    disk:
      name: trendforge-data
      mountPath: /app/data
      sizeGB: 1
```
