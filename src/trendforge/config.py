"""TrendForge 全局配置 — 通过环境变量 / .env 配置"""
from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# ============ 支持的 LLM 厂商注册表 ============
# kind: "openai" = OpenAI 兼容接口（/chat/completions）；"anthropic" = 原生 Messages API
VENDOR_DEFAULTS: dict[str, dict] = {
    "openai":    {"kind": "openai",    "base_url": "https://api.openai.com/v1",                        "default_model": "gpt-4o-mini",               "label": "OpenAI"},
    "anthropic": {"kind": "anthropic", "base_url": "https://api.anthropic.com",                        "default_model": "claude-3-5-haiku-20241022",  "label": "Anthropic Claude"},
    "deepseek":  {"kind": "openai",    "base_url": "https://api.deepseek.com/v1",                       "default_model": "deepseek-chat",             "label": "DeepSeek 深度求索"},
    "kimi":      {"kind": "openai",    "base_url": "https://api.moonshot.cn/v1",                        "default_model": "moonshot-v1-8k",            "label": "Kimi 月之暗面"},
    "qwen":      {"kind": "openai",    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus",                 "label": "Qwen 通义千问"},
    "glm":       {"kind": "openai",    "base_url": "https://open.bigmodel.cn/api/paas/v4",              "default_model": "glm-4.7-flash",             "label": "GLM 智谱清言"},
}

# ============ 可信新闻源 RSS 注册表 ============
# 字段: feed_url, source_name, category(tech/finance/world), country, language,
#       credibility_level(1=权威官方 2=权威媒体 3=一般), source_type
# 采集器按此表拉取；单个 feed 失败自动跳过
RSS_SOURCES: list[dict] = [
    # ---- AI 官方博客 ----
    {"feed_url": "https://openai.com/blog/rss.xml", "source_name": "OpenAI Blog",
     "category": "tech", "country": "US", "language": "en", "credibility_level": 1, "source_type": "official"},
    {"feed_url": "https://www.anthropic.com/news/rss.xml", "source_name": "Anthropic News",
     "category": "tech", "country": "US", "language": "en", "credibility_level": 1, "source_type": "official"},
    {"feed_url": "https://deepmind.google/blog/rss.xml", "source_name": "Google DeepMind Blog",
     "category": "tech", "country": "US", "language": "en", "credibility_level": 1, "source_type": "official"},
    # ---- 科技媒体 ----
    {"feed_url": "https://techcrunch.com/feed/", "source_name": "TechCrunch",
     "category": "tech", "country": "US", "language": "en", "credibility_level": 2, "source_type": "tech_media"},
    {"feed_url": "https://www.theverge.com/rss/index.xml", "source_name": "The Verge",
     "category": "tech", "country": "US", "language": "en", "credibility_level": 2, "source_type": "tech_media"},
    {"feed_url": "https://feeds.arstechnica.com/arstechnica/index", "source_name": "Ars Technica",
     "category": "tech", "country": "US", "language": "en", "credibility_level": 2, "source_type": "tech_media"},
    # ---- 国际新闻 ----
    {"feed_url": "http://feeds.bbci.co.uk/news/world/rss.xml", "source_name": "BBC World",
     "category": "world", "country": "GB", "language": "en", "credibility_level": 1, "source_type": "official_media"},
    {"feed_url": "http://feeds.bbci.co.uk/news/technology/rss.xml", "source_name": "BBC Technology",
     "category": "tech", "country": "GB", "language": "en", "credibility_level": 1, "source_type": "official_media"},
    {"feed_url": "https://feeds.apnews.com/apf-topnews", "source_name": "AP News",
     "category": "world", "country": "US", "language": "en", "credibility_level": 1, "source_type": "official_media"},
    # ---- 财经 ----
    {"feed_url": "https://www.federalreserve.gov/feeds/press_all.xml", "source_name": "Federal Reserve",
     "category": "finance", "country": "US", "language": "en", "credibility_level": 1, "source_type": "official"},
    # ---- 国际新闻补充（Reuters / MIT Tech Review / Bloomberg）----
    {"feed_url": "https://feeds.reuters.com/Reuters/worldNews", "source_name": "Reuters World",
     "category": "world", "country": "US", "language": "en", "credibility_level": 1, "source_type": "official_media"},
    {"feed_url": "https://www.technologyreview.com/feed/", "source_name": "MIT Technology Review",
     "category": "tech", "country": "US", "language": "en", "credibility_level": 1, "source_type": "tech_media"},
    {"feed_url": "https://feeds.bloomberg.com/markets.rss", "source_name": "Bloomberg Markets",
     "category": "finance", "country": "US", "language": "en", "credibility_level": 1, "source_type": "official_media"},
    # ---- 更多权威科技源（拓宽覆盖面）----
    {"feed_url": "https://www.wired.com/feed/rss", "source_name": "Wired",
     "category": "tech", "country": "US", "language": "en", "credibility_level": 2, "source_type": "tech_media"},
    # ---- 国际新闻补充 ----
    {"feed_url": "https://www.aljazeera.com/xml/rss/all.xml", "source_name": "Al Jazeera",
     "category": "world", "country": "INTL", "language": "en", "credibility_level": 1, "source_type": "official_media"},
    # ---- 中文科技/AI 源（支撑中文默认生产，避免全部依赖英文改写）----
    {"feed_url": "https://36kr.com/feed", "source_name": "36氪",
     "category": "tech", "country": "CN", "language": "zh", "credibility_level": 2, "source_type": "tech_media"},
    {"feed_url": "https://www.qbitai.com/feed", "source_name": "量子位",
     "category": "tech", "country": "CN", "language": "zh", "credibility_level": 2, "source_type": "tech_media"},
    {"feed_url": "https://www.leiphone.com/rss.xml", "source_name": "雷锋网",
     "category": "tech", "country": "CN", "language": "zh", "credibility_level": 2, "source_type": "tech_media"},
    {"feed_url": "https://www.jiqizhixin.com/rss", "source_name": "机器之心",
     "category": "tech", "country": "CN", "language": "zh", "credibility_level": 2, "source_type": "tech_media"},
]

# ============ 全球化内容策略（按国家/地区）============
# 体现"Agent 理解的是用户，而不仅仅是新闻"：不同国家不同内容策略
COUNTRY_STRATEGIES: dict[str, dict] = {
    "US": {"label": "美国", "language": "en", "content_styles": ["breaking_news", "deep_dive", "analysis"],
           "default_style": "deep_dive", "title_style": "direct_factual", "summary_len": 180, "body_len": 900,
           "target_audience": "tech_professionals", "platforms": ["twitter", "linkedin", "web_feed"], "tone": "objective_in_depth"},
    "GB": {"label": "英国", "language": "en", "content_styles": ["analysis", "brief"],
           "default_style": "analysis", "title_style": "understated", "summary_len": 150, "body_len": 700,
           "target_audience": "general_news_readers", "platforms": ["web_feed", "twitter"], "tone": "measured"},
    "JP": {"label": "日本", "language": "ja", "content_styles": ["summary", "brief"],
           "default_style": "summary", "title_style": "polite_concise", "summary_len": 120, "body_len": 500,
           "target_audience": "commuters", "platforms": ["line", "web_feed", "twitter"], "tone": "polite_concise"},
    "KR": {"label": "韩国", "language": "ko", "content_styles": ["entertainment", "trending"],
           "default_style": "trending", "title_style": "engaging", "summary_len": 140, "body_len": 600,
           "target_audience": "young_mobile", "platforms": ["naver", "twitter", "instagram"], "tone": "lively"},
    "IN": {"label": "印度", "language": "en", "content_styles": ["startup", "tech_explainer"],
           "default_style": "startup", "title_style": "aspirational", "summary_len": 160, "body_len": 750,
           "target_audience": "startup_enthusiasts", "platforms": ["whatsapp", "linkedin", "twitter"], "tone": "aspirational"},
    "BR": {"label": "巴西", "language": "pt", "content_styles": ["football", "lifestyle"],
           "default_style": "football", "title_style": "passionate", "summary_len": 150, "body_len": 650,
           "target_audience": "sports_fans", "platforms": ["instagram", "whatsapp", "twitter"], "tone": "passionate"},
    "CN": {"label": "中国", "language": "zh", "content_styles": ["deep_dive", "industry_analysis"],
           "default_style": "deep_dive", "title_style": "professional", "summary_len": 160, "body_len": 800,
           "target_audience": "tech_professionals", "platforms": ["weibo", "wechat", "web_feed"], "tone": "professional"},
}

# ============ 分发平台与内容形态 ============
DISTRIBUTION_PLATFORMS: dict[str, dict] = {
    "twitter":      {"format": "short_card",   "max_len": 280,   "best_hour_local": [8, 12, 19]},
    "linkedin":     {"format": "long_post",    "max_len": 3000,  "best_hour_local": [9, 13]},
    "web_feed":     {"format": "full_article", "max_len": 0,     "best_hour_local": [7, 18]},
    "wechat":       {"format": "rich_article", "max_len": 20000, "best_hour_local": [8, 21]},
    "weibo":        {"format": "short_card",   "max_len": 140,   "best_hour_local": [12, 21]},
    "instagram":    {"format": "visual_card",  "max_len": 2200,  "best_hour_local": [19, 21]},
    "naver":        {"format": "summary_card", "max_len": 1000,  "best_hour_local": [8, 20]},
    "line":         {"format": "brief_card",   "max_len": 500,   "best_hour_local": [8, 19]},
    "whatsapp":     {"format": "brief_card",   "max_len": 800,   "best_hour_local": [9, 20]},
    "short_video":  {"format": "video_script", "max_len": 1500,  "best_hour_local": [19, 21]},
}

# 内容形态候选（Publisher 推荐输出）
CONTENT_FORMATS: list[str] = ["news_card", "article", "commentary", "summary", "short_video_script", "deep_analysis"]

# ============ 短视频平台预设（VideoScriptPlanner 用）============
# 不同平台的时长 / 钩子风格 / 受众 / 画幅 / 语气 差异，驱动 Agent 产出贴合平台的脚本。
VIDEO_PLATFORMS: dict[str, dict] = {
    "douyin":        {"label": "抖音",        "duration": 45, "hook_style": "冲突/反转",
                      "audience": "泛娱乐大众", "aspect": "9:16", "tone": "口语化、强情绪、前 3 秒抛冲突"},
    "tiktok":        {"label": "TikTok",      "duration": 30, "hook_style": "curiosity/question",
                      "audience": "global Gen-Z", "aspect": "9:16", "tone": "casual, fast-paced, 英文口播（除非源语言为中文）"},
    "reuters":       {"label": "Reuters Shorts", "duration": 40, "hook_style": "fact-led",
                      "audience": "news consumers", "aspect": "9:16", "tone": "neutral, authoritative, 先给结论"},
    "instagram":     {"label": "Instagram Reels", "duration": 30, "hook_style": "aesthetic/relatable",
                      "audience": "lifestyle", "aspect": "9:16", "tone": "polished, 视觉优先"},
    "youtube_shorts": {"label": "YouTube Shorts", "duration": 50, "hook_style": "value/hook",
                      "audience": "how-to seekers", "aspect": "9:16", "tone": "informative, 干货向"},
    "kuaishou":      {"label": "快手",        "duration": 35, "hook_style": "接地气/故事",
                      "audience": "下沉市场大众", "aspect": "9:16", "tone": "亲切、口语、强共鸣"},
}

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROMPTS_DIR = BASE_DIR / "prompt_templates"
CHROMA_DIR = BASE_DIR / "data" / "chroma"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TF_", extra="ignore")

    # ---- 运行环境 ----
    app_name: str = "TrendForge"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # ---- 数据库（SQLite 默认，可切 PostgreSQL）----
    database_url: str = f"sqlite+aiosqlite:///{DATA_DIR}/trendforge.db"

    # ---- 向量库（Chroma 嵌入式）----
    chroma_path: str = str(CHROMA_DIR)
    chroma_collection: str = "news_chunks"
    embedding_model: str = "text-embedding-3-small"

    # ---- LLM 厂商（支持 openai/anthropic/deepseek/kimi/qwen/glm）----
    llm_vendor: str = "openai"            # 当前激活的对话厂商
    llm_api_key: str = ""                 # 通用 key（任一厂商都可用）
    llm_base_url: str = ""                # 覆盖厂商默认 base_url（留空用默认）
    llm_model: str = ""                   # 覆盖厂商默认模型（留空用默认）
    # 各厂商独立 key（优先于通用 key；env: TF_<VENDOR>_API_KEY）
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    kimi_api_key: str = ""
    qwen_api_key: str = ""
    glm_api_key: str = ""
    # 各 Agent 模型覆盖（留空 → 用厂商默认模型；可按 Agent 差异化选型）
    planner_model: str = ""
    research_model: str = ""
    writer_model: str = ""
    reviewer_model: str = ""
    publisher_model: str = ""
    video_model: str = ""               # 短视频脚本生成模型（留空 → writer_model → 厂商默认）
    llm_timeout: int = 180
    llm_max_retries: int = 3

    # ---- Embedding（独立于对话厂商，保持向量维度稳定）----
    # 仅支持 OpenAI 兼容厂商；留空 key → 自动用本地 MiniLM（与种子数据兼容，零配置）
    embedding_vendor: str = "openai"
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    # ---- RAG ----
    rag_top_k: int = 20
    rag_min_relevance: float = 0.5
    rag_time_decay_lambda: float = 0.02

    # ---- 智能 Chunk ----
    chunk_target_tokens: int = 400      # 目标 300~500 token
    chunk_min_tokens: int = 80          # 低于此合并到相邻
    chunk_overlap_tokens: int = 60      # overlap 50~80
    chunk_max_tokens: int = 600         # 硬上限

    # ---- News Collector ----
    collector_initial_target: int = 600      # 首次初始化目标篇数（P1：扩充精选知识库）
    collector_per_feed_limit: int = 80       # 每个 feed 最多取多少条（P1：提高单源覆盖）
    collector_fetch_fulltext: bool = True    # RSS 只有摘要时是否抓全文
    collector_http_timeout: int = 20         # 抓取超时秒
    collector_daily_hour: int = 6            # 每日增量采集的小时（本地时区）
    collector_user_agent: str = "TrendForgeBot/1.0 (+https://github.com/trendforge)"

    # ---- Workflow ----
    max_review_rounds: int = 2
    sla_seconds: int = 480
    task_retry_max: int = 3
    task_retry_base_sec: float = 5.0

    # ---- 发布 ----
    gray_initial_ratio: float = 0.1
    gray_observation_minutes: int = 30
    gray_ctr_threshold: float = 0.03
    publish_channels: list[str] = ["site_feed", "weibo", "twitter", "rss"]

    # ---- 合规 ----
    sensitive_words: list[str] = ["震惊", "惊呆", "必看", "内部消息", "据传", "曝光"]


settings = Settings()

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)
