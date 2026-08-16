from __future__ import annotations

import asyncio
import json
import socket
import uuid
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPResponse
from typing import Any
from urllib.parse import urlsplit

from .errors import MCPCallError, MCPConnectionError, MCPSessionExpiredError, SerenaToolError


@dataclass(frozen=True)
class MCPSessionInfo:
    session_id: str | None
    protocol_version: str


class _MissingResponse:
    pass


_MISSING = _MissingResponse()


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


def _jsonrpc_result(payload: Any, request_id: str) -> Any | _MissingResponse:
    if not isinstance(payload, dict):
        raise MCPCallError(f"MCP returned a non-object JSON-RPC payload: {payload!r}")
    if payload.get("id") != request_id:
        return _MISSING
    if "error" in payload:
        error = payload["error"]
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message", "MCP request failed")
            details = error.get("data")
            suffix = f" ({details})" if details is not None else ""
            raise SerenaToolError(f"MCP error {code}: {message}{suffix}")
        raise SerenaToolError(f"MCP error: {error}")
    if "result" not in payload:
        raise MCPCallError(f"MCP response has neither result nor error: {payload!r}")
    return payload["result"]


def _read_sse_response(response: HTTPResponse, request_id: str) -> Any:
    data_lines: list[str] = []

    def dispatch() -> Any | _MissingResponse:
        if not data_lines:
            return _MISSING
        raw = "\n".join(data_lines)
        data_lines.clear()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MCPCallError(f"Invalid JSON in MCP SSE response: {raw[:200]!r}") from exc
        return _jsonrpc_result(payload, request_id)

    while True:
        raw_line = response.readline()
        if not raw_line:
            result = dispatch()
            if result is not _MISSING:
                return result
            break
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            result = dispatch()
            if result is not _MISSING:
                return result
            continue
        if line.startswith(":"):
            continue
        field, sep, value = line.partition(":")
        if sep and field == "data":
            data_lines.append(value[1:] if value.startswith(" ") else value)

    raise MCPCallError("MCP SSE stream ended before the matching JSON-RPC response arrived")


class MCPClient:
    def __init__(self, timeout: float = 30.0, health_timeout: float = 3.0):
        self.timeout = timeout
        self.health_timeout = min(health_timeout, timeout)

    async def _legacy_session(self, url: str, operation, *, timeout: float | None = None):
        """Use the official SDK for cold/fallback calls.

        Warm calls use a cached MCP session ID and one direct local HTTP POST.
        """
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

    async def initialize_session(self, url: str, *, timeout: float | None = None) -> MCPSessionInfo:
        """Create one persistent server-side MCP session without keeping a client daemon."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def run() -> MCPSessionInfo:
            try:
                async with streamable_http_client(url, terminate_on_close=False) as (
                    read_stream,
                    write_stream,
                    get_session_id,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        result = await session.initialize()
                        return MCPSessionInfo(
                            session_id=get_session_id(),
                            protocol_version=str(result.protocolVersion),
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise MCPConnectionError(f"MCP initialization failed for {url}: {exc}") from exc

        limit = self.timeout if timeout is None else timeout
        try:
            return await asyncio.wait_for(run(), timeout=limit)
        except asyncio.TimeoutError as exc:
            raise MCPConnectionError(f"MCP initialization timed out after {limit:g}s for {url}") from exc

    def _direct_request_sync(
        self,
        url: str,
        session_id: str,
        protocol_version: str,
        method: str,
        params: dict[str, Any] | None,
        *,
        timeout: float,
    ) -> Any:
        parts = urlsplit(url)
        if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise MCPConnectionError(f"Cached-session fast path only supports local HTTP MCP URLs: {url}")
        port = parts.port or 80
        target = parts.path or "/"
        if parts.query:
            target += f"?{parts.query}"

        request_id = uuid.uuid4().hex
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Mcp-Session-Id": session_id,
            "MCP-Protocol-Version": protocol_version,
            "Content-Length": str(len(body)),
        }

        connection = HTTPConnection(parts.hostname, port, timeout=timeout)
        try:
            try:
                connection.connect()
            except (ConnectionError, OSError, socket.timeout) as exc:
                raise MCPConnectionError(f"MCP connection failed for {url}: {exc}") from exc

            request_started = False
            try:
                request_started = True
                connection.request("POST", target, body=body, headers=headers)
                response = connection.getresponse()
                if response.status == 404:
                    response.read()
                    raise MCPSessionExpiredError(f"Cached MCP session expired for {url}")
                if response.status >= 400:
                    text = response.read().decode("utf-8", errors="replace")
                    raise MCPCallError(f"MCP HTTP {response.status} for {url}: {text[:500]}")

                content_type = response.getheader("content-type", "").split(";", 1)[0].strip().lower()
                if content_type == "application/json":
                    raw = response.read()
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise MCPCallError(f"Invalid JSON MCP response: {raw[:200]!r}") from exc
                    result = _jsonrpc_result(parsed, request_id)
                    if result is _MISSING:
                        raise MCPCallError("MCP JSON response did not match the request ID")
                    return result
                if content_type == "text/event-stream":
                    return _read_sse_response(response, request_id)
                raw = response.read()
                raise MCPCallError(
                    f"Unexpected MCP content type {content_type!r} for {url}: {raw[:200]!r}"
                )
            except (MCPSessionExpiredError, SerenaToolError, MCPCallError):
                raise
            except (ConnectionError, OSError, socket.timeout) as exc:
                if request_started:
                    raise MCPCallError(
                        f"MCP request failed after it started for {url}: {exc}. "
                        "The tool result may be unknown; mutating calls are not retried automatically."
                    ) from exc
                raise MCPConnectionError(f"MCP connection failed for {url}: {exc}") from exc
        finally:
            connection.close()

    async def _cached_request(
        self,
        url: str,
        session_id: str,
        protocol_version: str,
        method: str,
        params: dict[str, Any] | None,
        *,
        timeout: float | None = None,
    ) -> Any:
        # The CLI performs one local request at a time. Keeping this synchronous
        # avoids a second resident process and avoids importing a large async HTTP
        # client on every warm invocation.
        return self._direct_request_sync(
            url,
            session_id,
            protocol_version,
            method,
            params,
            timeout=self.timeout if timeout is None else timeout,
        )

    async def list_tools(
        self,
        url: str,
        *,
        session_id: str | None = None,
        protocol_version: str | None = None,
    ) -> list[str]:
        if session_id and protocol_version:
            result = await self._cached_request(url, session_id, protocol_version, "tools/list", {})
            tools = result.get("tools", []) if isinstance(result, dict) else []
            return [tool["name"] for tool in tools if isinstance(tool, dict) and isinstance(tool.get("name"), str)]

        async def op(session):
            result = await session.list_tools()
            return [tool.name for tool in result.tools]

        return await self._legacy_session(url, op)

    async def is_ready(
        self,
        url: str,
        *,
        session_id: str | None = None,
        protocol_version: str | None = None,
        timeout: float | None = None,
    ) -> bool:
        try:
            if session_id and protocol_version:
                await self._cached_request(
                    url,
                    session_id,
                    protocol_version,
                    "tools/list",
                    {},
                    timeout=timeout or self.health_timeout,
                )
            else:
                await self._legacy_session(
                    url,
                    lambda session: session.list_tools(),
                    timeout=timeout or self.health_timeout,
                )
            return True
        except Exception:
            return False

    async def call_tool(
        self,
        url: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        session_id: str | None = None,
        protocol_version: str | None = None,
    ) -> Any:
        if session_id and protocol_version:
            result = await self._cached_request(
                url,
                session_id,
                protocol_version,
                "tools/call",
                {"name": tool, "arguments": arguments},
            )
            return _normalize_result(result)

        async def op(session):
            result = await session.call_tool(tool, arguments=arguments)
            return _normalize_result(result)

        return await self._legacy_session(url, op)
