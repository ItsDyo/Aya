from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aya.paths import PROJECT_ROOT


def _load_dotenv(path: Path = PROJECT_ROOT / ".env"):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _env(name: str, default: str = "", aliases: tuple[str, ...] = ()) -> str:
    for candidate in (name, *aliases):
        value = os.getenv(candidate)
        if value is not None:
            return value
    return default


def _env_bool(name: str, default: bool = False, aliases: tuple[str, ...] = ()) -> bool:
    value = _env(name, str(int(default)), aliases).strip().lower()
    return value in {"1", "true", "sim", "yes", "on", "ligado"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _ollama_openai_url() -> str:
    value = _env("AYA_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1", ("OLLAMA_BASE_URL",)).rstrip("/")
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


@dataclass(frozen=True)
class ModelConfig:
    primary: str = os.getenv("AYA_MODEL_PRIMARY", "llama3.2")
    reviewer: str = os.getenv("AYA_MODEL_REVIEWER", "gemma2:2b")
    ollama_base_url: str = _ollama_openai_url()
    ollama_api_key: str = os.getenv("AYA_OLLAMA_API_KEY", "ollama")
    default_temperature: float = _env_float("AYA_DEFAULT_TEMPERATURE", 0.7)
    default_max_tokens: int = _env_int("AYA_DEFAULT_MAX_TOKENS", 700)
    primary_temperature: float = _env_float("AYA_PRIMARY_TEMPERATURE", 0.7)
    primary_max_tokens: int = _env_int("AYA_PRIMARY_MAX_TOKENS", 800)
    reviewer_temperature: float = _env_float("AYA_REVIEWER_TEMPERATURE", 0.2)
    reviewer_max_tokens: int = _env_int("AYA_REVIEWER_MAX_TOKENS", 800)


@dataclass(frozen=True)
class VoiceConfig:
    name: str = os.getenv("AYA_PIPER_VOICE", "pt_BR-faber-medium")
    voice_dir: Path = Path(os.getenv("AYA_PIPER_VOICE_DIR", str(PROJECT_ROOT / "voices")))
    output_file: str = os.getenv("AYA_PIPER_OUTPUT_FILE", "aya_piper_resposta.wav")
    max_chars: int = _env_int("AYA_PIPER_MAX_CHARS", 3500)
    timeout_seconds: int = _env_int("AYA_PIPER_TIMEOUT_SECONDS", 120)

    @property
    def model_path(self) -> Path:
        return Path(os.getenv("AYA_PIPER_MODEL", str(self.voice_dir / f"{self.name}.onnx")))

    @property
    def config_path(self) -> Path:
        return Path(os.getenv("AYA_PIPER_CONFIG", str(self.voice_dir / f"{self.name}.onnx.json")))


@dataclass(frozen=True)
class RuntimeConfig:
    auto_reflection_interval: int = _env_int("AYA_AUTO_REFLECTION_INTERVAL", 6)
    default_study_minutes: int = _env_int("AYA_DEFAULT_STUDY_MINUTES", 25)
    panel_limit: int = _env_int("AYA_PANEL_LIMIT", 3)
    context_memory_limit: int = _env_int("AYA_CONTEXT_MEMORY_LIMIT", 8)
    context_knowledge_limit: int = _env_int("AYA_CONTEXT_KNOWLEDGE_LIMIT", 5)
    context_event_limit: int = _env_int("AYA_CONTEXT_EVENT_LIMIT", 5)
    memory_temporary_ttl_days: int = _env_int("AYA_MEMORY_TEMPORARY_TTL_DAYS", 45)
    privacy_mode: str = os.getenv("AYA_PRIVACY_MODE", "leve").strip().lower()


@dataclass(frozen=True)
class RAGConfig:
    candidate_limit: int = _env_int("AYA_RAG_CANDIDATE_LIMIT", 40)
    context_items: int = _env_int("AYA_RAG_CONTEXT_ITEMS", 8)
    context_max_chars: int = _env_int("AYA_RAG_CONTEXT_MAX_CHARS", 6500)
    item_max_chars: int = _env_int("AYA_RAG_ITEM_MAX_CHARS", 900)
    max_items_per_source: int = _env_int("AYA_RAG_MAX_ITEMS_PER_SOURCE", 2)
    min_score: float = _env_float("AYA_RAG_MIN_SCORE", 0.12)
    embedding_enabled: bool = _env_bool("AYA_EMBEDDING_ENABLED", False)
    embedding_model: str = _env("AYA_EMBEDDING_MODEL", "embeddinggemma").strip()
    embedding_timeout_seconds: int = _env_int("AYA_EMBEDDING_TIMEOUT_SECONDS", 90)
    embedding_scan_limit: int = _env_int("AYA_EMBEDDING_SCAN_LIMIT", 5000)


@dataclass(frozen=True)
class ServerConfig:
    remote_mode: bool = _env_bool("AYA_REMOTE_MODE", False)
    host: str = _env("AYA_HOST", "127.0.0.1", ("AYA_GRADIO_HOST",)).strip() or "127.0.0.1"
    port: int = _env_int("AYA_PORT", _env_int("AYA_GRADIO_PORT", 7860))
    auth_enabled: bool = _env_bool("AYA_AUTH_ENABLED", False)
    auth_user: str = _env("AYA_AUTH_USERNAME", "", ("AYA_GRADIO_USER",)).strip()
    auth_password: str = _env("AYA_AUTH_PASSWORD", "", ("AYA_GRADIO_PASSWORD",)).strip()
    share: bool = _env_bool("AYA_GRADIO_SHARE", False)

    @property
    def auth(self) -> tuple[str, str] | None:
        if self.auth_enabled and self.auth_user and self.auth_password:
            return (self.auth_user, self.auth_password)
        return None

    @property
    def is_network_exposed(self) -> bool:
        return self.remote_mode or self.host in {"0.0.0.0", "::"} or self.share

    @property
    def public_url_hint(self) -> str:
        if self.remote_mode:
            return f"http://TAILSCALE-IP:{self.port}"
        if self.host in {"0.0.0.0", "::"}:
            return f"http://SEU-IP-LOCAL:{self.port}"
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class SecurityConfig:
    allowed_file_root: Path = Path(_env("AYA_ALLOWED_FILE_ROOT", str(PROJECT_ROOT)).strip() or PROJECT_ROOT).resolve()


MODEL_CONFIG = ModelConfig()
VOICE_CONFIG = VoiceConfig()
RUNTIME_CONFIG = RuntimeConfig()
RAG_CONFIG = RAGConfig()
SERVER_CONFIG = ServerConfig()
SECURITY_CONFIG = SecurityConfig()
