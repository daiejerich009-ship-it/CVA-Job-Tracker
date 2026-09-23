"""Optional configuration helpers. Main settings are read from .env."""
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = PROJECT_DIR / "credentials.json"
TOKEN_FILE = PROJECT_DIR / "token.json"
LOG_FILE = PROJECT_DIR / "job_tracker.log"
