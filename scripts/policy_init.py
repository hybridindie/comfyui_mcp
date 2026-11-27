#!/usr/bin/env python3
"""Suggest an enforce-mode allowlist from the audit log (issue #230).

uv run python scripts/policy_init.py
uv run python scripts/policy_init.py --audit-file ./audit.log --apply
"""

import sys

from comfyui_mcp.policy_init import main

if __name__ == "__main__":
    sys.exit(main())
