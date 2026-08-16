# serena-skill-cli

A thin CLI facade that keeps Serena MCP tool schemas **out of OpenCode's model context** while reusing a persistent, per-project Serena MCP/LSP backend.

## Architecture

```text
OpenCode -> shell -> serena-cli -> localhost Streamable HTTP MCP -> Serena -> LSP
```

OpenCode must **not** also register Serena as an MCP server, otherwise the fixed tool-schema token cost remains.

Each project gets one automatically managed Serena server. The CLI stores only PID/port/url state under the user state directory; project source is never copied there.

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
pytest -q -m "not integration"
```

The integration test is opt-in and requires Serena:

```powershell
pytest -q -m integration
```

## Runtime behavior and performance

For an already-running project daemon, a normal semantic query uses the fast path:

```text
state/PID check -> one MCP session -> initialize -> call_tool
```

It does **not** perform `list_tools` or a second MCP readiness session before every tool call. `server status` and explicit `tool list` still perform a real MCP probe.

Initial Serena/LSP startup has its own timeout (`--startup-timeout`, default 120 seconds), separate from normal MCP operation timeout (`--timeout`, default 30 seconds). This matters for large Unity/C#/Java repositories where language-server initialization can legitimately exceed 30 seconds.

Read-only calls may recover once if a stale daemon disappears. Mutating calls are never automatically retried after an ambiguous in-flight failure, preventing duplicate inserts/renames/deletes when the edit may already have been applied.

To measure warm-call latency on PowerShell:

```powershell
Measure-Command { serena-cli symbol find SerenaService --path src/serena_skill_cli/service.py }
```

## State and concurrency

- Windows: `%LOCALAPPDATA%\serena-skill-cli\projects\<project-id>`
- POSIX: `$XDG_STATE_HOME/serena-skill-cli/projects/<project-id>` or `~/.local/state/...`
- per-project file lock prevents duplicate Serena processes for the same repository
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
