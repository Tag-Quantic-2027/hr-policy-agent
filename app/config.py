"""All settings in one place, read from environment variables.

Nothing else in the codebase calls os.environ. That gives us one file to
check when something is misconfigured, and one place where secrets enter.
"""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"  # the policy files
CHROMA_DIR = ROOT / ".chroma"  # the vector index, built from the corpus and git-ignored
MODEL_DIR = ROOT / ".model_cache"  # the embedding model, downloaded once and git-ignored
MOCK_DATA_DIR = ROOT / "mock_data"  # the synthetic HR records

# Loads .env for local development. On Render the variables are set in the
# dashboard, there is no .env file, and this line does nothing.
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    llm_model: str
    judge_model: str
    mcp_policy_url: str
    mcp_hr_url: str
    mcp_internal_token: str  # proves to the HR server that a call comes from our own agent
    agent_max_steps: int
    daily_chat_limit: int  # the most chat requests served per day, to protect the API key's budget
    retrieval_top_k: int
    retrieval_mode: str  # "hybrid", "vector" or "keyword"
    disabled_tools: tuple[str, ...]  # tools hidden from the model, used only for evaluation experiments

    @property
    def has_llm_key(self) -> bool:
        return bool(self.anthropic_api_key)


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "claude-haiku-5-5"),
        judge_model=os.getenv("JUDGE_MODEL", "claude-sonnet-5-5"),
        mcp_policy_url=os.getenv("MCP_POLICY_URL", ""),
        mcp_hr_url=os.getenv("MCP_HR_URL", ""),
        # With the servers inside this service, a fresh random token per start is enough.
        # Set the variable only when the HR server runs as a separate service.
        mcp_internal_token=os.getenv("MCP_INTERNAL_TOKEN") or secrets.token_urlsafe(24),
        agent_max_steps=int(os.getenv("AGENT_MAX_STEPS", "8")),
        daily_chat_limit=int(os.getenv("DAILY_CHAT_LIMIT", "300")),
        retrieval_top_k=int(os.getenv("RETRIEVAL_TOP_K", "5")),
        retrieval_mode=os.getenv("RETRIEVAL_MODE", "hybrid"),
        disabled_tools=tuple(name.strip() for name in os.getenv("DISABLED_TOOLS", "").split(",") if name.strip()),
    )


settings = load_settings()
