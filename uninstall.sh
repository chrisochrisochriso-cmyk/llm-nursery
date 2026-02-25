#!/bin/bash
# paperknight AI - Uninstaller
#
# What this removes:
#   - All Docker containers (Ollama, ChromaDB, Coordinator)
#   - Docker volumes (model cache, RAG data, history) - optional
#   - The pk CLI from /usr/local/bin or ~/.local/bin
#   - The ~/.pk profile directory
#
# What this PRESERVES:
#   - Docker itself (stays installed)
#   - Any other Docker containers/services on this machine

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
info() { echo -e "  → $*"; }
warn() { echo -e "${YELLOW}  !${RESET} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}paperknight AI - Uninstaller${RESET}"
echo ""
echo "This will stop and remove paperknight AI from this machine."
echo ""

read -rp "Are you sure? Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
read -rp "Also delete model cache and RAG data? (y/n): " DELETE_DATA
echo ""

# ---------------------------------------------------------------------------
# Stop and remove containers
# ---------------------------------------------------------------------------
if command -v docker &>/dev/null && [[ -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
    info "Stopping services..."
    cd "$SCRIPT_DIR"

    if [[ "$DELETE_DATA" =~ ^[Yy]$ ]]; then
        docker compose down -v 2>/dev/null \
            || warn "docker compose down failed - containers may already be stopped"
        ok "Services stopped and data volumes deleted"
        warn "Model cache deleted - next install will re-download (~5GB)"
    else
        docker compose down 2>/dev/null \
            || warn "docker compose down failed - containers may already be stopped"
        ok "Services stopped (data volumes kept)"
        info "To delete model cache and data later: docker compose down -v"
    fi
else
    warn "Docker or docker-compose.yml not found - skipping container removal"
fi

# ---------------------------------------------------------------------------
# Remove pk CLI
# ---------------------------------------------------------------------------
PK_REMOVED=false
for pk_path in /usr/local/bin/pk "$HOME/.local/bin/pk"; do
    if [[ -f "$pk_path" ]]; then
        rm -f "$pk_path" 2>/dev/null \
            || sudo rm -f "$pk_path" 2>/dev/null \
            || warn "Could not remove $pk_path - remove manually"
        ok "Removed pk CLI from $pk_path"
        PK_REMOVED=true
    fi
done

if [[ "$PK_REMOVED" == "false" ]]; then
    warn "pk CLI not found - already removed"
fi

# ---------------------------------------------------------------------------
# Remove profile
# ---------------------------------------------------------------------------
if [[ -d "$HOME/.pk" ]]; then
    rm -rf "$HOME/.pk"
    ok "Removed ~/.pk profile"
else
    warn "~/.pk not found - already removed"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}paperknight AI removed.${RESET}"
echo ""
echo "Docker is still installed and running."
echo ""
echo "To reinstall:"
echo "  bash install.sh"
echo ""
