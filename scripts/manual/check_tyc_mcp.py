import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def mask(value: str) -> str:
    value = value or ""
    return value[:8] + "..." if value else ""


def parse_mcp_response(response: requests.Response) -> dict[str, Any]:
    response.encoding = "utf-8"
    content_type = response.headers.get("content-type", "")
    text = response.text.strip()
    if "text/event-stream" in content_type or text.startswith("event:") or text.startswith("data:"):
        payloads = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                data = line.removeprefix("data:").strip()
                if data and data != "[DONE]":
                    payloads.append(data)
        for data in reversed(payloads):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                continue
        return {"raw_sse": text[:2000]}
    try:
        return response.json()
    except ValueError:
        return {"raw": text[:2000]}


class TycMcpClient:
    def __init__(self, url: str, api_key: str, timeout: int = 30):
        self.url = url
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2024-11-05",
            }
        )
        self._id = 0

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            body["params"] = params
        response = self.session.post(self.url, json=body, timeout=self.timeout)
        session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
        if session_id:
            self.session.headers.update({"Mcp-Session-Id": session_id})
        parsed = parse_mcp_response(response)
        if response.status_code >= 400:
            return {"error": f"HTTP {response.status_code}", "response": parsed}
        return parsed

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        try:
            response = self.session.post(self.url, json=body, timeout=self.timeout)
            session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
            if session_id:
                self.session.headers.update({"Mcp-Session-Id": session_id})
        except Exception:
            pass

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "rag-tyc-mcp-test", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized", {})
        return result

    def list_tools(self) -> dict[str, Any]:
        return self.request("tools/list", {})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})


def compact_tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") or {}
    tools = result.get("tools") or payload.get("tools") or []
    return [
        {
            "name": tool.get("name"),
            "description": (tool.get("description") or "")[:220],
            "inputSchema": tool.get("inputSchema") or tool.get("input_schema") or {},
        }
        for tool in tools
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Tianyancha MCP connectivity and tools.")
    parser.add_argument("--tool", default="", help="Optional MCP tool name to call.")
    parser.add_argument("--args", default="{}", help="JSON arguments for --tool.")
    parsed = parser.parse_args()

    api_key = (os.getenv("TYC_API_KEY") or os.getenv("TENC_API_KEY") or "").strip()
    url = os.getenv("TYC_MCP_URL", "https://mcp.tianyancha.com/v1").strip()
    if not api_key:
        print("[ERROR] 请先在 .env 配置 TYC_API_KEY 或 TENC_API_KEY")
        return 1
    print(f"[env] TYC_API_KEY={mask(api_key)}")
    print(f"[env] TYC_MCP_URL={url}")

    try:
        tool_args = json.loads(parsed.args)
        if not isinstance(tool_args, dict):
            raise ValueError("--args must be a JSON object")
    except Exception as exc:
        print(f"[ERROR] --args 不是合法 JSON object: {exc}")
        return 1

    client = TycMcpClient(url, api_key)
    init_payload = client.initialize()
    if init_payload.get("error"):
        print("[ERROR] initialize failed")
        print(json.dumps(init_payload, ensure_ascii=False, indent=2)[:4000])
        return 1
    print("[OK] initialize")

    tools_payload = client.list_tools()
    if tools_payload.get("error"):
        print("[ERROR] tools/list failed")
        print(json.dumps(tools_payload, ensure_ascii=False, indent=2)[:4000])
        return 1
    tools = compact_tools(tools_payload)
    print(f"[OK] tools/list: {len(tools)} tools")
    for item in tools:
        print(f"- {item['name']}: {item['description']}")
        schema = item.get("inputSchema") or {}
        if schema:
            print(f"  inputSchema: {json.dumps(schema, ensure_ascii=False)[:500]}")

    if parsed.tool:
        print(f"\n[CALL] {parsed.tool} args={json.dumps(tool_args, ensure_ascii=False)}")
        result = client.call_tool(parsed.tool, tool_args)
        print(json.dumps(result, ensure_ascii=False, indent=2)[:8000])
        return 0 if not result.get("error") else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
