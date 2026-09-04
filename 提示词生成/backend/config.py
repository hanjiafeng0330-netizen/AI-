import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://ccproxy.yukework.com")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

STORAGE_DIR = BASE_DIR / "storage"
PRODUCTS_DIR = STORAGE_DIR / "products"
RESULTS_DIR = STORAGE_DIR / "results"
HISTORY_DIR = STORAGE_DIR / "history"

for d in (PRODUCTS_DIR, RESULTS_DIR, HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 「脚本分析」工作台是同目录下的兄弟项目，本工作台直接读它落盘的历史结果文件，
# 不经过 HTTP，避免依赖脚本分析服务是否在运行。
SOURCE_ANALYSIS_DIR = BASE_DIR.parent / "脚本分析"
SOURCE_HISTORY_DIR = SOURCE_ANALYSIS_DIR / "storage" / "history"
