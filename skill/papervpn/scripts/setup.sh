#!/usr/bin/env bash
set -euo pipefail
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
if [ -n "${PAPERVPN_ROOT:-}" ]; then
  ROOT="$PAPERVPN_ROOT"
else
  ROOT="$(cd "$(dirname "$SELF")/../../.." 2>/dev/null && pwd || true)"
fi

python3 - <<'PY' || pip3 install --user --break-system-packages requests cryptography
import importlib
for m in ("requests", "cryptography"):
    importlib.import_module(m)
PY

if ! python3 -c "import playwright" >/dev/null 2>&1; then
  echo "Installing playwright (needed for ScienceDirect)…"
  pip3 install --user --break-system-packages playwright
fi

if ! python3 -c "import secretstorage" >/dev/null 2>&1; then
  echo "Installing secretstorage (needed for 'login --from-chrome')…"
  pip3 install --user --break-system-packages secretstorage
fi

echo "papervpn dependencies OK"
if [ -n "${ROOT:-}" ] && [ -d "$ROOT/papervpn" ]; then
  echo "run: PYTHONPATH=$ROOT python3 -m papervpn check"
else
  echo "run: python3 -m papervpn check"
fi
