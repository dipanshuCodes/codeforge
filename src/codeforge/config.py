"""Settings. The ONLY source of user identity: never parse identity from Request text.

Values come from the process environment, filled in from `.env.local` (local runs) and `.env`
(deployed) by `load_env_files`. Every key read here is listed in ENV_KEYS and must appear in
`.env.example` (a unit test enforces it).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Every environment variable CodeForge reads. Add new keys here AND in .env.example.
ENV_KEYS: tuple[str, ...] = (
    "CODEFORGE_USER_ID",
    "CODEFORGE_ROLE",
    "CODEFORGE_DB_PATH",
    "CODEFORGE_RUN_QUOTA",
    "CODEFORGE_CHAOS_RATE",
    "CODEFORGE_CHAOS_SEED",
    "GROQ_API_KEY",  # read by langchain-groq, never by our code
)
# Later files are weaker: values already set (shell, or an earlier file) are kept.
ENV_FILES: tuple[str, ...] = (".env.local", ".env")

Role = Literal["student", "instructor"]
_ROLES: tuple[str, ...] = ("student", "instructor")


class ConfigError(Exception):
    """Raised when required config is missing or invalid. We fail closed, never default."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    role: Role
    large_model: str = "openai/gpt-oss-120b"
    small_model: str = "openai/gpt-oss-20b"
    db_path: str = "codeforge.db"
    sandbox_timeout_s: float = 10.0
    max_output_bytes: int = 10_240
    sandbox_memory_bytes: int = 256 * 1024 * 1024  # enforced on Linux; macOS ignores RLIMIT_AS
    max_repair_attempts: int = 2  # 1-3 Executions per Run
    chaos_rate: float = 0.0  # share of model calls failed on purpose (R5); 0 = off
    chaos_seed: int = 0
    run_quota: int = 5  # Requests per User per day (R1 demo User: 5, chaos-run User: 25)


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    """Build Settings from environment variables; raise ConfigError on missing identity."""
    user_id = env.get("CODEFORGE_USER_ID", "").strip()
    if not user_id:
        raise ConfigError("CODEFORGE_USER_ID is not set")
    role = env.get("CODEFORGE_ROLE", "").strip()
    if role not in _ROLES:
        raise ConfigError(f"CODEFORGE_ROLE must be one of {', '.join(_ROLES)}")
    overrides = {}
    if env.get("CODEFORGE_DB_PATH"):
        overrides["db_path"] = env["CODEFORGE_DB_PATH"]
    quota = env.get("CODEFORGE_RUN_QUOTA", "").strip()
    if quota:
        if not quota.isdigit() or int(quota) < 1:
            raise ConfigError("CODEFORGE_RUN_QUOTA must be a positive whole number")
        overrides["run_quota"] = int(quota)
    rate = env.get("CODEFORGE_CHAOS_RATE", "").strip()
    if rate:
        try:
            value = float(rate)
        except ValueError:
            value = -1.0
        if not 0.0 <= value <= 1.0:
            raise ConfigError("CODEFORGE_CHAOS_RATE must be a number from 0 to 1")
        overrides["chaos_rate"] = value
    seed = env.get("CODEFORGE_CHAOS_SEED", "").strip()
    if seed:
        if not seed.isdigit():
            raise ConfigError("CODEFORGE_CHAOS_SEED must be a whole number")
        overrides["chaos_seed"] = int(seed)
    return Settings(user_id=user_id, role=role, **overrides)


def parse_env_file(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Ignores blanks, comments and malformed lines; strips one pair
    of matching quotes and an optional `export `. No variable interpolation."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key.isidentifier():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env_files(directory: Path, environ: MutableMapping[str, str] = os.environ) -> None:
    """Fill `environ` from .env.local, then .env, in `directory`. Never overrides a value that
    is already set; blank values in a file are skipped so they can't shadow a weaker file."""
    for name in ENV_FILES:
        path = directory / name
        if not path.is_file():
            continue
        for key, value in parse_env_file(path.read_text(encoding="utf-8")).items():
            if value and not environ.get(key):
                environ[key] = value
