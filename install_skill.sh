#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════
#  papervpn skill installer
#
#    ./install_skill.sh                  install to ~/.agents/skills only
#                                        (the shared dir that opencode, Codex,
#                                         Claude Code and dsh all read)
#    ./install_skill.sh -a codex,dsh     install to specific agents (multi-select)
#    ./install_skill.sh --all            install to every known agent
#    ./install_skill.sh --list           show install status per agent
#    ./install_skill.sh -r codex,dsh     uninstall from specific agents
#    ./install_skill.sh -r --all         uninstall from every known agent
#
#  Known agents: agents, claude, codex, opencode, dsh
# ════════════════════════════════════════════════════════════════════════
set -euo pipefail

SKILL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skill/papervpn"
BIN_DIR="${HOME}/.local/bin"
KNOWN="agents claude codex opencode dsh"

target_dir() {
  case "$1" in
    agents)   printf '%s\n' "${HOME}/.agents/skills/papervpn" ;;
    claude)   printf '%s\n' "${HOME}/.claude/skills/papervpn" ;;
    codex)    printf '%s\n' "${HOME}/.codex/skills/papervpn" ;;
    opencode) printf '%s\n' "${HOME}/.config/opencode/skills/papervpn" ;;
    dsh)      printf '%s\n' "${HOME}/.dsh/skills/papervpn" ;;
    *)        return 1 ;;
  esac
}

usage() { sed -n '2,15p' "$0"; }

action=install
select_all=0
selected=""
while [ $# -gt 0 ]; do
  case "$1" in
    -a|--agents)                 selected="${selected:+$selected,}$2"; shift 2 ;;
    --all)                       select_all=1; shift ;;
    -r|--uninstall|--remove)     action=uninstall; shift ;;
    -l|--list)                   action=list; shift ;;
    -h|--help)                   usage; exit 0 ;;
    -*) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    *) selected="${selected:+$selected,}$1"; shift ;;   # bare agent names, comma-separated
  esac
done

if [ "$select_all" = 1 ]; then
  list="$KNOWN"
elif [ -n "$selected" ]; then
  list="$(printf '%s' "$selected" | tr ',' ' ')"
else
  list="agents"
fi

install_one() {
  local dest
  dest="$(target_dir "$1")" || { echo "unknown agent: $1" >&2; return 1; }
  mkdir -p "$dest/scripts"
  cp "$SKILL_SRC/SKILL.md" "$dest/SKILL.md"
  cp "$SKILL_SRC"/scripts/* "$dest/scripts/"
  chmod +x "$dest"/scripts/*
  echo "installed -> $dest"
}

uninstall_one() {
  local dest
  dest="$(target_dir "$1")" || { echo "unknown agent: $1" >&2; return 1; }
  if [ -e "$dest" ]; then rm -rf "$dest"; echo "removed   -> $dest"; else echo "absent    -> $dest"; fi
}

list_one() {
  local dest
  dest="$(target_dir "$1")" || { echo "unknown agent: $1" >&2; return 1; }
  if [ -f "$dest/SKILL.md" ]; then printf '  [x] %-9s %s\n' "$1" "$dest"; else printf '  [ ] %-9s %s\n' "$1" "$dest"; fi
}

case "$action" in
  install)
    for a in $list; do install_one "$a"; done
    mkdir -p "$BIN_DIR"
    ln -sf "$SKILL_SRC/scripts/papervpn"     "$BIN_DIR/papervpn"
    ln -sf "$SKILL_SRC/scripts/papervpn-mcp" "$BIN_DIR/papervpn-mcp"
    chmod +x "$SKILL_SRC"/scripts/*
    echo "launchers -> $BIN_DIR/papervpn, $BIN_DIR/papervpn-mcp"
    echo
    echo "verify: papervpn check"
    ;;
  uninstall)
    for a in $list; do uninstall_one "$a"; done
    ;;
  list)
    echo "papervpn skill status:"
    for a in $KNOWN; do list_one "$a"; done
    ;;
esac
