#!/usr/bin/env bash
# Install the papervpn skill into every local AI harness that reads SKILL.md.
set -euo pipefail

SKILL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skill/papervpn"
BIN_DIR="${HOME}/.local/bin"

TARGETS=(
  "${HOME}/.claude/skills/papervpn"
  "${HOME}/.config/opencode/skills/papervpn"
  "${HOME}/.agents/skills/papervpn"
  "${HOME}/.codex/skills/papervpn"
  "${HOME}/.dsh/skills/papervpn"
)

for dest in "${TARGETS[@]}"; do
  mkdir -p "$(dirname "$dest")"
  rm -rf "$dest"
  mkdir -p "$dest/scripts"
  cp "$SKILL_SRC/SKILL.md" "$dest/SKILL.md"
  cp "$SKILL_SRC"/scripts/* "$dest/scripts/"
  chmod +x "$dest"/scripts/*
  echo "installed skill -> $dest"
done

mkdir -p "$BIN_DIR"
ln -sf "$SKILL_SRC/scripts/papervpn" "$BIN_DIR/papervpn"
ln -sf "$SKILL_SRC/scripts/papervpn-mcp" "$BIN_DIR/papervpn-mcp"
chmod +x "$SKILL_SRC"/scripts/*
echo "installed launchers -> $BIN_DIR/papervpn, $BIN_DIR/papervpn-mcp"
echo
echo "Verify:  ~/.local/bin/papervpn check"
