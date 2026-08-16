from dataclasses import dataclass

import pytest

from serena_skill_cli.errors import SerenaToolError
from serena_skill_cli.mcp_client import _normalize_result


@dataclass
class FakeResult:
    data: dict

    def model_dump(self, **_kwargs):
        return self.data


def test_normalize_single_json_text():
    result = FakeResult({"content": [{"type": "text", "text": '{"value":1}'}], "isError": False})
    assert _normalize_result(result) == {"value": 1}


def test_normalize_single_plain_text():
    result = FakeResult({"content": [{"type": "text", "text": "OK"}]})
    assert _normalize_result(result) == "OK"


def test_normalize_empty_structured_content_is_preserved():
    result = FakeResult({"structuredContent": {}, "content": [{"type": "text", "text": "fallback"}]})
    assert _normalize_result(result) == {}


def test_normalize_error_raises_concise_tool_error():
    with pytest.raises(SerenaToolError, match="bad symbol"):
        _normalize_result(FakeResult({"isError": True, "content": [{"type": "text", "text": "bad symbol"}]}))


@pytest.mark.asyncio
async def test_session_accepts_mcp_1_28_three_value_transport(monkeypatch):
    import sys
    import types
    from contextlib import asynccontextmanager

    from serena_skill_cli.mcp_client import MCPClient

    read_stream = object()
    write_stream = object()

    @asynccontextmanager
    async def fake_streamable_http_client(url):
        assert url == "http://127.0.0.1:19400/mcp"
        yield read_stream, write_stream, lambda: "session-id"

    class FakeClientSession:
        def __init__(self, read, write):
            assert read is read_stream
            assert write is write_stream
            self.initialized = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            self.initialized = True

    mcp_module = types.ModuleType("mcp")
    mcp_module.ClientSession = FakeClientSession
    mcp_client_module = types.ModuleType("mcp.client")
    streamable_module = types.ModuleType("mcp.client.streamable_http")
    streamable_module.streamable_http_client = fake_streamable_http_client

    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_module)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_module)

    async def operation(session):
        return session.initialized

    client = MCPClient(timeout=1)
    assert await client._session("http://127.0.0.1:19400/mcp", operation) is True


@pytest.mark.asyncio
async def test_call_tool_does_not_list_tools_first(monkeypatch):
    import sys
    import types
    from contextlib import asynccontextmanager

    from serena_skill_cli.mcp_client import MCPClient

    @asynccontextmanager
    async def fake_streamable_http_client(_url):
        yield object(), object(), lambda: "session-id"

    class FakeClientSession:
        def __init__(self, _read, _write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            return None

        async def call_tool(self, name, arguments):
            assert name == "find_symbol"
            assert arguments == {"name_path_pattern": "Foo"}
            return FakeResult({"content": [{"type": "text", "text": "[]"}]})

        async def list_tools(self):
            raise AssertionError("call_tool fast path must not list tools")

    mcp_module = types.ModuleType("mcp")
    mcp_module.ClientSession = FakeClientSession
    mcp_client_module = types.ModuleType("mcp.client")
    streamable_module = types.ModuleType("mcp.client.streamable_http")
    streamable_module.streamable_http_client = fake_streamable_http_client
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_module)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_module)

    result = await MCPClient(timeout=1).call_tool(
        "http://127.0.0.1:19400/mcp", "find_symbol", {"name_path_pattern": "Foo"}
    )
    assert result == []
