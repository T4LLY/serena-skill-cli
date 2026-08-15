---
name: serena-read
description: Use Serena semantic code navigation and diagnostics through the token-light serena-cli instead of exposing Serena MCP tools directly to OpenCode.
---

# Serena Read

Use `serena-cli` when semantic code understanding is more appropriate than raw grep or reading whole files.

Prefer the smallest query that answers the question:

```text
serena-cli symbol overview <file>
serena-cli symbol find <name-path> [--path <file-or-dir>] [--body] [--info]
serena-cli symbol refs <name-path> --path <defining-file>
serena-cli symbol implementations <name-path> --path <defining-file>
serena-cli symbol declaration --path <source-file> --regex <regex-with-one-capture-group>
serena-cli symbol diagnostics <file>
```

Rules:
- Do not register Serena MCP directly in OpenCode when using this skill; the CLI hides the MCP schemas to reduce fixed context cost.
- Use `overview` before reading a large unfamiliar source file.
- Use `find` without `--body` first; add `--body` only when implementation text is actually needed.
- Use `refs` before changing public or widely used symbols.
- Keep `--max-chars` bounded when a query could return many results.
- Results are JSON by default. Use `--pretty` only for human inspection.
- If a needed Serena capability is not wrapped, inspect `serena-cli tool list` and use `serena-cli tool call` sparingly.
