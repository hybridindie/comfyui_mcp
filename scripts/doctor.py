#!/usr/bin/env python3
"""Diagnose a ComfyUI MCP configuration, transport, and install (issue #226).

uv run python scripts/doctor.py
uv run python scripts/doctor.py --url http://gpu-box:8188
uv run python scripts/doctor.py --json
"""

import sys

from comfyui_mcp.doctor import main

if __name__ == "__main__":
    sys.exit(main())
