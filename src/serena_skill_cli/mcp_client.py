from __future__ import annotations

import asyncio
import json
from typing import Any

from .errors import ToolUnavailableError


def _normalize_result(result: Any) -> Any:
    data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
    if not isinstance(data, dict):
        return data
    if data.get("isError") or data.get("is_error"):
        raise RuntimeError(f"Serena tool returned an error: {data}")
    structured = data.get("structuredContent") or data.get("structured_content")
    if structured is not None:
        return structured
    content = data.get("content")
    if isinstance(content, list):
        texts = [entry.get("text") for entry in content if isinstance(entry, dict) and entry.get("type") == "text"]
        if len(texts) == 1 and isinstance(texts[0], str):
            text = texts[0]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return data


class MCPClient:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def _session(self, url: str, operation):
        # Lazy imports keep unit tests and --help usable before dependencies are installed.
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def run():
            async with streamable_http_client(url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await operation(session)

        return await asyncio.wait_for(run(), timeout=self.timeout)

    async def list_tools(self, url: str) -> list[str]:
        async def op(session):
            result = await session.list_tools()
            return [tool.name for tool in result.tools]

        return await self._session(url, op)

    async def is_ready(self, url: str) -> bool:
        try:
            await self.list_tools(url)
            return True
        except Exception:
            return False

    async def call_tool(self, url: str, tool: str, arguments: dict[str, Any]) -> Any:
        async def op(session):
            listing = await session.list_tools()
            available = {item.name for item in listing.tools}
            if tool not in available:
                raise ToolUnavailableError(
                    f"Serena tool '{tool}' is unavailable in the active context/modes. "
                    f"Available: {', '.join(sorted(available))}"
                )
            result = await session.call_tool(tool, arguments=arguments)
            return _normalize_result(result)

        return await self._session(url, op)
