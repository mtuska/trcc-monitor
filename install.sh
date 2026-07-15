#!/usr/bin/env bash
# Install trcc-monitor as a systemd user service.
#
# 1. Installs the package into an isolated tool environment (uv tool / pipx /
#    pip --user, whichever is available) so it works on immutable distros
#    (Bazzite/ostree) without touching the base system.
# 2. Generates the systemd user unit with the resolved binary path.
# 3. Reloads and (unless --no-enable) enables + starts the service.
#
# Usage: ./install.sh [--no-enable] [--user-only]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="$REPO_DIR/packaging/systemd/trcc-monitor.service"
UNIT_DST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_DST="$UNIT_DST_DIR/trcc-monitor.service"

ENABLE=1
for arg in "$@"; do
    case "$arg" in
        --no-enable) ENABLE=0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

echo "==> Installing trcc-monitor package"
if command -v uv >/dev/null 2>&1; then
    # --reinstall is load-bearing: without it uv serves a cached wheel keyed on
    # the (unchanged) version, so local source edits silently never deploy.
    uv tool install --force --reinstall "$REPO_DIR"
elif command -v pipx >/dev/null 2>&1; then
    pipx install --force "$REPO_DIR"
else
    echo "    uv/pipx not found — falling back to pip --user"
    python3 -m pip install --user --force-reinstall "$REPO_DIR"
fi

# Resolve the installed executable path.
BIN="$(command -v trcc-monitor || true)"
if [ -z "$BIN" ]; then
    for cand in "$HOME/.local/bin/trcc-monitor"; do
        [ -x "$cand" ] && BIN="$cand" && break
    done
fi
if [ -z "$BIN" ]; then
    echo "ERROR: trcc-monitor not found on PATH after install." >&2
    echo "       Ensure ~/.local/bin is on your PATH, then re-run." >&2
    exit 1
fi
echo "    installed: $BIN"

echo "==> Writing systemd user unit -> $UNIT_DST"
mkdir -p "$UNIT_DST_DIR"
sed "s#__EXEC__#$BIN#" "$UNIT_SRC" > "$UNIT_DST"

echo "==> Reloading systemd user daemon"
systemctl --user daemon-reload

if [ "$ENABLE" -eq 1 ]; then
    echo "==> Enabling + starting trcc-monitor.service"
    systemctl --user enable --now trcc-monitor.service
    echo
    echo "Done. Check status with:"
    echo "    systemctl --user status trcc-monitor.service"
    echo "    journalctl --user -u trcc-monitor.service -f"
else
    echo
    echo "Installed but not enabled. Start it with:"
    echo "    systemctl --user enable --now trcc-monitor.service"
fi

cat <<'NOTE'

Reminders:
  * trcc-monitor pushes frames through the trccd daemon. Install and enable
    thermalright-trcc-linux first:
        sudo trcc system setup           # udev rules + SELinux (one-time, root)
        systemctl --user enable --now trccd.service
  * All collectors are free: `limits` reads Claude Code's own /api/oauth/usage
    endpoint (no tokens), everything else is local or an unauthenticated page.
  * Configure via ~/.config/trcc-monitor/config.toml (see README).
NOTE
