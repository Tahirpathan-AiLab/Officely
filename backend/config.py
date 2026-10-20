from pathlib import Path
import os
from dataclasses import dataclass, field

# Directory paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"
PROMPTS_DIR = BACKEND_DIR / "agents" / "prompts"


def _load_project_env() -> None:
    """Load project .env values without overriding explicitly exported variables."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return
    try:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not name or name in os.environ:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            os.environ[name] = value
    except OSError:
        # Configuration can still come from the process environment or UI.
        return


_load_project_env()
DB_PATH = DATA_DIR / "robonest.db"

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class LLMSettings:
    provider: str = os.getenv("ROBONEST_LLM_PROVIDER", "ollama")  # "ollama", "openai", or "mock"
    ollama_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout_seconds: int = 90
    max_concurrency: int = 1  # Serialized LLM queue to prevent GPU/RAM overload


@dataclass
class AgentSettings:
    max_steps_per_task: int = 10  # Agent loop protection
    task_timeout_seconds: int = 180
    history_limit: int = 6  # Context chhota rakho taaki local models confuse na hon


@dataclass
class SecuritySettings:
    allow_dangerous_execution: bool = False
    ask_user_for_destructive_actions: bool = True
    safe_working_directory: str = str(PROJECT_ROOT) 


@dataclass
class Settings:
    app_name: str = "RoboNest Backend"
    version: str = "1.0.0"
    host: str = "127.0.0.1"
    port: int = 8765
    db_path: Path = DB_PATH
    llm: LLMSettings = field(default_factory=LLMSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)


settings = Settings()
