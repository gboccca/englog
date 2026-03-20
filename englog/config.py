"""EngLog configuration and paths."""

import os
from pathlib import Path

# Base data directory — stored in user's home
DATA_DIR = Path(os.environ.get("ENGLOG_DATA", Path.home() / ".englog"))
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
DB_PATH = DATA_DIR / "englog.db"

# Capture settings
SCREENSHOT_INTERVAL_SECONDS = 30  # how often to take a screenshot
SCREENSHOT_QUALITY = 40           # JPEG quality (lower = smaller files)
SCREENSHOT_SCALE = 0.5            # resize factor (0.5 = half resolution)

# Ollama settings
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")  # good balance of speed/quality
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", 32768))  # context window size

# AI context limits — keeps prompts within safe token budgets
MAX_CONTEXT_CHARS = 24000  # ~6K tokens, leaves room for system prompt + output
OLLAMA_TIMEOUT = 300  # seconds — long sessions need more generation time

# Ensure directories exist
def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
