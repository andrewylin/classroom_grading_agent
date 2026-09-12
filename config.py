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
DB_PATH = os.getenv("DB_PATH", "grading_state.sqlite3")
OUTPUT_PATH = os.getenv("OUTPUT_PATH", "grading_recommendations.csv")

# Read-only everywhere: this agent never writes back to Classroom or Drive.
# It reads submissions/rubrics and produces a local report for you to review
# and enter yourself.
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
