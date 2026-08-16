from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from . import __version__
from .output import envelope, render
from .project import resolve_project
from .service import SerenaService
from .skills import install_skills
from .tools import declaration_args, diagnostics_args, edit_args, find_args, implementations_args, overview_args, refs_args


def _common_symbol_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--include-kind", type=int, action="append")
    parser.add_argument("--exclude-kind", type=int, action="append")
    parser.add_argument("--max-chars", type=int, default=-1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="serena-cli", description="Token-light CLI facade over a project-local Serena MCP server.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--project", help="Project root. Defaults to nearest .serena/project.yml or .git ancestor.")
    parser.add_argument("--context", default="ide-assistant", help="Serena context passed to start-mcp-server.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout for one MCP operation.")
    parser.add_argument("--startup-timeout", type=float, default=120.0, help="Timeout for initial Serena/LSP startup.")
    parser.add_argument("--serena-command", help="Command used to launch Serena; env: SERENA_SKILL_SERENA_COMMAND.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    sub = parser.add_subparsers(dest="command", required=True)

    symbol = sub.add_parser("symbol", help="Semantic read operations.")
    sym = symbol.add_subparsers(dest="symbol_command", required=True)

    p = sym.add_parser("overview")
    p.add_argument("path")
    p.add_argument("--depth", type=int, default=-1)
    p.add_argument("--max-chars", type=int, default=-1)
    p.set_defaults(mapper=overview_args)

    p = sym.add_parser("find")
    p.add_argument("name")
    p.add_argument("--path")
    p.add_argument("--depth", type=int, default=0)
    p.add_argument("--body", action="store_true")
    p.add_argument("--info", action="store_true")
    p.add_argument("--substring", action="store_true")
    p.add_argument("--max-matches", type=int, default=-1)
    _common_symbol_filters(p)
    p.set_defaults(mapper=find_args)

    p = sym.add_parser("refs")
    p.add_argument("name")
    p.add_argument("--path", required=True)
    _common_symbol_filters(p)
    p.set_defaults(mapper=refs_args)

    p = sym.add_parser("implementations")
    p.add_argument("name")
    p.add_argument("--path", required=True)
    p.add_argument("--info", action="store_true")
    _common_symbol_filters(p)
    p.set_defaults(mapper=implementations_args)

    p = sym.add_parser("declaration")
    p.add_argument("--path", required=True)
    p.add_argument("--regex", required=True, help="Regex with exactly one capture group around the target symbol.")
    p.add_argument("--within", help="Optional containing symbol name path.")
    p.add_argument("--body", action="store_true")
    p.add_argument("--info", action="store_true")
    p.set_defaults(mapper=declaration_args)

    p = sym.add_parser("diagnostics")
    p.add_argument("path")
    p.add_argument("--start-line", type=int, default=0)
    p.add_argument("--end-line", type=int, default=-1)
    p.add_argument("--min-severity", type=int, choices=(1, 2, 3, 4), default=4)
    p.add_argument("--max-chars", type=int, default=-1)
    p.set_defaults(mapper=diagnostics_args)

    edit = sub.add_parser("edit", help="Semantic edit/refactor operations.")
    edits = edit.add_subparsers(dest="edit_command", required=True)
    p = edits.add_parser("rename")
    p.add_argument("name")
    p.add_argument("new_name")
    p.add_argument("--path", required=True)
    p.set_defaults(mapper=edit_args)
    p = edits.add_parser("safe-delete")
    p.add_argument("name")
    p.add_argument("--path", required=True)
    p.set_defaults(mapper=edit_args)
    for name in ("replace-body", "insert-before", "insert-after"):
        p = edits.add_parser(name)
        p.add_argument("name")
        p.add_argument("--path", required=True)
        body = p.add_mutually_exclusive_group(required=True)
        body.add_argument("--content")
        body.add_argument("--content-file", type=Path)
        p.set_defaults(mapper=edit_args)

    tool = sub.add_parser("tool", help="Escape hatch for Serena tools not wrapped by this CLI.")
    tools = tool.add_subparsers(dest="tool_command", required=True)
    tools.add_parser("list")
    p = tools.add_parser("call")
    p.add_argument("name")
    p.add_argument("--args-json", default="{}", help="JSON object passed as tool arguments.")

    server = sub.add_parser("server", help="Manage the per-project Serena server.")
    servers = server.add_subparsers(dest="server_command", required=True)
    servers.add_parser("start")
    p = servers.add_parser("status")
    p.add_argument(
        "--probe", action="store_true", help="Perform a real MCP request instead of local PID/port checks only."
    )
    servers.add_parser("stop")
    servers.add_parser("restart")
    p = servers.add_parser("logs")
    p.add_argument("--lines", type=int, default=80)

    skill = sub.add_parser("skill", help="Install bundled OpenCode skills into the project.")
    skills = skill.add_subparsers(dest="skill_command", required=True)
    p = skills.add_parser("install")
    p.add_argument("--force", action="store_true")
    return parser


async def _run_async(ns) -> dict:
    project = resolve_project(ns.project)
    service = SerenaService(
        project,
        context=ns.context,
        timeout=ns.timeout,
        startup_timeout=ns.startup_timeout,
        serena_command=ns.serena_command,
    )

    if ns.command == "skill":
        installed = install_skills(project, force=ns.force)
        return envelope(ok=True, result=[str(p) for p in installed], project=str(project))

    if ns.command == "server":
        if ns.server_command == "status":
            return envelope(ok=True, result=await service.status(probe=ns.probe), project=str(project))
        if ns.server_command == "stop":
            service.stop()
            return envelope(ok=True, result={"stopped": True}, project=str(project))
        if ns.server_command == "restart":
            state = await service.restart()
            return envelope(ok=True, result={"pid": state.pid, "url": state.url}, project=str(project))
        if ns.server_command == "logs":
            return envelope(ok=True, result=service.log_tail(ns.lines), project=str(project))
        state = await service.ensure_server()
        return envelope(ok=True, result={"pid": state.pid, "url": state.url}, project=str(project))

    if ns.command in {"symbol", "edit"}:
        tool, arguments = ns.mapper(ns)
        result = await service.call_tool(tool, arguments, retry_safe=ns.command == "symbol")
        return envelope(ok=True, result=result, tool=tool, project=str(project))
    if ns.command == "tool":
        if ns.tool_command == "list":
            result = await service.list_tools()
            return envelope(ok=True, result=result, project=str(project))
        arguments = json.loads(ns.args_json)
        if not isinstance(arguments, dict):
            raise ValueError("--args-json must decode to a JSON object")
        result = await service.call_tool(ns.name, arguments, retry_safe=False)
        return envelope(ok=True, result=result, tool=ns.name, project=str(project))
    raise AssertionError(f"Unhandled command: {ns.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    try:
        data = asyncio.run(_run_async(ns))
        print(render(data, pretty=ns.pretty))
        return 0
    except KeyboardInterrupt:
        print(render(envelope(ok=False, error="Interrupted"), pretty=getattr(ns, "pretty", False)), file=sys.stderr)
        return 130
    except Exception as exc:
        print(render(envelope(ok=False, error=str(exc), error_type=type(exc).__name__), pretty=getattr(ns, "pretty", False)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
