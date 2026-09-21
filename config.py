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
MODEL_THINKING = _bool("MODEL_THINKING", False)  # off by default - CPU-only thinking mode is very slow
MODEL_TIMEOUT_SECONDS = int(os.getenv("MODEL_TIMEOUT_SECONDS", "1800"))
MODEL_CTX_SIZE = int(os.getenv("MODEL_CTX_SIZE", "16384"))

# Prompt budgeting. These caps keep long essays / calibration blocks from
# silently overflowing the local model context window without a visible warning.
MAX_ESSAY_CHARS = int(os.getenv("MAX_ESSAY_CHARS", "12000"))
MAX_CALIBRATION_CHARS = int(os.getenv("MAX_CALIBRATION_CHARS", "2500"))

# Pipeline behavior
DB_PATH = os.getenv("DB_PATH", "grading_state.sqlite3")
OUTPUT_PATH = os.getenv("OUTPUT_PATH", "grading_recommendations.csv")
CALIBRATION_DIR = os.getenv("CALIBRATION_DIR", "calibration")
# How many of your saved calibration examples to include per grading prompt.
# More examples improve calibration but lengthen the prompt - on CPU-only
# hardware that directly costs you time per essay, so keep this small.
MAX_CALIBRATION_EXAMPLES = int(os.getenv("MAX_CALIBRATION_EXAMPLES", "3"))

# Read-only everywhere: this agent never writes back to Classroom or Drive.
# It reads submissions/rubrics and produces a local report for you to review
# and enter yourself.
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
