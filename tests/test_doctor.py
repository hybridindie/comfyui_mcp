"""Doctor diagnostics (issue #226)."""

from __future__ import annotations

import json

import httpx
import respx

from comfyui_mcp.config import (
    ComfyUISettings,
    LoggingSettings,
    RemoteAuthSettings,
    RemoteTransportSettings,
    Settings,
    TransportSettings,
)
from comfyui_mcp.doctor import FAIL, PASS, WARN, main, run_checks

BASE = "http://test:8188"


def _settings(tmp_path, **kwargs) -> Settings:
    kwargs.setdefault("comfyui", ComfyUISettings(url=BASE))
    kwargs.setdefault("logging", LoggingSettings(audit_file=str(tmp_path / "audit.log")))
    return Settings(**kwargs)


def _mock_comfy() -> None:
    respx.get(f"{BASE}/queue").mock(
        return_value=httpx.Response(200, json={"queue_running": [], "queue_pending": []})
    )
    respx.get(f"{BASE}/features").mock(
        return_value=httpx.Response(
            200,
            json={
                "max_upload_size": 104857600,
                "extension": {"manager": {"supports_v4": True}},
            },
        )
    )
    respx.get(f"{BASE}/settings").mock(
        return_value=httpx.Response(200, json={"Comfy.InstalledVersion": "0.46.3"})
    )
    respx.get(f"{BASE}/v2/manager/version").mock(return_value=httpx.Response(200, text="V4.2.2"))
    respx.get(f"{BASE}/model-manager/models").mock(return_value=httpx.Response(404, json={}))


def _by_name(report):
    return {check.name: check for check in report.checks}


@respx.mock
async def test_happy_path_reports_pass_and_warnings(tmp_path):
    _mock_comfy()

    report = await run_checks(_settings(tmp_path), config_path=tmp_path / "missing.yaml")

    checks = _by_name(report)
    assert report.failed is False
    assert checks["config"].status == WARN
    assert checks["audit"].status == PASS
    assert checks["transport"].status == PASS
    assert checks["comfyui"].status == PASS
    assert checks["features"].status == PASS
    assert checks["version"].detail == "0.46.3"
    assert checks["manager"].status == PASS
    assert checks["model-manager"].status == WARN
    assert checks["policy"].status == PASS


@respx.mock
async def test_unreachable_comfyui_is_fatal_and_skips_probes(tmp_path):
    respx.get(f"{BASE}/queue").mock(return_value=httpx.Response(500, json={}))

    report = await run_checks(_settings(tmp_path), config_path=tmp_path / "missing.yaml")

    checks = _by_name(report)
    assert report.failed is True
    assert checks["comfyui"].status == FAIL
    assert "features" not in checks
    assert "model-manager" not in checks


@respx.mock
async def test_auth_enabled_without_token_fails(tmp_path, monkeypatch):
    _mock_comfy()
    monkeypatch.delenv("COMFYUI_MCP_HTTP_TOKEN", raising=False)
    settings = _settings(
        tmp_path,
        transport=TransportSettings(
            remote=RemoteTransportSettings(
                enabled=True,
                auth=RemoteAuthSettings(enabled=True),
            )
        ),
    )

    report = await run_checks(settings, config_path=tmp_path / "missing.yaml")

    assert _by_name(report)["transport"].status == FAIL
    assert report.failed is True


@respx.mock
async def test_auth_token_env_passes(tmp_path, monkeypatch):
    _mock_comfy()
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", "s3cret")
    settings = _settings(
        tmp_path,
        transport=TransportSettings(
            remote=RemoteTransportSettings(
                enabled=True,
                auth=RemoteAuthSettings(enabled=True),
            )
        ),
    )

    report = await run_checks(settings, config_path=tmp_path / "missing.yaml")

    check = _by_name(report)["transport"]
    assert check.status == PASS
    assert "1 token(s)" in check.detail


@respx.mock
async def test_audit_parent_that_is_a_file_fails(tmp_path):
    _mock_comfy()
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    settings = _settings(
        tmp_path,
        logging=LoggingSettings(audit_file=str(blocker / "audit.log")),
    )

    report = await run_checks(settings, config_path=tmp_path / "missing.yaml")

    assert _by_name(report)["audit"].status == FAIL


@respx.mock
def test_main_json_output(tmp_path, capsys):
    _mock_comfy()
    config = tmp_path / "config.yaml"
    config.write_text(
        f"comfyui:\n  url: {BASE}\nlogging:\n  audit_file: {tmp_path / 'audit.log'}\n"
    )

    code = main(["--config", str(config), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["failed"] is False
    assert any(check["name"] == "comfyui" for check in payload["checks"])


@respx.mock
def test_main_failure_exit_code(tmp_path, capsys):
    respx.get(f"{BASE}/queue").mock(return_value=httpx.Response(500, json={}))
    config = tmp_path / "config.yaml"
    config.write_text(f"comfyui:\n  url: {BASE}\n")

    code = main(["--config", str(config)])

    out = capsys.readouterr().out
    assert code == 1
    assert "failure(s)" in out
