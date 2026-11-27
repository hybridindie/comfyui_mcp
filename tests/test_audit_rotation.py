"""Audit log rotation and retention (issue #208)."""

from __future__ import annotations

import json

import pytest

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.config import load_settings


def _records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _write(logger: AuditLogger, count: int) -> None:
    for index in range(count):
        logger.log(tool="t", action="called", extra={"payload": "x" * 200, "n": index})


class TestRotation:
    def test_rotates_when_threshold_is_crossed(self, tmp_path):
        path = tmp_path / "audit.log"
        logger = AuditLogger(path, max_bytes=400, backup_count=2)

        _write(logger, 6)

        assert (tmp_path / "audit.log.1").exists()
        assert path.stat().st_size <= 400
        assert all(record["tool"] == "t" for record in _records(path))
        assert all(record["tool"] == "t" for record in _records(tmp_path / "audit.log.1"))

    def test_keeps_only_backup_count_files(self, tmp_path):
        path = tmp_path / "audit.log"
        logger = AuditLogger(path, max_bytes=300, backup_count=2)

        _write(logger, 12)

        assert (tmp_path / "audit.log.1").exists()
        assert (tmp_path / "audit.log.2").exists()
        assert not (tmp_path / "audit.log.3").exists()

    def test_zero_disables_rotation(self, tmp_path):
        path = tmp_path / "audit.log"
        logger = AuditLogger(path, max_bytes=0, backup_count=2)

        _write(logger, 6)

        assert not (tmp_path / "audit.log.1").exists()
        assert len(_records(path)) == 6

    def test_zero_backups_truncates_instead_of_keeping_history(self, tmp_path):
        path = tmp_path / "audit.log"
        logger = AuditLogger(path, max_bytes=300, backup_count=0)

        _write(logger, 3)

        assert not (tmp_path / "audit.log.1").exists()
        assert len(_records(path)) == 1

    def test_refuses_to_rotate_through_a_symlinked_backup(self, tmp_path, caplog):
        path = tmp_path / "audit.log"
        victim = tmp_path / "victim.log"
        victim.write_text("keep me\n")
        (tmp_path / "audit.log.1").symlink_to(victim)

        logger = AuditLogger(path, max_bytes=300, backup_count=2)
        _write(logger, 4)

        assert victim.read_text() == "keep me\n"
        assert "ROTATION REFUSED" in caplog.text
        # The record is still appended rather than dropped.
        assert _records(path)

    def test_each_line_remains_valid_json_across_files(self, tmp_path):
        path = tmp_path / "audit.log"
        logger = AuditLogger(path, max_bytes=500, backup_count=3)

        _write(logger, 10)

        for candidate in [path, *sorted(tmp_path.glob("audit.log.*"))]:
            for line in candidate.read_text().splitlines():
                json.loads(line)


class TestConfig:
    def test_env_overrides_rotation_settings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COMFYUI_AUDIT_MAX_BYTES", "1234")
        monkeypatch.setenv("COMFYUI_AUDIT_BACKUP_COUNT", "2")

        settings = load_settings(config_path=tmp_path / "missing.yaml")

        assert settings.logging.max_bytes == 1234
        assert settings.logging.backup_count == 2

    def test_negative_values_are_rejected(self):
        from pydantic import ValidationError

        from comfyui_mcp.config import LoggingSettings

        with pytest.raises(ValidationError):
            LoggingSettings(max_bytes=-1)
        with pytest.raises(ValidationError):
            LoggingSettings(backup_count=-1)
