---
name: serena-edit
description: Perform symbol-aware refactors and structural edits through the token-light serena-cli Serena frontend.
---

# Serena Edit

Use semantic edits when they are safer than textual replacement.

```text
serena-cli edit rename <name-path> <new-name> --path <defining-file>
serena-cli edit replace-body <name-path> --path <file> --content-file <file>
serena-cli edit insert-before <name-path> --path <file> --content-file <file>
serena-cli edit insert-after <name-path> --path <file> --content-file <file>
serena-cli edit safe-delete <name-path> --path <defining-file>
```

Rules:
- Before `replace-body`, retrieve the exact symbol with `serena-cli symbol find ... --body`.
- Before rename or safe delete, inspect references when the impact is not already obvious.
- Prefer `--content-file` for multiline code to avoid shell quoting errors.
- After edits, run the project tests/build and `serena-cli symbol diagnostics` for affected files when useful.
- Never broaden the requested change merely because a semantic edit makes it easy.
