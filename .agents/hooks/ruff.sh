#!/usr/bin/env bash
# Hook PostToolUse (Claude Code y Codex): formatea y corrige con ruff los .py recién editados.
# Claude manda la ruta en tool_input.file_path; Codex (apply_patch) la trae dentro del parche,
# en las líneas "*** Add File:", "*** Update File:" o "*** Move to:".
# Si quedan errores que ruff no corrige solo, los muestra al agente (exit 2) para que los arregle.
set -u
entrada=$(cat)
raiz=$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null) || exit 0
cwd=$(jq -r '.cwd // empty' <<<"$entrada")
cd "${cwd:-$raiz}" || exit 0

mapfile -t rutas < <(
  jq -r '.tool_input.file_path // empty' <<<"$entrada"
  jq -r '.tool_input.command // empty | if type == "array" then join("\n") else . end' <<<"$entrada" |
    sed -n -E 's/^\*\*\* (Add File|Update File|Move to): (.*)$/\2/p'
)

archivos=()
for r in "${rutas[@]}"; do
  [[ $r == *.py && -f $r ]] || continue
  abs=$(realpath "$r")
  [[ $abs == "$raiz"/* ]] && archivos+=("$abs")
done
((${#archivos[@]})) || exit 0

cd "$raiz" || exit 0
uv run --quiet ruff check --fix --quiet "${archivos[@]}" >/dev/null 2>&1
uv run --quiet ruff format --quiet "${archivos[@]}" >/dev/null 2>&1
if ! salida=$(uv run --quiet ruff check --quiet --output-format concise "${archivos[@]}" 2>&1); then
  printf 'ruff encontró problemas que no pudo corregir solo:\n%s\n' "$salida" | sed 's/\x1b\[[0-9;]*m//g' >&2
  exit 2
fi
