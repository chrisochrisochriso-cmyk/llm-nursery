#!/bin/bash
# paperknight AI - Uninstaller
# Removes paperknight AI from the cluster cleanly.
#
# What this removes:
#   - All paperknight-ai Kubernetes resources (deployments, services, PVCs)
#   - The paperknight-ai namespace
#   - The pk CLI from /usr/local/bin or ~/.local/bin
#   - The ~/.pk profile directory
#
# What this PRESERVES:
#   - The llm-nursery namespace and all its resources (untouched)
#   - Plex and any other services on the ZimaBoards
#   - Tailscale (stays connected - remove manually if wanted)
#   - k3s itself (stays running)
#   - The model weights on the PVC are DELETED with the PVC
#
# The LFM2-24B model (~13.5GB) lives on the PVC. If you want to
# keep it for reinstall, back it up first:
#   kubectl exec -n paperknight-ai deployment/pk-storage-node -- \
#     tar czf /tmp/lfm2-backup.tar.gz /storage/ollama
#   kubectl cp paperknight-ai/<storage-pod>:/tmp/lfm2-backup.tar.gz ./lfm2-backup.tar.gz

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
info() { echo -e "  → $*"; }
warn() { echo -e "${YELLOW}  !${RESET} $*"; }

echo ""
echo -e "${BOLD}paperknight AI - Uninstaller${RESET}"
echo ""
echo "This will remove paperknight AI from your cluster."
echo "llm-nursery, Plex, and Tailscale are NOT affected."
echo ""
echo -e "${YELLOW}WARNING: The model weights (~13.5GB) on the PVC will be deleted.${RESET}"
echo "  Back them up first if you want to avoid re-downloading on reinstall."
echo ""
read -rp "Are you sure? Type 'yes' to continue: " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""

# ---------------------------------------------------------------------------
# Remove Kubernetes resources
# ---------------------------------------------------------------------------
if command -v kubectl &>/dev/null; then
    if kubectl get namespace paperknight-ai &>/dev/null 2>&1; then
        info "Scaling down deployments (graceful shutdown)..."
        kubectl scale deployment --all -n paperknight-ai --replicas=0 2>/dev/null || true
        sleep 3

        info "Deleting paperknight-ai namespace and all resources..."
        # This deletes all deployments, services, configmaps, and PVCs in the namespace
        kubectl delete namespace paperknight-ai --timeout=60s 2>/dev/null \
            || warn "Namespace deletion timed out - it will finish in the background"
        ok "Kubernetes resources removed"
    else
        warn "Namespace paperknight-ai not found - already removed or never installed"
    fi
else
    warn "kubectl not found - skipping cluster cleanup"
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
    warn "pk CLI not found in standard locations - already removed"
fi

# ---------------------------------------------------------------------------
# Remove profile
# ---------------------------------------------------------------------------
if [[ -d "$HOME/.pk" ]]; then
    rm -rf "$HOME/.pk"
    ok "Removed ~/.pk profile directory"
else
    warn "~/.pk not found - already removed"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}paperknight AI removed.${RESET}"
echo ""
echo "What's still running:"
echo "  - k3s (still running, llm-nursery namespace intact)"
echo "  - Tailscale (still connected)"
echo "  - Plex (untouched)"
echo ""
echo "To reinstall:"
echo "  bash install.sh"
echo ""
echo "To remove Tailscale (optional):"
echo "  Linux: sudo tailscale down && sudo apt remove tailscale"
echo "  macOS: brew uninstall tailscale (or delete from Applications)"
echo ""
