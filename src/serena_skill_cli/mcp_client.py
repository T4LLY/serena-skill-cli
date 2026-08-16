from __future__ import annotations

import asyncio
import json
from typing import Any

from .errors import MCPCallError, MCPConnectionError, SerenaToolError


def _error_text(data: dict[str, Any]) -> str:
    content = data.get("content")
    if isinstance(content, list):
        texts = [entry.get("text") for entry in content if isinstance(entry, dict) and entry.get("type") == "text"]
        texts = [text for text in texts if isinstance(text, str) and text]
        if texts:
            return "\n".join(texts)
    return str(data)


def _normalize_result(result: Any) -> Any:
    data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
    if not isinstance(data, dict):
        return data
    if data.get("isError") or data.get("is_error"):
        raise SerenaToolError(_error_text(data))
    structured = data.get("structuredContent")
    if structured is None:
        structured = data.get("structured_content")
    if structured is not None:
        return structured
    content = data.get("content")
    if isinstance(content, list):
        texts = [entry.get("text") for entry in content if isinstance(entry, dict) and entry.get("type") == "text"]
        texts = [text for text in texts if isinstance(text, str)]
        if len(texts) == 1:
            text = texts[0]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        if texts and len(texts) == len(content):
            return texts
    return data


class MCPClient:
    def __init__(self, timeout: float = 30.0, health_timeout: float = 3.0):
        self.timeout = timeout
        self.health_timeout = min(health_timeout, timeout)

    async def _session(self, url: str, operation, *, timeout: float | None = None):
        # Lazy imports keep --help and unit tests usable before dependencies are installed.
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def run():
            operation_started = False
            try:
                async with streamable_http_client(url) as (read_stream, write_stream, _get_session_id):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        operation_started = True
                        return await operation(session)
            except (SerenaToolError, asyncio.CancelledError):
                raise
            except Exception as exc:
                if operation_started:
                    raise MCPCallError(
                        f"MCP request failed after it started for {url}: {exc}. "
                        "The tool result may be unknown; mutating calls are not retried automatically."
                    ) from exc
                raise MCPConnectionError(f"MCP connection failed for {url}: {exc}") from exc

        limit = self.timeout if timeout is None else timeout
        try:
            return await asyncio.wait_for(run(), timeout=limit)
        except asyncio.TimeoutError as exc:
            raise MCPCallError(
                f"MCP operation timed out after {limit:g}s for {url}. "
                "The tool result may be unknown; mutating calls are not retried automatically."
            ) from exc

    async def list_tools(self, url: str) -> list[str]:
        async def op(session):
            result = await session.list_tools()
            return [tool.name for tool in result.tools]

        return await self._session(url, op)

    async def is_ready(self, url: str, *, timeout: float | None = None) -> bool:
        try:
            await self._session(url, lambda session: session.list_tools(), timeout=timeout or self.health_timeout)
            return True
        except Exception:
            return False

    async def call_tool(self, url: str, tool: str, arguments: dict[str, Any]) -> Any:
        async def op(session):
            # Deliberately do not list tools first. Missing/disabled tools are
            # surfaced by Serena itself, saving one MCP round trip per CLI call.
            result = await session.call_tool(tool, arguments=arguments)
            return _normalize_result(result)

        return await self._session(url, op)
