FROM python:3.12-slim

# 系统依赖（chromadb onnxruntime 需要编译工具链 + libgomp）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 预下载 chromadb 默认 embedding 模型(all-MiniLM-L6-v2 onnx)，避免启动时下载
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction; DefaultEmbeddingFunction()(['warmup'])" \
    || echo "model prefetch skipped"

# 拷贝应用代码 + 已打包的数据(243篇新闻+chroma向量，让 /search /stats 立即可用)
COPY . .

# 确保数据目录存在
RUN mkdir -p data/chroma prompt_templates

ENV TF_HOST=0.0.0.0 \
    TF_PORT=8000 \
    TF_DEBUG=false \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# 启动：init_db(幂等建表+迁移) 后起服务。数据已打包，不再 seed 采集
CMD ["sh", "-c", "python -c \"import asyncio;from db import init_db;asyncio.run(init_db())\" && uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
