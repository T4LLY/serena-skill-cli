from __future__ import annotations

from typing import Any


def overview_args(ns) -> tuple[str, dict[str, Any]]:
    return "get_symbols_overview", {"relative_path": ns.path, "depth": ns.depth, "max_answer_chars": ns.max_chars}


def find_args(ns) -> tuple[str, dict[str, Any]]:
    return "find_symbol", {
        "name_path_pattern": ns.name,
        "depth": ns.depth,
        "relative_path": ns.path or "",
        "include_body": ns.body,
        "include_info": ns.info,
        "include_kinds": ns.include_kind or [],
        "exclude_kinds": ns.exclude_kind or [],
        "substring_matching": ns.substring,
        "max_matches": ns.max_matches,
        "max_answer_chars": ns.max_chars,
    }


def refs_args(ns) -> tuple[str, dict[str, Any]]:
    return "find_referencing_symbols", {
        "name_path": ns.name,
        "relative_path": ns.path,
        "include_kinds": ns.include_kind or [],
        "exclude_kinds": ns.exclude_kind or [],
        "max_answer_chars": ns.max_chars,
    }


def implementations_args(ns) -> tuple[str, dict[str, Any]]:
    return "find_implementations", {
        "name_path": ns.name,
        "relative_path": ns.path,
        "include_info": ns.info,
        "include_kinds": ns.include_kind or [],
        "exclude_kinds": ns.exclude_kind or [],
        "max_answer_chars": ns.max_chars,
    }


def declaration_args(ns) -> tuple[str, dict[str, Any]]:
    return "find_declaration", {
        "relative_path": ns.path,
        "regex": ns.regex,
        "containing_symbol_name_path": ns.within,
        "include_body": ns.body,
        "include_info": ns.info,
    }


def diagnostics_args(ns) -> tuple[str, dict[str, Any]]:
    return "get_diagnostics_for_file", {
        "relative_path": ns.path,
        "start_line": ns.start_line,
        "end_line": ns.end_line,
        "min_severity": ns.min_severity,
        "max_answer_chars": ns.max_chars,
    }


def edit_args(ns) -> tuple[str, dict[str, Any]]:
    if ns.edit_command == "rename":
        return "rename_symbol", {"name_path": ns.name, "relative_path": ns.path, "new_name": ns.new_name}
    if ns.edit_command == "safe-delete":
        return "safe_delete_symbol", {"name_path_pattern": ns.name, "relative_path": ns.path}
    body = _read_body(ns)
    mapping = {
        "replace-body": "replace_symbol_body",
        "insert-before": "insert_before_symbol",
        "insert-after": "insert_after_symbol",
    }
    return mapping[ns.edit_command], {"name_path": ns.name, "relative_path": ns.path, "body": body}


def _read_body(ns) -> str:
    if ns.content is not None:
        return ns.content
    if ns.content_file is None:
        raise ValueError("Either --content or --content-file is required")
    return ns.content_file.read_text(encoding="utf-8")
