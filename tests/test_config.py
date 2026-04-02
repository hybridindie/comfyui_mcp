"""Tests for configuration loading."""

import pytest
import yaml

from comfyui_mcp.config import (
    ModelSearchSettings,
    SecuritySettings,
    Settings,
    _apply_env_overrides,
    load_settings,
)


class TestSettingsDefaults:
    def test_default_comfyui_url(self):
        s = Settings()
        assert s.comfyui.url == "http://127.0.0.1:8188"

    def test_default_comfyui_external_url(self):
        s = Settings()
        assert s.comfyui.external_url is None

    def test_default_security_mode(self):
        s = Settings()
        assert s.security.mode == "audit"

    def test_default_rate_limits(self):
        s = Settings()
        assert s.rate_limits.workflow == 10
        assert s.rate_limits.read_only == 60

    def test_default_transport_remote_disabled(self):
        s = Settings()
        assert s.transport.remote.enabled is False

    def test_dangerous_nodes_default(self):
        s = Settings()
        assert len(s.security.dangerous_nodes) > 0

    def test_allowed_extensions_default(self):
        s = Settings()
        assert ".png" in s.security.allowed_extensions


class TestSettingsFromYAML:
    def test_load_from_yaml(self, tmp_path):
        config = {
            "comfyui": {
                "url": "https://gpu-server:8188",
                "external_url": "https://comfy.example.com/comfyui",
            },
            "security": {"mode": "enforce"},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config))

        settings = load_settings(config_path=config_file)
        assert settings.comfyui.url == "https://gpu-server:8188"
        assert settings.comfyui.external_url == "https://comfy.example.com/comfyui"
        assert settings.security.mode == "enforce"

    def test_missing_yaml_uses_defaults(self, tmp_path):
        settings = load_settings(config_path=tmp_path / "nonexistent.yaml")
        assert settings.comfyui.url == "http://127.0.0.1:8188"


class TestSettingsEnvOverrides:
    def test_env_overrides_url(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_URL", "https://env-server:8188")
        settings = load_settings()
        assert settings.comfyui.url == "https://env-server:8188"

    def test_env_overrides_external_url(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_EXTERNAL_URL", "https://comfy.example.com")
        settings = load_settings()
        assert settings.comfyui.external_url == "https://comfy.example.com"

    def test_env_overrides_security_mode(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_SECURITY_MODE", "enforce")
        settings = load_settings()
        assert settings.security.mode == "enforce"


class TestSecurityModeValidation:
    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            SecuritySettings(mode="invalid")

    def test_enforce_mode_accepted(self):
        s = SecuritySettings(mode="enforce")
        assert s.mode == "enforce"


class TestModelSearchSettings:
    def test_default_values(self):
        s = ModelSearchSettings()
        assert s.huggingface_token == ""
        assert s.civitai_api_key == ""
        assert s.max_search_results == 10

    def test_custom_values(self):
        s = ModelSearchSettings(
            huggingface_token="hf_xxx",
            civitai_api_key="civ_yyy",
            max_search_results=5,
        )
        assert s.huggingface_token == "hf_xxx"  # noqa: S105
        assert s.civitai_api_key == "civ_yyy"
        assert s.max_search_results == 5


class TestDownloadSecuritySettings:
    def test_default_allowed_download_domains(self):
        s = SecuritySettings()
        assert "huggingface.co" in s.allowed_download_domains
        assert "civitai.com" in s.allowed_download_domains

    def test_default_allowed_model_extensions(self):
        s = SecuritySettings()
        assert ".safetensors" in s.allowed_model_extensions
        assert ".ckpt" in s.allowed_model_extensions
        assert ".pt" in s.allowed_model_extensions
        assert ".pth" in s.allowed_model_extensions
        assert ".bin" in s.allowed_model_extensions

    def test_custom_download_domains(self):
        s = SecuritySettings(allowed_download_domains=["example.com"])
        assert s.allowed_download_domains == ["example.com"]


class TestModelSearchEnvOverrides:
    def test_huggingface_token_env(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_HUGGINGFACE_TOKEN", "hf_test123")
        data = _apply_env_overrides({})
        assert data["model_search"]["huggingface_token"] == "hf_test123"  # noqa: S105

    def test_civitai_api_key_env(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_CIVITAI_API_KEY", "civ_test456")
        data = _apply_env_overrides({})
        assert data["model_search"]["civitai_api_key"] == "civ_test456"

    def test_max_search_results_env(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_MAX_SEARCH_RESULTS", "20")
        data = _apply_env_overrides({})
        assert data["model_search"]["max_search_results"] == 20

    def test_allowed_download_domains_env(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_ALLOWED_DOWNLOAD_DOMAINS", "example.com,other.com")
        data = _apply_env_overrides({})
        assert data["security"]["allowed_download_domains"] == ["example.com", "other.com"]
