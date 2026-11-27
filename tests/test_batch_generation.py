"""Bounded batch generation (issue #229)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.generation import register_generation_tools


@pytest.fixture
def tools(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    inspector = WorkflowInspector(mode="audit", dangerous_nodes=[], allowed_nodes=[])
    sanitizer = PathSanitizer(allowed_extensions=[".png", ".safetensors"])
    mcp = FastMCP("batch-test")
    return register_generation_tools(mcp, client, audit, limiter, inspector, sanitizer=sanitizer)


@respx.mock
async def test_prompt_seed_matrix_submits_every_variant(tools):
    respx.post("http://test:8188/prompt").mock(
        side_effect=[httpx.Response(200, json={"prompt_id": f"id-{index}"}) for index in range(4)]
    )

    result = await tools["comfyui_generate_batch"](prompts=["a", "b"], seeds=[1, 2])

    assert result["status"] == "submitted"
    assert result["count"] == 4
    assert {(v["prompt"], v["seed"]) for v in result["variants"]} == {
        ("a", 1),
        ("a", 2),
        ("b", 1),
        ("b", 2),
    }
    assert {v["prompt_id"] for v in result["variants"]} == {
        "id-0",
        "id-1",
        "id-2",
        "id-3",
    }


async def test_matrix_over_the_cap_fails_before_submitting(tools):
    with pytest.raises(ValueError, match="exceeds the limit"):
        await tools["comfyui_generate_batch"](prompts=["a", "b", "c"], seeds=[1, 2, 3])


@respx.mock
async def test_no_seeds_generates_one_per_prompt(tools):
    respx.post("http://test:8188/promise").mock()  # guard: wrong path must not match
    respx.post("http://test:8188/prompt").mock(
        side_effect=[
            httpx.Response(200, json={"prompt_id": "id-0"}),
            httpx.Response(200, json={"prompt_id": "id-1"}),
        ]
    )

    result = await tools["comfyui_generate_batch"](prompts=["a", "b"])

    assert result["count"] == 2
    assert all(isinstance(v["seed"], int) for v in result["variants"])


@respx.mock
async def test_one_failed_variant_returns_partial(tools):
    respx.post("http://test:8188/prompt").mock(
        side_effect=[
            httpx.Response(200, json={"prompt_id": "id-0"}),
            httpx.Response(500, json={}),
        ]
    )

    result = await tools["comfyui_generate_batch"](prompts=["a", "b"])

    assert result["status"] == "partial"
    assert result["count"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["prompt"] == "b"


async def test_empty_prompt_is_rejected(tools):
    with pytest.raises(ValueError, match="non-empty"):
        await tools["comfyui_generate_batch"](prompts=["a", "  "])
