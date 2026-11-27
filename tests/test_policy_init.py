"""Policy-init helper (issue #230)."""

from __future__ import annotations

import json

import yaml

from comfyui_mcp.policy_init import (
    apply_to_config,
    build_suggestions,
    collect_usage,
    main,
    render_fragment,
)


def _record(timestamp: str, nodes: list[str]) -> str:
    return json.dumps(
        {
            "timestamp": timestamp,
            "tool": "run_workflow",
            "action": "inspected",
            "nodes_used": nodes,
        }
    )


def _audit(tmp_path, *lines: str):
    path = tmp_path / "audit.log"
    path.write_text("\n".join(lines) + "\n")
    return path


class TestCollectUsage:
    def test_counts_each_workflow_once_and_tracks_window(self, tmp_path):
        path = _audit(
            tmp_path,
            _record("2026-01-01T00:00:00+00:00", ["A", "B", "A"]),
            _record("2026-01-02T00:00:00+00:00", ["A", "C"]),
            json.dumps({"tool": "x", "action": "called"}),
        )

        usage, inspections, skipped = collect_usage(path)

        assert inspections == 2
        assert skipped == 0
        assert usage["A"].count == 2
        assert usage["A"].first_seen == "2026-01-01T00:00:00+00:00"
        assert usage["A"].last_seen == "2026-01-02T00:00:00+00:00"
        assert usage["B"].count == 1
        assert usage["C"].count == 1

    def test_skips_malformed_lines(self, tmp_path):
        path = _audit(tmp_path, "not-json", _record("2026-01-01T00:00:00+00:00", ["A"]))

        _, inspections, skipped = collect_usage(path)

        assert inspections == 1
        assert skipped == 1

    def test_ignores_records_without_nodes(self, tmp_path):
        path = _audit(
            tmp_path,
            json.dumps({"timestamp": "2026-01-01T00:00:00+00:00", "tool": "x"}),
        )

        _, inspections, _ = collect_usage(path)

        assert inspections == 0


class TestSuggestions:
    def _usage(self, tmp_path):
        path = _audit(
            tmp_path,
            _record("2026-01-01T00:00:00+00:00", ["A", "B", "ExecutePython"]),
            _record("2026-01-02T00:00:00+00:00", ["A"]),
        )
        usage, _, _ = collect_usage(path)
        return usage

    def test_dangerous_nodes_are_excluded(self, tmp_path):
        suggestions = build_suggestions(
            self._usage(tmp_path),
            blocked_nodes=["ExecutePython"],
            current_allowlist=["A"],
        )

        assert set(suggestions.allowlist) == {"A", "B"}
        assert set(suggestions.dangerous_seen) == {"ExecutePython"}

    def test_never_seen_entries_are_flagged(self, tmp_path):
        suggestions = build_suggestions(
            self._usage(tmp_path),
            blocked_nodes=[],
            current_allowlist=["A", "Old"],
        )

        assert suggestions.never_seen == ["Old"]

    def test_min_count_filters(self, tmp_path):
        suggestions = build_suggestions(
            self._usage(tmp_path),
            blocked_nodes=[],
            current_allowlist=[],
            min_count=2,
        )

        assert set(suggestions.allowlist) == {"A"}

    def test_render_fragment_is_valid_yaml(self, tmp_path):
        suggestions = build_suggestions(
            self._usage(tmp_path),
            blocked_nodes=["ExecutePython"],
            current_allowlist=[],
        )

        parsed = yaml.safe_load(render_fragment(suggestions))

        assert parsed["security"]["allowed_nodes"] == ["A", "B"]


class TestApply:
    def test_writes_allowlist_and_keeps_a_backup(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(
            "security:\n  mode: audit\n  allowed_nodes: [Old]\n  dangerous_nodes: [X]\n"
        )

        backup = apply_to_config(config, ["A", "B"])

        assert backup is not None and backup.exists()
        parsed = yaml.safe_load(config.read_text())
        assert parsed["security"]["allowed_nodes"] == ["A", "B"]
        assert parsed["security"]["mode"] == "audit"
        assert parsed["security"]["dangerous_nodes"] == ["X"]

    def test_creates_a_config_when_missing(self, tmp_path):
        config = tmp_path / "nested" / "config.yaml"

        backup = apply_to_config(config, ["A"])

        assert backup is None
        assert yaml.safe_load(config.read_text())["security"]["allowed_nodes"] == ["A"]


class TestMain:
    def test_missing_audit_file_exits_nonzero(self, tmp_path, capsys):
        code = main(["--audit-file", str(tmp_path / "missing.log")])

        assert code == 1
        assert "not found" in capsys.readouterr().err

    def test_dry_run_prints_fragment(self, tmp_path, capsys):
        audit = _audit(tmp_path, _record("2026-01-01T00:00:00+00:00", ["A"]))
        config = tmp_path / "config.yaml"

        code = main(["--audit-file", str(audit), "--config", str(config)])

        out = capsys.readouterr().out
        assert code == 0
        assert "security:" in out
        assert "Re-run with --apply" in out
        assert not config.exists()

    def test_apply_writes_config(self, tmp_path, capsys):
        audit = _audit(tmp_path, _record("2026-01-01T00:00:00+00:00", ["A"]))
        config = tmp_path / "config.yaml"

        code = main(["--audit-file", str(audit), "--config", str(config), "--apply"])

        assert code == 0
        assert "Updated" in capsys.readouterr().out
        assert yaml.safe_load(config.read_text())["security"]["allowed_nodes"] == ["A"]
