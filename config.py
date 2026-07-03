import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Model configurations
# Load model from environment, fallback to valid Claude 3.5 Sonnet model
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

# Application settings
MAX_HISTORY_LENGTH = 50
MAX_CONTEXT_MESSAGES = 20
DB_PATH = os.getenv("DB_PATH", "/app/data/mindspace.db")

# Safety Settings
CRISIS_DETECTION_ENABLED = os.getenv("CRISIS_DETECTION_ENABLED", "True").lower() == "true"
OFF_TOPIC_DETECTION_ENABLED = os.getenv("OFF_TOPIC_DETECTION_ENABLED", "True").lower() == "true"
PROMPT_INJECTION_DETECTION = os.getenv("PROMPT_INJECTION_DETECTION", "True").lower() == "true"
OFFENSIVE_CONTENT_FILTER = os.getenv("OFFENSIVE_CONTENT_FILTER", "True").lower() == "true"

# Session Settings
SESSION_TIMEOUT_HOURS = 24  # Sessions expire after 24 hours
MAX_SESSIONS_PER_USER = 5

# API Settings - align environment variables and default port to 8015
API_HOST = os.getenv("API_HOST", os.getenv("HOST", "0.0.0.0"))
API_PORT = int(os.getenv("API_PORT", os.getenv("PORT", 8015)))
API_RELOAD = os.getenv("API_RELOAD", os.getenv("RELOAD", "False")).lower() == "true"
API_WORKERS = int(os.getenv("API_WORKERS", os.getenv("WORKERS", 1)))