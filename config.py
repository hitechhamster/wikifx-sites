"""
配置文件 - 命令行版(main.py)的回落配置。

密钥一律从环境变量读取，不再硬编码，避免提交进 Git。
本地运行命令行版前，先设置环境变量：
    TAVILY_API_KEY / OPENROUTER_API_KEY / WP_APP_PASSWORD
Web 后台(webapp)不依赖这里，所有配置存数据库、网页里填。
"""
import os

# ============ API Keys（环境变量）============
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")            # Tavily 搜索 key（tvly-...）
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")    # OpenRouter key（sk-or-v1-...）


# ============ WordPress 账号 ============
WP_URL = os.environ.get("WP_URL", "https://dzypjy.com")   # 站点首页，末尾不要带 /
WP_USERNAME = os.environ.get("WP_USERNAME", "kbing0830")  # WP 登录用户名
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")   # Application Password（环境变量）

# ============ 模型配置 ============
MODEL_OUTLINE_AND_ARTICLE = "openai/gpt-5-mini"  # 大纲 + 正文（更便宜的 GPT-5 mini）
MODEL_SEO_META = "google/gemini-3.1-flash-lite"  # SEO 元数据
MODEL_IMAGE_PROMPT = "google/gemini-3.1-flash-lite"  # 生成图片 prompt
MODEL_IMAGE_GEN = "google/gemini-3.1-flash-image"  # Nano Banana 生图

# ============ 字数 ============
WORD_COUNT_MIN = 2000
WORD_COUNT_MAX = 3000

# ============ 图片配置 ============
IMAGE_ENABLED = False  # 总开关。False 则完全不生成图片
IMAGE_RETRY = 1  # 图片失败时的额外重试次数（1 = 共试 2 次）

# ============ 路径 ============
INPUT_EXCEL = "./input.xlsx"  # 默认输入 Excel
OUTPUT_DIR = "./output"  # 输出根目录（内含 articles/ images/ results_*.xlsx）

# ============ 其他 ============
DEFAULT_LANGUAGE = "Vietnamese"  # 默认文章语言（越南语）
PAUSE_EVERY_N_ROWS = 3  # 每处理 N 条暂停 15 秒，防限流