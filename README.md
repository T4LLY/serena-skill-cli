# serena-skill-cli

A thin CLI facade that keeps Serena MCP tool schemas **out of OpenCode's model context** while reusing a persistent, per-project Serena MCP/LSP backend.

## Architecture

```text
OpenCode -> shell -> serena-cli -> localhost Streamable HTTP MCP -> Serena -> LSP
```

OpenCode must **not** also register Serena as an MCP server, otherwise the fixed tool-schema token cost remains.

Each project gets one automatically managed Serena server. The CLI stores PID/port/url plus the negotiated MCP session ID/protocol version under the user state directory; project source is never copied there. No additional bridge daemon is created.

## Requirements

- Python 3.11-3.14
- Serena installed and initialized
- `serena` available on PATH (or set `SERENA_SKILL_SERENA_COMMAND`)

Current Serena installation:

```powershell
uv tool install -p 3.13 serena-agent
serena init
```

## Install this CLI

From this directory:

```powershell
uv tool install .
```

For development:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Both `serena-cli` and `serena-skill` are installed as aliases.

## Install the OpenCode skills

Run from a project directory:

```powershell
serena-cli skill install
```

This creates:

```text
.opencode/skills/serena-read/SKILL.md
.opencode/skills/serena-edit/SKILL.md
```

Use `--force` to update an existing copy.

## Examples

```powershell
serena-cli --pretty symbol overview Packages/com.example/Editor/Foo.cs
serena-cli symbol find Foo/Bar --path Packages/com.example/Editor/Foo.cs
serena-cli symbol find Foo/Bar --path Packages/com.example/Editor/Foo.cs --body
serena-cli symbol refs Foo/Bar --path Packages/com.example/Editor/Foo.cs
serena-cli symbol implementations IFoo/Run --path Packages/com.example/Runtime/IFoo.cs
serena-cli symbol diagnostics Packages/com.example/Editor/Foo.cs

serena-cli edit rename Foo/Bar Baz --path Packages/com.example/Editor/Foo.cs
serena-cli edit replace-body Foo/Bar --path Packages/com.example/Editor/Foo.cs --content-file body.txt

serena-cli --pretty server status
serena-cli --pretty server status --probe
serena-cli --pretty server logs
serena-cli server stop
```

Global options must come before the command, e.g.:

```powershell
serena-cli --project C:\src\MyProject --timeout 60 --startup-timeout 180 symbol find Foo
```

## Serena launch override

Default launch command is `serena`. To use another installation form:

```powershell
$env:SERENA_SKILL_SERENA_COMMAND = 'C:\path\to\serena.exe'
```

Windows paths containing spaces are also supported when the executable is quoted inside the command value:

```powershell
$env:SERENA_SKILL_SERENA_COMMAND = '"C:\Program Files\Serena\serena.exe"'
```

or:

```powershell
serena-cli --serena-command 'uv run serena' server start
```

The wrapper starts Serena as:

```text
serena start-mcp-server --transport streamable-http --host 127.0.0.1 --port <port> --project <root> --context ide-assistant
```

and explicitly disables dashboard/browser/gui-log startup for the background instance.

On Windows, the Serena process is created with `CREATE_NO_WINDOW` and a hidden `STARTUPINFO`; no helper CMD window should appear when OpenCode invokes `serena-cli`.

## Project resolution

1. explicit `--project`
2. nearest ancestor containing `.serena/project.yml` or `.git`
3. current directory

This mirrors Serena's current nearest-project behavior for normal repositories.

## Raw escape hatch

New/optional Serena tools can be used without waiting for a wrapper release:

```powershell
serena-cli --pretty tool list
serena-cli tool call get_current_config --args-json '{}'
```

The high-level Skills intentionally do not advertise all tools, preserving progressive disclosure.

## Tests

Unit tests do not require a running Serena server:

```powershell
uv run --extra dev pytest -q -m "not integration"
```

The integration test is opt-in and requires Serena:

```powershell
uv run --extra dev pytest -q -m integration
```

## Runtime behavior and performance

The first MCP connection for a project uses the official MCP Python SDK to negotiate the protocol and create a server-side session. The transport is closed **without terminating that MCP session**, and the negotiated session ID/version are persisted beside the Serena PID.

Subsequent semantic calls use the warm path:

```text
state/PID check -> one localhost HTTP POST -> tools/call -> result
```

The warm path does not create a new `ClientSession`, does not run `initialize`, and does not call `tools/list`. It uses Python's standard-library HTTP client, so there is no resident bridge process and no extra HTTP-client dependency.

If Serena returns HTTP 404 for an expired/unknown MCP session, the CLI re-initializes only the MCP session while keeping the Serena/LSP process alive, then retries once. This retry is safe for edit tools because Serena rejects an unknown session before dispatching the request. Ambiguous in-flight edit failures are still never retried automatically.

`server status` is intentionally local and fast: it checks state, PID, and listening port only. Use `server status --probe` when you explicitly want a real MCP request.

Initial Serena/LSP startup has its own timeout (`--startup-timeout`, default 120 seconds), separate from normal MCP operation timeout (`--timeout`, default 30 seconds). Tool calls made while a newly started server is still inside that startup window inherit the remaining startup-timeout budget, so background language-server initialization remains covered even after MCP `initialize` has completed. This matters for large Unity/C#/Java repositories where language-server initialization can legitimately exceed 30 seconds.

Persisted server state records an OS-derived process identity for newly started Serena processes. Stop/restart only terminates a persisted PID when that identity still matches; legacy state without an identity token is removed without killing a process based on PID alone.

To measure warm-call latency on PowerShell:

```powershell
Measure-Command { serena-cli symbol find SerenaService --path src/serena_skill_cli/service.py }
```

After upgrading from 0.1.2, an existing live Serena process is reused. The first 0.1.3 call adds the cached MCP session fields to `state.json`; Serena/LSP does not need to restart.

## State and concurrency

- Windows: `%LOCALAPPDATA%\serena-skill-cli\projects\<project-id>`
- POSIX: `$XDG_STATE_HOME/serena-skill-cli/projects/<project-id>` or `~/.local/state/...`
- per-project file lock prevents duplicate Serena processes and serializes MCP-session creation/refresh for the same repository
- a global port-allocation lock prevents simultaneous projects from choosing the same local port during startup
- stale PID/state is replaced automatically
- Windows PID liveness uses Win32 process handles; it does not use `os.kill(pid, 0)`
- mismatched/corrupt state is removed without killing an unrelated PID

## Compatibility boundary

The wrapper depends only on:

- Serena's public CLI launch arguments
- Streamable HTTP MCP
- the named Serena tools and their public MCP arguments

It does not import Serena's internal Python modules. High-level calls go directly to the named Serena tool to avoid an extra `list_tools` round trip. Use `serena-cli tool list` when diagnosing tools disabled by the active Serena context/modes.
