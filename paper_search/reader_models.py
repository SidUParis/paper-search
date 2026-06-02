"""Server-side model/provider registry for the private reader workbench.

The browser may edit provider metadata, but API keys stay in the local state
directory or environment variables and are never returned by public APIs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import re

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency exists in normal repo installs
    load_dotenv = None  # type: ignore[assignment]


@dataclass(slots=True)
class ModelProvider:
    id: str
    label: str
    base_url: str
    models: list[str] = field(default_factory=list)
    default_model: str = ""
    enabled: bool = True
    api_key_env: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelProvider":
        return cls(
            id=str(data.get("id") or "").strip(),
            label=str(data.get("label") or "").strip(),
            base_url=str(data.get("base_url") or "").strip(),
            models=[str(item).strip() for item in data.get("models", []) if str(item).strip()],
            default_model=str(data.get("default_model") or "").strip(),
            enabled=bool(data.get("enabled", True)),
            api_key_env=str(data.get("api_key_env") or "").strip(),
        )

    def validate(self) -> None:
        if not self.id or not self.id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("provider id must be alphanumeric plus '-' or '_'")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an http(s) URL")
        if not self.models:
            raise ValueError("at least one model is required")
        if not self.default_model:
            self.default_model = self.models[0]
        if self.default_model not in self.models:
            self.models.insert(0, self.default_model)

    def to_storage(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def to_public(self, has_key: bool) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "label": self.label,
            "base_url": self.base_url,
            "models": list(self.models),
            "default_model": self.default_model,
            "enabled": self.enabled,
            "has_key": has_key,
        }


def _slug_provider_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "preset"


def _chat_preset_providers_from_env() -> list[ModelProvider]:
    """Mirror chat.xfairllm.com model presets from CHAT_PRESET_* env vars.

    The env format is intentionally compatible with the standalone chat app:
    CHAT_PRESET_<NAME>_LABEL / _BASE / _MODEL / _KEY.  Keys remain server-side;
    the browser only receives provider metadata plus has_key.
    """

    groups: dict[str, dict[str, str]] = {}
    pattern = re.compile(r"^CHAT_PRESET_(?P<name>.+)_(?P<field>LABEL|BASE|MODEL|KEY)$")
    for key, value in os.environ.items():
        match = pattern.match(key)
        if not match or not str(value).strip():
            continue
        groups.setdefault(match.group("name"), {})[match.group("field").lower()] = str(value).strip()

    providers: list[ModelProvider] = []
    for name, data in sorted(groups.items()):
        base_url = data.get("base", "").strip()
        model = data.get("model", "").strip()
        if not base_url or not model:
            continue
        provider = ModelProvider(
            id=f"chat-{_slug_provider_id(name)}",
            label=data.get("label") or name.replace("_", " ").title(),
            base_url=base_url,
            api_key_env=f"CHAT_PRESET_{name}_KEY",
            models=[model],
            default_model=model,
            enabled=True,
        )
        try:
            provider.validate()
        except ValueError:
            continue
        providers.append(provider)
    return providers


def default_providers() -> list[ModelProvider]:
    providers = [
        ModelProvider(
            id="deepseek",
            label="DeepSeek",
            base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY",
            models=["deepseek-v4-flash", "deepseek-v4-pro"],
            default_model="deepseek-v4-flash",
            enabled=True,
        ),
        ModelProvider(
            id="openai",
            label="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            models=["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
            default_model="gpt-4.1-mini",
            enabled=False,
        ),
        ModelProvider(
            id="openrouter",
            label="OpenRouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            models=["qwen/qwen3.6-plus", "google/gemma-4-31b-it:free"],
            default_model="qwen/qwen3.6-plus",
            enabled=True,
        ),
        ModelProvider(
            id="custom",
            label="Custom OpenAI-compatible",
            base_url="https://example.com/v1",
            models=["custom-model"],
            default_model="custom-model",
            enabled=False,
        ),
    ]
    providers.extend(_chat_preset_providers_from_env())
    return providers


def _load_runtime_env() -> None:
    """Load repo-local env files used by the paper-search workflows.

    The reader workbench may run from the fork directory while the user's live
    credentials remain in `/home/orange/paper-search/.env`; loading both keeps
    API-key detection consistent without copying secrets into git.
    """

    if load_dotenv is None:
        return
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / ".env",
        Path("/home/orange/paper-search/.env"),
        Path("/home/orange/xfairllm-chat/.env"),
    ]
    for path in candidates:
        if path.exists():
            load_dotenv(path, override=False)


class ReaderModelRegistry:
    """Local model-provider registry with server-side secret storage."""

    def __init__(self, state_dir: Path | str) -> None:
        _load_runtime_env()
        self.state_dir = Path(state_dir)
        self.providers_path = self.state_dir / "providers.json"
        self.secrets_path = self.state_dir / "secrets.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _load_provider_map(self) -> dict[str, ModelProvider]:
        providers = {provider.id: provider for provider in default_providers()}
        if self.providers_path.exists():
            data = json.loads(self.providers_path.read_text(encoding="utf-8"))
            for item in data.get("providers", []):
                if isinstance(item, dict):
                    provider = ModelProvider.from_dict(item)
                    provider.validate()
                    providers[provider.id] = provider
        return providers

    def _save_provider_map(self, providers: dict[str, ModelProvider]) -> None:
        payload = {"providers": [provider.to_storage() for provider in sorted(providers.values(), key=lambda p: p.id)]}
        self.providers_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_secrets(self) -> dict[str, str]:
        if not self.secrets_path.exists():
            return {}
        data = json.loads(self.secrets_path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}

    def _save_secrets(self, secrets: dict[str, str]) -> None:
        self.secrets_path.write_text(json.dumps(secrets, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            self.secrets_path.chmod(0o600)
        except OSError:
            pass

    def list_providers(self) -> list[ModelProvider]:
        return list(self._load_provider_map().values())

    def get_provider(self, provider_id: str) -> ModelProvider:
        providers = self._load_provider_map()
        if provider_id not in providers:
            raise KeyError(f"unknown provider: {provider_id}")
        return providers[provider_id]

    def upsert_provider(self, provider: ModelProvider) -> None:
        provider.validate()
        providers = self._load_provider_map()
        providers[provider.id] = provider
        self._save_provider_map(providers)

    def set_provider_key(self, provider_id: str, api_key: str) -> None:
        if not api_key.strip():
            raise ValueError("api key must not be empty")
        # Ensure the provider exists before accepting a secret for it.
        self.get_provider(provider_id)
        secrets = self._load_secrets()
        secrets[provider_id] = api_key
        self._save_secrets(secrets)

    def resolve_api_key(self, provider: ModelProvider) -> str:
        if provider.api_key_env and os.environ.get(provider.api_key_env):
            return str(os.environ[provider.api_key_env])
        return self._load_secrets().get(provider.id, "")

    def has_key(self, provider: ModelProvider) -> bool:
        return bool(self.resolve_api_key(provider))

    def public_config(self) -> dict[str, Any]:
        provider_objects = self.list_providers()
        providers = [provider.to_public(has_key=self.has_key(provider)) for provider in provider_objects]
        chat_model = os.environ.get("CHAT_MODEL", "").strip()
        chat_default = "deepseek/deepseek-v4-flash"
        chat_default_value = "deepseek|deepseek-v4-flash"
        presets = []
        for provider in provider_objects:
            for model in provider.models:
                has_key = self.has_key(provider)
                option = {
                    "provider_id": provider.id,
                    "provider_label": provider.label,
                    "model": model,
                    "label": provider.label if len(provider.models) == 1 else f"{provider.label} · {model}",
                    "value": f"{provider.id}|{model}",
                    "enabled": provider.enabled,
                    "has_key": has_key,
                }
                presets.append(option)
                if chat_model and model == chat_model:
                    chat_default = f"{provider.id}/{model}"
                    chat_default_value = option["value"]
        # Prefer the chat.xfairllm.com preset list in the UI when it exists;
        # otherwise fall back to enabled built-in providers.
        ui_presets = [p for p in presets if p["provider_id"].startswith("chat-") and p["enabled"]]
        if not ui_presets:
            ui_presets = [p for p in presets if p["enabled"]]
        return {
            "providers": providers,
            "presets": ui_presets,
            "defaults": {
                "chat": chat_default,
                "chat_value": chat_default_value,
                "paper_qa": chat_default,
                "refine": "deepseek/deepseek-v4-pro",
                "ranking": "openrouter/qwen/qwen3.6-plus",
            },
        }


def build_chat_request_kwargs(
    registry: ReaderModelRegistry,
    provider_id: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1000,
) -> dict[str, Any]:
    provider = registry.get_provider(provider_id)
    api_key = registry.resolve_api_key(provider)
    if not api_key:
        raise ValueError(f"missing API key for provider: {provider_id}")
    selected_model = model or provider.default_model
    if selected_model not in provider.models:
        raise ValueError(f"model '{selected_model}' is not configured for provider '{provider_id}'")
    return {
        "base_url": provider.base_url,
        "api_key": api_key,
        "model": selected_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
