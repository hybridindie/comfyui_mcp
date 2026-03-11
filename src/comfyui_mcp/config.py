"""Configuration management with YAML file + environment variable overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, field_validator

_DEFAULT_CONFIG_PATH = Path.home() / ".comfyui-mcp" / "config.yaml"

_DEFAULT_DANGEROUS_NODES = [
    # Code execution — shell, eval, exec
    "Terminal",  # comfyui-colab: shell via subprocess
    "interpreter_tool",  # comfyui_LLM_party: exec/eval
    "interpreter_function",  # comfyui_LLM_party: exec/eval
    "KY_Eval_Python",  # ComfyUI-KYNode: exec Python
    "CustomScriptNumpy",  # ComfyUI-FuncAsTexture-CoiiNode: exec formula
    "Equation1param _O",  # QualityOfLifeSuit_Omar92: raw eval
    "Equation2params _O",  # QualityOfLifeSuit_Omar92: raw eval
    "Evaluate Integers",  # efficiency-nodes-comfyui: simpleeval
    "Evaluate Floats",  # efficiency-nodes-comfyui: simpleeval
    "Evaluate Strings",  # efficiency-nodes-comfyui: simpleeval
    "Simple Eval Examples",  # efficiency-nodes-comfyui: simpleeval
    # Network access — arbitrary HTTP requests
    "Image Send HTTP",  # was-node-suite: arbitrary HTTP
    "Get Request Node",  # ComfyUI-RequestNodes: HTTP GET
    "Post Request Node",  # ComfyUI-RequestNodes: HTTP POST
    "Form Post Request Node",  # ComfyUI-RequestNodes: HTTP POST
    "Rest Api Node",  # ComfyUI-RequestNodes: REST calls
    # Filesystem access — read/write arbitrary paths
    "Load Text File",  # was-node-suite: reads arbitrary files
    "Save Text File",  # was-node-suite: writes arbitrary files
    "Text Load Line From File",  # was-node-suite: reads arbitrary files
    "Video Dump Frames",  # was-node-suite: reads/writes arbitrary paths
    "Create Morph Image from Path",  # was-node-suite: reads arbitrary paths
    "Create Video from Path",  # was-node-suite: reads/writes arbitrary paths
    "Export API",  # was-node-suite: writes to arbitrary paths
    "saveTextToFile _O",  # QualityOfLifeSuit_Omar92: writes arbitrary files
]

_DEFAULT_ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".json"]
_DEFAULT_ALLOWED_DOWNLOAD_DOMAINS = ["huggingface.co", "civitai.com"]
_DEFAULT_ALLOWED_MODEL_EXTENSIONS = [".safetensors", ".ckpt", ".pt", ".pth", ".bin"]


class ComfyUISettings(BaseModel):
    url: str = "http://127.0.0.1:8188"
    tls_verify: bool = True
    timeout_connect: int = 30
    timeout_read: int = 300

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https")
        if not parsed.netloc:
            raise ValueError("URL must have a valid host")
        return v


class SecuritySettings(BaseModel):
    mode: Literal["audit", "enforce"] = "audit"
    allowed_nodes: list[str] = []
    dangerous_nodes: list[str] = list(_DEFAULT_DANGEROUS_NODES)
    max_upload_size_mb: int = 50
    allowed_extensions: list[str] = list(_DEFAULT_ALLOWED_EXTENSIONS)
    allowed_download_domains: list[str] = list(_DEFAULT_ALLOWED_DOWNLOAD_DOMAINS)
    allowed_model_extensions: list[str] = list(_DEFAULT_ALLOWED_MODEL_EXTENSIONS)

    @field_validator("max_upload_size_mb")
    @classmethod
    def validate_max_upload_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_upload_size_mb must be at least 1")
        if v > 500:
            raise ValueError("max_upload_size_mb must not exceed 500")
        return v


class ModelSearchSettings(BaseModel):
    huggingface_token: str = ""
    civitai_api_key: str = ""
    max_search_results: int = 10


class RateLimitSettings(BaseModel):
    workflow: int = 10
    generation: int = 10
    file_ops: int = 30
    read_only: int = 60


class LoggingSettings(BaseModel):
    audit_file: str = "~/.comfyui-mcp/audit.log"


class SSESettings(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080


class TransportSettings(BaseModel):
    sse: SSESettings = SSESettings()


class Settings(BaseModel):
    comfyui: ComfyUISettings = ComfyUISettings()
    security: SecuritySettings = SecuritySettings()
    rate_limits: RateLimitSettings = RateLimitSettings()
    logging: LoggingSettings = LoggingSettings()
    transport: TransportSettings = TransportSettings()
    model_search: ModelSearchSettings = ModelSearchSettings()


def _apply_env_overrides(data: dict) -> dict:
    """Apply environment variable overrides."""
    env_map = {
        "COMFYUI_URL": ("comfyui", "url"),
        "COMFYUI_TLS_VERIFY": ("comfyui", "tls_verify"),
        "COMFYUI_TIMEOUT_CONNECT": ("comfyui", "timeout_connect"),
        "COMFYUI_TIMEOUT_READ": ("comfyui", "timeout_read"),
        "COMFYUI_SECURITY_MODE": ("security", "mode"),
        "COMFYUI_AUDIT_FILE": ("logging", "audit_file"),
        "COMFYUI_HUGGINGFACE_TOKEN": ("model_search", "huggingface_token"),
        "COMFYUI_CIVITAI_API_KEY": ("model_search", "civitai_api_key"),
        "COMFYUI_MAX_SEARCH_RESULTS": ("model_search", "max_search_results"),
        "COMFYUI_ALLOWED_DOWNLOAD_DOMAINS": ("security", "allowed_download_domains"),
    }
    for env_var, path in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            section, key = path
            if section not in data:
                data[section] = {}
            if key in ("timeout_connect", "timeout_read", "max_search_results"):
                data[section][key] = int(value)
            elif key == "tls_verify":
                data[section][key] = value.lower() in ("true", "1", "yes")
            elif key == "allowed_download_domains":
                data[section][key] = [d.strip() for d in value.split(",") if d.strip()]
            else:
                data[section][key] = value
    return data


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML file with environment variable overrides."""
    path = config_path or _DEFAULT_CONFIG_PATH
    data: dict = {}

    if path.exists():
        with open(path) as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = loaded

    data = _apply_env_overrides(data)
    return Settings(**data)
