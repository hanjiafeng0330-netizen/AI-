from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# --- sub-module apps ---
from 提示词生成.backend.main import app as prompt_app
from 脚本分析.backend.main import app as script_app
from 视频生成.backend.main import app as video_app

app = FastAPI(title="AI 图书自动化")

# mount sub-modules (Starlette strips the prefix before forwarding)
app.mount("/prompt", prompt_app)
app.mount("/script", script_app)
app.mount("/video", video_app)

# homepage static files (must be last)
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="home")
