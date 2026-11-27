"""Configuration management with YAML file + environment variable overrides."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

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
    # Network egress / billable — first-party ComfyUI cloud API nodes (PR #9129).
    # These send user prompts/images to paid third-party services from the
    # ComfyUI host, incurring real monetary cost. Refresh from
    # comfy/api_nodes/ when ComfyUI core adds new vendors.
    # BFL (Black Forest Labs / Flux)
    "FluxProUltraImageNode",
    "FluxProExpandNode",
    "FluxProFillNode",
    "FluxEraseNode",
    "FluxVTONode",
    "Flux2ImageNode",
    "Flux3TextToVideoNode",
    "Flux3ImageToVideoNode",
    "Flux3VideoContinuationNode",
    # Gemini (Google)
    "GeminiNode",
    "GeminiNodeV2",
    "GeminiInputFiles",
    "GeminiImageNode",
    "GeminiImage2Node",
    "GeminiNanoBanana2",
    "GeminiNanoBanana2V2",
    "GeminiVideoOmni",
    # Ideogram
    "IdeogramV3",
    "IdeogramV4",
    "IdeogramPImage",
    # Kling
    "KlingTextToVideoNode",
    "KlingOmniProTextToVideoNode",
    "KlingOmniProFirstLastFrameNode",
    "KlingOmniProImageToVideoNode",
    "KlingOmniProVideoToVideoNode",
    "KlingOmniProEditVideoNode",
    "KlingOmniProImageNode",
    "KlingImage2VideoNode",
    "KlingStartEndFrameNode",
    "KlingVideoExtendNode",
    "KlingLipSyncAudioToVideoNode",
    "KlingLipSyncTextToVideoNode",
    "KlingImageGenerationNode",
    "KlingTextToVideoWithAudio",
    "KlingImageToVideoWithAudio",
    "KlingMotionControl",
    "KlingVideoNode",
    "KlingFirstLastFrameNode",
    "KlingAvatarNode",
    # Luma
    "LumaReferenceNode",
    "LumaConceptsNode",
    "LumaImageNode",
    "LumaImageModifyNode",
    "LumaVideoNode",
    "LumaImageToVideoNode",
    "LumaImageNode2",
    "LumaImageEditNode2",
    "LumaRay32TextToVideoNode",
    "LumaRay32ImageToVideoNode",
    "LumaRay32KeyframeNode",
    "LumaRay32KeyframesToVideoNode",
    "LumaRay32VideoEditNode",
    "LumaRay32VideoReframeNode",
    "LumaRay32ExtendVideoNode",
    # Minimax
    "MinimaxTextToVideoNode",
    "MinimaxImageToVideoNode",
    "MinimaxSubjectToVideoNode",
    "MinimaxHailuoVideoNode",
    "MinimaxHailuo03TextToVideoNode",
    "MinimaxHailuo03FirstLastFrameNode",
    "MinimaxHailuo03ReferenceNode",
    # Moonvalley
    "MoonvalleyImg2VideoNode",
    "MoonvalleyTxt2VideoNode",
    "MoonvalleyVideo2VideoNode",
    # OpenAI
    "OpenAIDalle2",
    "OpenAIDalle3",
    "OpenAIGPTImage1",
    "OpenAIGPTImageNodeV2",
    "OpenAIChatNode",
    "OpenAIInputFiles",
    "OpenAIChatConfig",
    # Pika
    "PikaImageToVideoNode2_2",
    "PikaTextToVideoNode2_2",
    "PikaScenesV2_2",
    "Pikadditions",
    "Pikaswaps",
    "Pikaffects",
    "PikaStartEndFrameNode2_2",
    # PixVerse
    "PixverseTemplateNode",
    "PixverseTextToVideoNode",
    "PixverseImageToVideoNode",
    "PixverseTransitionVideoNode",
    # Recraft
    "RecraftColorRGB",
    "RecraftControls",
    "RecraftStyleV3RealisticImage",
    "RecraftStyleV3DigitalIllustration",
    "RecraftStyleV3VectorIllustrationNode",
    "RecraftStyleV3LogoRaster",
    "RecraftStyleV3InfiniteStyleLibrary",
    "RecraftCreateStyleNode",
    "RecraftTextToImageNode",
    "RecraftImageToImageNode",
    "RecraftImageInpaintingNode",
    "RecraftTextToVectorNode",
    "RecraftVectorizeImageNode",
    "RecraftReplaceBackgroundNode",
    "RecraftRemoveBackgroundNode",
    "RecraftCrispUpscaleNode",
    "RecraftCreativeUpscaleNode",
    "RecraftV4TextToImageNode",
    "RecraftV4TextToVectorNode",
    # Rodin (3D generation)
    "Rodin3D_Regular",
    "Rodin3D_Detail",
    "Rodin3D_Smooth",
    "Rodin3D_Sketch",
    "Rodin3D_Gen2",
    "Rodin3D_Gen25_Image",
    "Rodin3D_Gen25_Text",
    # Runway
    "RunwayImageToVideoNodeGen3a",
    "RunwayImageToVideoNodeGen4",
    "RunwayFirstLastFrameNode",
    "RunwayTextToImageNode",
    "RunwayAleph2KeyframeNode",
    "RunwayAleph2PromptImageNode",
    "RunwayAleph2VideoToVideoNode",
    # Stability AI
    "StabilityStableImageUltraNode",
    "StabilityStableImageSD_3_5Node",
    "StabilityUpscaleConservativeNode",
    "StabilityUpscaleCreativeNode",
    "StabilityUpscaleFastNode",
    # Tripo (3D generation)
    "TripoTextToModelNode",
    "TripoImageToModelNode",
    "TripoMultiviewToModelNode",
    "TripoTextureNode",
    "TripoRefineNode",
    "TripoRigNode",
    "TripoRetargetNode",
    "TripoConversionNode",
    "TripoImportModelNode",
    "TripoP1TextToModelNode",
    "TripoP1ImageToModelNode",
    "TripoP1MultiviewToModelNode",
    # Veo2 / Veo3 (Google)
    "VeoVideoGenerationNode",
    "Veo3VideoGenerationNode",
    "Veo3FirstLastFrameNode",
]

_DEFAULT_ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".json"]
_DEFAULT_ALLOWED_DOWNLOAD_DOMAINS = ["huggingface.co", "civitai.com"]
_DEFAULT_ALLOWED_MODEL_EXTENSIONS = [".safetensors", ".ckpt", ".pt", ".pth", ".bin"]


class ComfyUISettings(BaseModel):
    url: str = "http://127.0.0.1:8188"
    external_url: str | None = None
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

    @field_validator("external_url")
    @classmethod
    def validate_external_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        return cls.validate_url(v)

    @field_validator("tls_verify")
    @classmethod
    def warn_tls_disabled(cls, v: bool) -> bool:
        if not v:
            _logger.warning(
                "TLS verification disabled — connections are vulnerable to MITM attacks. "
                "Only use for local development.",
            )
        return v


class ToolsSettings(BaseModel):
    """Tool-surface profile (issue #212).

    ``full`` exposes every registered tool. ``core`` exposes the generation,
    jobs, files, and discovery loop and hides the niche/destructive surface
    (history, settings, downloads, node packs, subgraphs, presets). Hidden
    tools are not listed and cannot be called by name.
    """

    profile: Literal["full", "core"] = "full"


class SecurityPolicySettings(BaseModel):
    """Declarative workflow policy (issue #211).

    ``deny_nodes``, ``max_nodes`` and ``allowed_model_folders`` hard-block in
    enforce mode (and warn in audit mode). ``warn_nodes`` adds class types to
    the warning set. ``on_warning`` decides what an enforce-mode warning means:
    ``elicit`` asks (default), ``block`` refuses (headless CI), ``allow`` logs
    and proceeds.
    """

    model_config = ConfigDict(extra="forbid")

    deny_nodes: list[str] = []
    warn_nodes: list[str] = []
    on_warning: Literal["elicit", "block", "allow"] = "elicit"
    max_nodes: int = 0
    allowed_model_folders: list[str] = []

    @field_validator("max_nodes")
    @classmethod
    def non_negative_max_nodes(cls, v: int) -> int:
        if v < 0:
            raise ValueError("security.policy.max_nodes must be >= 0 (0 disables)")
        return v


class SecuritySettings(BaseModel):
    mode: Literal["audit", "enforce"] = "audit"
    allowed_nodes: list[str] = []
    policy: SecurityPolicySettings = Field(default_factory=SecurityPolicySettings)
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
    huggingface_token: str = Field(default="", repr=False)
    civitai_api_key: str = Field(default="", repr=False)
    max_search_results: int = 10


class RateLimitSettings(BaseModel):
    workflow: int = 10
    generation: int = 10
    file_ops: int = 30
    read_only: int = 60


class LoggingSettings(BaseModel):
    audit_file: str = "~/.comfyui-mcp/audit.log"
    # Rotate the live audit file at this size; 0 disables rotation.
    max_bytes: int = 10 * 1024 * 1024
    # Number of rotated files to keep (audit.log.1 … audit.log.N); 0 truncates.
    backup_count: int = 5

    @field_validator("max_bytes")
    @classmethod
    def non_negative_max_bytes(cls, v: int) -> int:
        if v < 0:
            raise ValueError("logging.max_bytes must be >= 0")
        return v

    @field_validator("backup_count")
    @classmethod
    def non_negative_backup_count(cls, v: int) -> int:
        if v < 0:
            raise ValueError("logging.backup_count must be >= 0")
        return v


class RemoteAuthSettings(BaseModel):
    """Static bearer-token auth for the Streamable HTTP transport.

    ``tokens`` maps an identity label to the *name* of the environment variable
    holding that identity's token. Secrets stay in the environment; the YAML
    never contains one. The resolved identity is recorded in the audit trail and
    keys per-identity rate-limit buckets.
    """

    enabled: bool = False
    tokens: dict[str, str] = Field(default_factory=lambda: {"default": "COMFYUI_MCP_HTTP_TOKEN"})


class RemoteTransportSettings(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    allow_unauthenticated: bool = False
    auth: RemoteAuthSettings = Field(default_factory=RemoteAuthSettings)

    @field_validator("host")
    @classmethod
    def warn_non_localhost(cls, v: str) -> str:
        if v not in _LOOPBACK_HOSTS:
            _logger.warning(
                "Streamable HTTP transport binding to %s — enable "
                "transport.remote.auth (recommended) or allow_unauthenticated "
                "and put it behind authenticated TLS.",
                v,
            )
        return v

    @model_validator(mode="after")
    def require_auth_for_public_bind(self) -> RemoteTransportSettings:
        if not self.enabled:
            return self
        if (
            self.host not in _LOOPBACK_HOSTS
            and not self.auth.enabled
            and not self.allow_unauthenticated
        ):
            raise ValueError(
                "transport.remote.host is not a loopback address; enable "
                "transport.remote.auth or set transport.remote.allow_unauthenticated=true "
                "(not recommended)"
            )
        if self.auth.enabled and not self.auth.tokens:
            raise ValueError(
                "transport.remote.auth.enabled requires at least one "
                "identity: ENV_VAR entry under transport.remote.auth.tokens"
            )
        return self


class TransportSettings(BaseModel):
    remote: RemoteTransportSettings = RemoteTransportSettings()


class TasksSettings(BaseModel):
    """Background task settings (Phase 6). Opt-in — disabled by default.

    Background tasks are most valuable for the HTTP/remote transport where
    long-running workflows can return a task handle immediately instead of
    holding the request open. stdio single-user mode gains little.
    """

    enabled: bool = False
    # Backend URL: "memory://" (default, ephemeral, single-process) or
    # "redis://host:port/db" (persistent, horizontally scalable).
    backend_url: str = "memory://"


class Settings(BaseModel):
    comfyui: ComfyUISettings = ComfyUISettings()
    security: SecuritySettings = SecuritySettings()
    rate_limits: RateLimitSettings = RateLimitSettings()
    logging: LoggingSettings = LoggingSettings()
    transport: TransportSettings = TransportSettings()
    model_search: ModelSearchSettings = ModelSearchSettings()
    tools: ToolsSettings = ToolsSettings()
    tasks: TasksSettings = TasksSettings()


def _apply_env_overrides(data: dict) -> dict:
    """Apply environment variable overrides."""
    env_map = {
        "COMFYUI_URL": ("comfyui", "url"),
        "COMFYUI_EXTERNAL_URL": ("comfyui", "external_url"),
        "COMFYUI_TLS_VERIFY": ("comfyui", "tls_verify"),
        "COMFYUI_TIMEOUT_CONNECT": ("comfyui", "timeout_connect"),
        "COMFYUI_TIMEOUT_READ": ("comfyui", "timeout_read"),
        "COMFYUI_SECURITY_MODE": ("security", "mode"),
        "COMFYUI_AUDIT_FILE": ("logging", "audit_file"),
        "COMFYUI_AUDIT_MAX_BYTES": ("logging", "max_bytes"),
        "COMFYUI_AUDIT_BACKUP_COUNT": ("logging", "backup_count"),
        "COMFYUI_HUGGINGFACE_TOKEN": ("model_search", "huggingface_token"),
        "COMFYUI_CIVITAI_API_KEY": ("model_search", "civitai_api_key"),
        "COMFYUI_MAX_SEARCH_RESULTS": ("model_search", "max_search_results"),
        "COMFYUI_ALLOWED_DOWNLOAD_DOMAINS": ("security", "allowed_download_domains"),
        "COMFYUI_TOOLS_PROFILE": ("tools", "profile"),
        "COMFYUI_TASKS_ENABLED": ("tasks", "enabled"),
        "COMFYUI_TASKS_BACKEND_URL": ("tasks", "backend_url"),
    }
    for env_var, path in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            section, key = path
            if section not in data:
                data[section] = {}
            if key in (
                "timeout_connect",
                "timeout_read",
                "max_search_results",
                "max_bytes",
                "backup_count",
            ):
                data[section][key] = int(value)
            elif key in ("tls_verify", "enabled"):
                data[section][key] = value.lower() in ("true", "1", "yes")
            elif key == "allowed_download_domains":
                data[section][key] = [d.strip() for d in value.split(",") if d.strip()]
            else:
                data[section][key] = value

    # Transport auth is three levels deep, so it is handled separately rather
    # than widening env_map for every two-level entry.
    auth_enabled = os.environ.get("COMFYUI_HTTP_AUTH_ENABLED")
    allow_unauth = os.environ.get("COMFYUI_ALLOW_UNAUTHENTICATED_HTTP")
    if auth_enabled is not None or allow_unauth is not None:
        transport = data.setdefault("transport", {}).setdefault("remote", {})
        if auth_enabled is not None:
            transport.setdefault("auth", {})["enabled"] = auth_enabled.lower() in (
                "true",
                "1",
                "yes",
            )
        if allow_unauth is not None:
            transport["allow_unauthenticated"] = allow_unauth.lower() in (
                "true",
                "1",
                "yes",
            )
    return data


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML file with environment variable overrides."""
    path = config_path or _DEFAULT_CONFIG_PATH
    data: dict = {}

    if path.exists():
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = loaded

    data = _apply_env_overrides(data)
    return Settings(**data)
