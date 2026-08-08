"""MCP prompts: reusable, parameterized prompt templates for the LLM.

Prompts expose the built-in workflow templates (txt2img, img2img, inpaint,
upscale) as recipes the LLM can retrieve. Per architecture.md "Resources and
prompts", prompt functions return a plain string (auto-wrapped as a user
message) — not mcp.types.PromptMessage or raw role/content dicts.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer


def register_prompts(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    sanitizer: PathSanitizer,
) -> dict[str, Any]:
    """Register workflow-template prompt recipes.

    Returns a dict mapping prompt names to the underlying async functions so
    tests can call them directly (mirrors the register_*_tools() contract).
    """
    prompt_fns: dict[str, Any] = {}

    @mcp.prompt(
        name="txt2img_prompt",
        description=(
            "Generate a text-to-image workflow recipe for a given style. "
            "Returns guidance the caller can pass to comfyui_generate_image."
        ),
    )
    async def txt2img_prompt(prompt: str, style: str = "photorealistic") -> str:
        """Produce a txt2img recipe for the given prompt and style.

        Args:
            prompt: The text description of the image to generate.
            style: The visual style to target (default: photorealistic).
        """
        limiter.check("prompt_txt2img")
        await audit.async_log(tool="prompt_txt2img", action="called", extra={"style": style})
        return (
            f"Use comfyui_generate_image to generate an image.\n\n"
            f"Prompt: {prompt}\n"
            f"Target style: {style}.\n"
            f"For {style} results, prefer a {style}-appropriate sampler/steps "
            f"combination — use comfyui_get_model_presets to look up the "
            f"recommended settings for your model family if unsure."
        )

    prompt_fns["txt2img_prompt"] = txt2img_prompt

    @mcp.prompt(
        name="img2img_prompt",
        description=(
            "Generate an image-to-image workflow recipe. The caller must "
            "have already uploaded the input image via comfyui_upload_image."
        ),
    )
    async def img2img_prompt(image: str, prompt: str, style: str = "photorealistic") -> str:
        """Produce an img2img recipe given an uploaded image and a transform prompt.

        Args:
            image: Filename of the image in ComfyUI's input directory.
            prompt: Text description guiding the transformation.
            style: Visual style to target (default: photorealistic).
        """
        limiter.check("prompt_img2img")
        await audit.async_log(
            tool="prompt_img2img", action="called", extra={"style": style, "image": image}
        )
        return (
            f"Use comfyui_transform_image to transform an existing image.\n\n"
            f"Image: {image}\n"
            f"Prompt: {prompt}\n"
            f"Target style: {style}.\n"
            f"Set the `strength` parameter based on how far to deviate from "
            f"the input — lower values (0.3-0.5) keep more of the original; "
            f"higher values (0.7-0.9) allow more change."
        )

    prompt_fns["img2img_prompt"] = img2img_prompt

    @mcp.prompt(
        name="inpaint_prompt",
        description=(
            "Generate an inpaint workflow recipe. The caller must have "
            "already uploaded both the input image and mask."
        ),
    )
    async def inpaint_prompt(
        image: str,
        mask: str,
        prompt: str,
        style: str = "photorealistic",
    ) -> str:
        """Produce an inpaint recipe given an uploaded image, mask, and prompt.

        Args:
            image: Filename of the image in ComfyUI's input directory.
            mask: Filename of the mask (white=inpaint, black=keep).
            prompt: Text description for the inpainted region.
            style: Visual style to target (default: photorealistic).
        """
        limiter.check("prompt_inpaint")
        await audit.async_log(
            tool="prompt_inpaint",
            action="called",
            extra={"style": style, "image": image, "mask": mask},
        )
        return (
            f"Use comfyui_inpaint_image to regenerate regions of an image.\n\n"
            f"Image: {image}\n"
            f"Mask: {mask} (white regions will be regenerated)\n"
            f"Prompt: {prompt}\n"
            f"Target style: {style}.\n"
            f"White regions in the mask indicate areas to regenerate. Set "
            f"`strength` (denoise) higher (0.8-1.0) for full replacement of the "
            f"masked region."
        )

    prompt_fns["inpaint_prompt"] = inpaint_prompt

    @mcp.prompt(
        name="upscale_prompt",
        description=(
            "Generate an upscaling workflow recipe. The caller must have "
            "already uploaded the input image."
        ),
    )
    async def upscale_prompt(image: str, upscale_model: str = "RealESRGAN_x4plus.pth") -> str:
        """Produce an upscale recipe for an uploaded image.

        Args:
            image: Filename of the image in ComfyUI's input directory.
            upscale_model: Name of the upscale model file (default: RealESRGAN_x4plus.pth).
        """
        limiter.check("prompt_upscale")
        await audit.async_log(
            tool="prompt_upscale", action="called", extra={"image": image, "model": upscale_model}
        )
        return (
            f"Use comfyui_upscale_image to upscale an existing image.\n\n"
            f"Image: {image}\n"
            f"Upscale model: {upscale_model}\n"
            f"The scale factor is determined by the upscale model "
            f"(e.g. RealESRGAN_x4plus = 4x). Use comfyui_list_models with "
            f"folder='upscale_models' to see available upscalers."
        )

    prompt_fns["upscale_prompt"] = upscale_prompt

    return prompt_fns
