import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# Google OAuth
CLIENT_SECRETS_PATH = os.getenv("GOOGLE_CLIENT_SECRETS_PATH", "client_secret.json")
TOKEN_STORE_PATH = os.getenv("GOOGLE_TOKEN_PATH", "token.json")

# Which courses to watch (comma-separated Classroom course IDs)
COURSE_IDS = [c.strip() for c in os.getenv("COURSE_IDS", "").split(",") if c.strip()]

# Local model server (Ollama, OpenAI-compatible)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3:8b")
MODEL_THINKING = _bool("MODEL_THINKING", True)  # use Qwen3 thinking mode for grading

# Pipeline behavior
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
AUTO_RETURN = _bool("AUTO_RETURN", False)  # if False: sets draftGrade + comment only, you review + return manually
DB_PATH = os.getenv("DB_PATH", "grading_state.sqlite3")

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive",
]
