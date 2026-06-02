from __future__ import annotations

import json
from pathlib import Path

from paper_search.reader_models import ModelProvider, ReaderModelRegistry, build_chat_request_kwargs
from paper_search.reader_server import ReaderServerConfig, create_reader_handler


def test_default_registry_exposes_presets_without_secret_values(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")
    registry = ReaderModelRegistry(tmp_path)

    public = registry.public_config()
    text = json.dumps(public)

    provider_ids = {provider["id"] for provider in public["providers"]}
    assert {"deepseek", "openai", "openrouter", "custom"}.issubset(provider_ids)
    deepseek = next(provider for provider in public["providers"] if provider["id"] == "deepseek")
    assert deepseek["base_url"] == "https://api.deepseek.com"
    assert deepseek["has_key"] is True
    assert "deepseek-secret" not in text
    assert "api_key" not in text.lower()


def test_registry_imports_chat_xfairllm_env_presets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "vertex_ai/claude-sonnet-4-6")
    monkeypatch.setenv("CHAT_PRESET_CLAUDE_SONNET_4_6_LABEL", "Claude Sonnet 4.6")
    monkeypatch.setenv("CHAT_PRESET_CLAUDE_SONNET_4_6_BASE", "https://management.llmproxy.ai.orange")
    monkeypatch.setenv("CHAT_PRESET_CLAUDE_SONNET_4_6_MODEL", "vertex_ai/claude-sonnet-4-6")
    monkeypatch.setenv("CHAT_PRESET_CLAUDE_SONNET_4_6_KEY", "preset-secret")

    public = ReaderModelRegistry(tmp_path).public_config()
    text = json.dumps(public)

    sonnet = next(provider for provider in public["providers"] if provider["id"] == "chat-claude_sonnet_4_6")
    assert sonnet["label"] == "Claude Sonnet 4.6"
    assert sonnet["base_url"] == "https://management.llmproxy.ai.orange"
    assert sonnet["models"] == ["vertex_ai/claude-sonnet-4-6"]
    assert sonnet["has_key"] is True
    assert public["defaults"]["chat_value"] == "chat-claude_sonnet_4_6|vertex_ai/claude-sonnet-4-6"
    assert any(p["value"] == public["defaults"]["chat_value"] for p in public["presets"])
    assert "preset-secret" not in text
    assert "api_key" not in text.lower()


def test_custom_provider_roundtrip_redacts_local_key(tmp_path: Path):
    registry = ReaderModelRegistry(tmp_path)
    provider = ModelProvider(
        id="local-vllm",
        label="Local vLLM",
        base_url="http://127.0.0.1:8000/v1",
        models=["qwen-local"],
        default_model="qwen-local",
        enabled=True,
    )

    registry.upsert_provider(provider)
    registry.set_provider_key("local-vllm", "sk-local-secret")
    reloaded = ReaderModelRegistry(tmp_path)
    public = reloaded.public_config()

    local = next(provider for provider in public["providers"] if provider["id"] == "local-vllm")
    assert local["has_key"] is True
    assert local["models"] == ["qwen-local"]
    assert "sk-local-secret" not in json.dumps(public)
    assert json.loads((tmp_path / "secrets.json").read_text(encoding="utf-8"))["local-vllm"] == "sk-local-secret"


def test_provider_validation_rejects_invalid_base_url(tmp_path: Path):
    registry = ReaderModelRegistry(tmp_path)

    try:
        registry.upsert_provider(ModelProvider(id="bad", label="Bad", base_url="file:///tmp/key", models=["x"], default_model="x"))
    except ValueError as exc:
        assert "base_url" in str(exc)
    else:
        raise AssertionError("invalid base_url should fail")


def test_build_chat_request_kwargs_uses_openai_compatible_fields(tmp_path: Path):
    registry = ReaderModelRegistry(tmp_path)
    registry.upsert_provider(
        ModelProvider(
            id="custom-api",
            label="Custom API",
            base_url="https://llm.example.com/v1",
            models=["paper-model"],
            default_model="paper-model",
            enabled=True,
        )
    )
    registry.set_provider_key("custom-api", "sk-custom")

    kwargs = build_chat_request_kwargs(
        registry,
        provider_id="custom-api",
        model="paper-model",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=123,
    )

    assert kwargs == {
        "base_url": "https://llm.example.com/v1",
        "api_key": "sk-custom",
        "model": "paper-model",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 123,
    }


def test_models_api_redacts_keys(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    state = tmp_path / ".reader"
    registry = ReaderModelRegistry(state)
    registry.set_provider_key("openai", "sk-sho...leak")
    config = ReaderServerConfig(site_dir=site, state_dir=state)
    handler = create_reader_handler(config)

    response = handler.handle_test_request("/api/models")

    assert response.status == 200
    text = response.body.decode("utf-8")
    payload = json.loads(text)
    assert any(provider["id"] == "openai" and provider["has_key"] for provider in payload["providers"])
    assert "sk-sho...leak" not in text
    assert "api_key" not in text.lower()


def test_models_api_can_save_key_without_echoing_it(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    state = tmp_path / ".reader"
    handler = create_reader_handler(ReaderServerConfig(site_dir=site, state_dir=state))

    response = handler.handle_test_request(
        "/api/models/openai/key",
        method="POST",
        json_body={"key": "sk-private-key"},
    )

    assert response.status == 200
    text = response.body.decode("utf-8")
    assert json.loads(text) == {"ok": True, "provider_id": "openai", "has_key": True}
    assert "sk-private-key" not in text
    assert json.loads((state / "secrets.json").read_text(encoding="utf-8"))["openai"] == "sk-private-key"


def test_models_api_can_upsert_custom_provider(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    state = tmp_path / ".reader"
    handler = create_reader_handler(ReaderServerConfig(site_dir=site, state_dir=state))

    response = handler.handle_test_request(
        "/api/models",
        method="POST",
        json_body={
            "id": "my-openai-compatible",
            "label": "My API",
            "base_url": "https://llm.example.com/v1",
            "models": ["reader-model"],
            "default_model": "reader-model",
            "enabled": True,
        },
    )

    assert response.status == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert any(provider["id"] == "my-openai-compatible" for provider in payload["providers"])
