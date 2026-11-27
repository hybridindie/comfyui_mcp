#!/usr/bin/env python3
"""Diagnose a ComfyUI MCP configuration, transport, and install (issue #226).

Installed:  comfyui-mcp-doctor [--config PATH] [--url URL] [--json]
Checkout:   uv run python scripts/doctor.py [same options]
"""

import sys

from comfyui_mcp.doctor import main

if __name__ == "__main__":
    sys.exit(main())
