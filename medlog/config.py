"""Central configuration. Everything tunable lives here."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    mem0_api_key: str = ""
    anthropic_api_key: str = ""

    medlog_db_path: str = "medlog.db"

    # Sonnet for per-turn chat; Opus for reconciliation, briefs and eval judging.
    medlog_chat_model: str = "claude-sonnet-5"
    medlog_reasoning_model: str = "claude-opus-5"

    # Retrieval defaults. mem0 v3 ships threshold=0.1 / rerank=False; we raise
    # top_k because clinical questions often span several entries.
    search_top_k: int = 12
    search_threshold: float = 0.1

    @property
    def db_path(self) -> Path:
        p = Path(self.medlog_db_path)
        return p if p.is_absolute() else ROOT / p

    def require(self, *names: str) -> None:
        """Fail loudly and usefully when a key is missing."""
        missing = [n for n in names if not getattr(self, n, "")]
        if missing:
            keys = ", ".join(n.upper() for n in missing)
            raise RuntimeError(
                f"Missing required credential(s): {keys}\n"
                f"Copy .env.example to .env and fill them in.\n"
                f"  MEM0_API_KEY      -> https://app.mem0.ai\n"
                f"  ANTHROPIC_API_KEY -> https://console.anthropic.com"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
