# config.py
import os
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH, override=True)

# Ассистент и LLM
ASSISTANT_NAME: str = os.getenv("ASSISTANT_NAME", "ишак").strip().lower()
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")

# Озвучка и аудио
VOICE_FEEDBACK: bool = os.getenv("VOICE_FEEDBACK", "true").lower() in ("true", "1", "yes")
VOICE_LANGUAGE: str = os.getenv("VOICE_LANGUAGE", "ru-RU")
VOICE_NAME: str = os.getenv("VOICE_NAME", "ru-RU-DmitryNeural")

# Пути к папкам
BASE_DIR = os.path.dirname(__file__)
SOUNDS_DIR = os.path.join(BASE_DIR, "sounds")
os.makedirs(SOUNDS_DIR, exist_ok=True)