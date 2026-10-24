"""stdio JSON-RPC MCP server for ATLAS research tools: PYTHONPATH=src python scripts/atlas_mcp_stdio.py"""
import json
import sys

from atlas.ext.mcp import handle

for line in sys.stdin:
    if not line.strip():
        continue
    try:
        out = handle(json.loads(line))
    except json.JSONDecodeError:
        out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
    if out is not None:
        sys.stdout.write(json.dumps(out, default=str) + "\n"); sys.stdout.flush()
