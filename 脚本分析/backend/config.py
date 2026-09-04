import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://ccproxy.yukework.com/v1")

STORAGE_DIR = BASE_DIR / "storage"
VIDEOS_DIR = STORAGE_DIR / "videos"
FRAMES_DIR = STORAGE_DIR / "frames"
AUDIO_DIR = STORAGE_DIR / "audio"
RESULTS_DIR = STORAGE_DIR / "results"
HISTORY_DIR = STORAGE_DIR / "history"

for d in (VIDEOS_DIR, FRAMES_DIR, AUDIO_DIR, RESULTS_DIR, HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-sol")
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")

DEFAULT_FRAME_INTERVAL_SEC = 2.0
MAX_FRAMES = 60
FRAME_BATCH_SIZE = 8
