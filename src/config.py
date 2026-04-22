from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=True)

DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DOCS_DIR = PROJECT_ROOT / "docs"


@dataclass(frozen=True)
class AppSettings:
    groq_api_key: str
    groq_model: str
    request_timeout_seconds: int
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_sender_email: str
    smtp_use_tls: bool


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = str(value).strip()
    return cleaned if cleaned else default


def get_settings() -> AppSettings:
    return AppSettings(
        groq_api_key=_get_env("GROQ_API_KEY", ""),
        groq_model=_get_env("GROQ_MODEL", "llama-3.1-8b-instant"),
        request_timeout_seconds=int(_get_env("REQUEST_TIMEOUT_SECONDS", "30")),
        smtp_host=_get_env("SMTP_HOST", ""),
        smtp_port=int(_get_env("SMTP_PORT", "587")),
        smtp_username=_get_env("SMTP_USERNAME", ""),
        smtp_password=_get_env("SMTP_PASSWORD", ""),
        smtp_sender_email=_get_env("SMTP_SENDER_EMAIL", ""),
        smtp_use_tls=_as_bool(_get_env("SMTP_USE_TLS", "true"), default=True),
    )


def ensure_project_dirs() -> None:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
