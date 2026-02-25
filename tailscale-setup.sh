#!/bin/bash
# paperknight AI - Tailscale Setup
# Standalone script to install or reinstall Tailscale
#
# Run this if:
#   - Tailscale wasn't installed during initial setup
#   - Tailscale needs to be reinstalled after a wipe
#   - Adding a new device to the network
#
# Works on:
#   - macOS (chriso's MacBook)
#   - Linux x86_64 (ZimaBoard 1 and 2)
#
# After running this on all devices:
#   - chriso can SSH into ZimaBoards from anywhere in the world
#   - pk CLI works over Tailscale exactly the same as on the home network
#   - All traffic stays encrypted via WireGuard
#   - No ports opened on dad's router

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
info() { echo -e "${BLUE}  →${RESET} $*"; }
warn() { echo -e "${YELLOW}  !${RESET} $*"; }
step() { echo -e "\n${BOLD}$*${RESET}"; }
dim()  { echo -e "${DIM}    $*${RESET}"; }

die() {
    echo -e "${RED}  ✗ ERROR:${RESET} $*" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   paperknight AI - Tailscale      ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
echo ""
echo "Sets up encrypted remote access between your devices."
echo "No ports opened on any router. Free for up to 3 devices."
echo ""

# ---------------------------------------------------------------------------
# Detect OS
# ---------------------------------------------------------------------------
step "Step 1 of 3 - Detecting your system"

OS=$(uname -s)
ARCH=$(uname -m)
ok "System: $OS $ARCH"

if [[ "$OS" == "Darwin" ]]; then
    PLATFORM="macos"
    ok "macOS detected (chriso's MacBook)"
elif [[ "$OS" == "Linux" ]]; then
    PLATFORM="linux"
    # Detect distro
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        DISTRO="${ID:-unknown}"
        ok "Linux detected: $DISTRO"
    else
        DISTRO="unknown"
        ok "Linux detected"
    fi
else
    die "Unsupported OS: $OS"
fi

# ---------------------------------------------------------------------------
# Install Tailscale
# ---------------------------------------------------------------------------
step "Step 2 of 3 - Installing Tailscale"

if command -v tailscale &>/dev/null; then
    CURRENT_VER=$(tailscale version 2>/dev/null | head -1 || echo "unknown")
    ok "Tailscale already installed (version: $CURRENT_VER)"
    warn "To reinstall, remove first: sudo apt remove tailscale (Linux) or brew uninstall tailscale (Mac)"
else
    if [[ "$PLATFORM" == "macos" ]]; then
        info "Installing Tailscale on macOS..."
        echo ""
        echo "  Option A - Homebrew (recommended if you have brew):"
        echo "    brew install tailscale"
        echo ""
        echo "  Option B - Download from tailscale.com/download"
        echo "    Install the .pkg file, then come back here"
        echo ""
        read -rp "  Have you installed Tailscale via one of the above methods? (y/n): " ts_installed
        if [[ ! "$ts_installed" =~ ^[Yy]$ ]]; then
            echo ""
            echo "  Install Tailscale first, then re-run this script."
            exit 0
        fi

    elif [[ "$PLATFORM" == "linux" ]]; then
        info "Installing Tailscale on Linux (ZimaBoard)..."
        echo ""
        # Official Tailscale install script - works on Debian/Ubuntu/Raspbian
        curl -fsSL https://tailscale.com/install.sh | sh \
            || die "Tailscale install failed. Try: sudo apt install tailscale"
        ok "Tailscale installed"
    fi
fi

# ---------------------------------------------------------------------------
# Connect to Tailscale
# ---------------------------------------------------------------------------
step "Step 3 of 3 - Connecting to your Tailscale network"

if [[ "$PLATFORM" == "linux" ]]; then
    # ZimaBoard: enable SSH over Tailscale so chriso can access remotely
    # --ssh: enables Tailscale SSH (no password needed, key-based via Tailscale ACLs)
    # --accept-routes: picks up any subnet routes from other nodes
    info "Starting Tailscale with SSH enabled..."
    echo ""
    echo "  You'll be shown a URL. Open it on any device to authorise this node."
    echo "  (Or use your phone if you're at dad's place)"
    echo ""

    sudo tailscale up --ssh --accept-routes \
        || die "tailscale up failed - is the tailscaled service running? Try: sudo systemctl start tailscaled"

    # Get our Tailscale IP
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "pending")
    ok "Tailscale connected"
    ok "This node's Tailscale IP: ${BOLD}$TS_IP${RESET}"

elif [[ "$PLATFORM" == "macos" ]]; then
    info "Connecting macOS to Tailscale..."
    echo ""
    echo "  If the Tailscale menu bar app is running, click it and sign in."
    echo "  Or run from terminal:"
    echo ""
    echo "    sudo tailscale up"
    echo ""
    read -rp "  Are you connected to Tailscale? (y/n): " ts_connected
    if [[ "$ts_connected" =~ ^[Yy]$ ]]; then
        TS_IP=$(tailscale ip -4 2>/dev/null || echo "check Tailscale app")
        ok "Tailscale IP: ${BOLD}$TS_IP${RESET}"
    else
        warn "Connect Tailscale, then run: tailscale ip -4 to get your IP"
    fi
fi

# ---------------------------------------------------------------------------
# Print summary and next steps
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}║        Tailscale is ready!        ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
echo ""

if [[ "$PLATFORM" == "linux" ]]; then
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "run: tailscale ip -4")
    echo "  This ZimaBoard's Tailscale IP: ${BOLD}$TS_IP${RESET}"
    echo ""
    echo "  From chriso's MacBook (anywhere in the world):"
    echo ""
    echo "    SSH in:       ssh root@$TS_IP"
    echo "    Use pk CLI:   pk profile --cluster-ip $TS_IP"
    echo "                  pk status"
    echo "                  pk ask 'hello from Wales'"
    echo ""
    echo "  Share this IP with chriso: ${YELLOW}$TS_IP${RESET}"

elif [[ "$PLATFORM" == "macos" ]]; then
    echo "  macOS connected to Tailscale."
    echo ""
    echo "  To connect pk CLI to the cluster over Tailscale:"
    echo ""
    echo "    pk profile --cluster-ip <zimaboard1-tailscale-ip>"
    echo "    pk status"
    echo ""
    echo "  Get ZimaBoard 1's Tailscale IP by running this script on it,"
    echo "  or check the Tailscale admin panel at tailscale.com/admin"
fi

echo ""
echo -e "${DIM}  Security: WireGuard encrypted, SSH key auth, no open ports on router${RESET}"
echo ""
