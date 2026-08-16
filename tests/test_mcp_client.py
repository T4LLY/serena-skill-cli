from dataclasses import dataclass
import json

import pytest

import serena_skill_cli.mcp_client as mcp_client_module
from serena_skill_cli.errors import MCPSessionExpiredError, SerenaToolError
from serena_skill_cli.mcp_client import MCPClient, _normalize_result


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
async def test_initialize_session_keeps_server_session_alive(monkeypatch):
    import sys
    import types
    from contextlib import asynccontextmanager

    read_stream = object()
    write_stream = object()
    observed = {}

    @asynccontextmanager
    async def fake_streamable_http_client(url, *, terminate_on_close=True):
        observed["url"] = url
        observed["terminate_on_close"] = terminate_on_close
        yield read_stream, write_stream, lambda: "session-id"

    class InitResult:
        protocolVersion = "2025-06-18"

    class FakeClientSession:
        def __init__(self, read, write):
            assert read is read_stream
            assert write is write_stream

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            return InitResult()

    mcp_module = types.ModuleType("mcp")
    mcp_module.ClientSession = FakeClientSession
    mcp_client_package = types.ModuleType("mcp.client")
    streamable_module = types.ModuleType("mcp.client.streamable_http")
    streamable_module.streamable_http_client = fake_streamable_http_client
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_package)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_module)

    info = await MCPClient(timeout=1).initialize_session("http://127.0.0.1:19400/mcp")

    assert info.session_id == "session-id"
    assert info.protocol_version == "2025-06-18"
    assert observed == {
        "url": "http://127.0.0.1:19400/mcp",
        "terminate_on_close": False,
    }


class FakeHTTPResponse:
    def __init__(self, status: int, content_type: str, body: bytes = b"", lines: list[bytes] | None = None):
        self.status = status
        self._content_type = content_type
        self._body = body
        self._lines = list(lines or [])

    def getheader(self, name: str, default=None):
        if name.lower() == "content-type":
            return self._content_type
        return default

    def read(self):
        return self._body

    def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class RecordingConnection:
    response_factory = None
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.method = None
        self.target = None
        self.body = None
        self.headers = None
        self.connected = False
        self.closed = False
        type(self).instances.append(self)

    def connect(self):
        self.connected = True

    def request(self, method, target, body, headers):
        self.method = method
        self.target = target
        self.body = body
        self.headers = headers

    def getresponse(self):
        assert self.response_factory is not None
        return type(self).response_factory(self)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_recording_connection():
    RecordingConnection.instances = []
    RecordingConnection.response_factory = None


@pytest.mark.asyncio
async def test_cached_call_is_one_direct_http_post_with_session_headers(monkeypatch):
    def response_factory(connection):
        request = json.loads(connection.body)
        result = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"content": [{"type": "text", "text": "[]"}], "isError": False},
        }
        return FakeHTTPResponse(200, "application/json", json.dumps(result).encode())

    RecordingConnection.response_factory = response_factory
    monkeypatch.setattr(mcp_client_module, "HTTPConnection", RecordingConnection)

    result = await MCPClient(timeout=2).call_tool(
        "http://127.0.0.1:19400/mcp",
        "find_symbol",
        {"name_path_pattern": "Foo"},
        session_id="cached-session",
        protocol_version="2025-06-18",
    )

    assert result == []
    assert len(RecordingConnection.instances) == 1
    connection = RecordingConnection.instances[0]
    request = json.loads(connection.body)
    assert connection.method == "POST"
    assert connection.target == "/mcp"
    assert connection.headers["Mcp-Session-Id"] == "cached-session"
    assert connection.headers["MCP-Protocol-Version"] == "2025-06-18"
    assert request["method"] == "tools/call"
    assert request["params"] == {"name": "find_symbol", "arguments": {"name_path_pattern": "Foo"}}
    assert connection.closed is True


@pytest.mark.asyncio
async def test_cached_call_parses_sse_response(monkeypatch):
    def response_factory(connection):
        request_id = json.loads(connection.body)["id"]
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": '{"ok":true}'}]},
            }
        )
        return FakeHTTPResponse(
            200,
            "text/event-stream; charset=utf-8",
            lines=[b"event: message\n", f"data: {payload}\n".encode(), b"\n"],
        )

    RecordingConnection.response_factory = response_factory
    monkeypatch.setattr(mcp_client_module, "HTTPConnection", RecordingConnection)

    result = await MCPClient(timeout=2).call_tool(
        "http://127.0.0.1:19400/mcp",
        "find_symbol",
        {},
        session_id="cached-session",
        protocol_version="2025-06-18",
    )
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_cached_session_404_is_explicitly_recoverable(monkeypatch):
    RecordingConnection.response_factory = lambda _connection: FakeHTTPResponse(
        404,
        "application/json",
        b'{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Session not found"}}',
    )
    monkeypatch.setattr(mcp_client_module, "HTTPConnection", RecordingConnection)

    with pytest.raises(MCPSessionExpiredError):
        await MCPClient(timeout=2).call_tool(
            "http://127.0.0.1:19400/mcp",
            "find_symbol",
            {},
            session_id="expired",
            protocol_version="2025-06-18",
        )


@pytest.mark.asyncio
async def test_cached_list_tools_uses_direct_request(monkeypatch):
    def response_factory(connection):
        request = json.loads(connection.body)
        payload = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"tools": [{"name": "find_symbol"}, {"name": "get_symbols_overview"}]},
        }
        return FakeHTTPResponse(200, "application/json", json.dumps(payload).encode())

    RecordingConnection.response_factory = response_factory
    monkeypatch.setattr(mcp_client_module, "HTTPConnection", RecordingConnection)

    tools = await MCPClient(timeout=2).list_tools(
        "http://127.0.0.1:19400/mcp",
        session_id="cached",
        protocol_version="2025-06-18",
    )
    assert tools == ["find_symbol", "get_symbols_overview"]
    assert json.loads(RecordingConnection.instances[0].body)["method"] == "tools/list"


@pytest.mark.asyncio
async def test_fallback_call_tool_does_not_list_tools_first(monkeypatch):
    import sys
    import types
    from contextlib import asynccontextmanager

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
            raise AssertionError("fallback call_tool path must not list tools explicitly")

    mcp_module = types.ModuleType("mcp")
    mcp_module.ClientSession = FakeClientSession
    mcp_client_package = types.ModuleType("mcp.client")
    streamable_module = types.ModuleType("mcp.client.streamable_http")
    streamable_module.streamable_http_client = fake_streamable_http_client
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_package)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_module)

    result = await MCPClient(timeout=1).call_tool(
        "http://127.0.0.1:19400/mcp", "find_symbol", {"name_path_pattern": "Foo"}
    )
    assert result == []
