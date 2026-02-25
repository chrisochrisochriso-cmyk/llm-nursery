#!/bin/bash
# paperknight AI - Installer
# Single ZimaBoard (Ubuntu) + MacBook setup
# No Kubernetes. Docker Compose only.
#
# Run this on:
#   1. The ZimaBoard  - sets up Ollama, ChromaDB, Coordinator
#   2. Your MacBook   - installs the pk CLI and points it at the ZimaBoard

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
err()  { echo -e "${RED}  ✗ ERROR:${RESET} $*" >&2; }
step() { echo -e "\n${BOLD}$*${RESET}"; }
dim()  { echo -e "${DIM}    $*${RESET}"; }

die() {
    err "$1"
    exit 1
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}║      paperknight AI Installer     ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
echo ""
echo "Private AI on your ZimaBoard. No cloud. No API costs."
echo "Llama 3.1 8B runs entirely on your hardware."
echo ""

# Check we're running from the cloned repo
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
    err "Run this from the cloned repo, not piped from curl."
    echo ""
    echo "  First clone the repo:"
    echo "    git clone https://github.com/chrisochrisochriso-cmyk/llm-nursery.git"
    echo "    cd llm-nursery"
    echo "    bash install.sh"
    echo ""
    exit 1
fi
ok "Running from repo: $SCRIPT_DIR"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Two questions
# ---------------------------------------------------------------------------
step "Step 1 of 4 - Quick setup"
echo ""

echo "What's your name?"
echo "  1) chriso"
echo "  2) johno"
echo "  3) other"
read -rp "Choose (1/2/3): " name_choice
case "$name_choice" in
    1) USER_NAME="chriso" ;;
    2) USER_NAME="johno" ;;
    *) read -rp "Enter your name: " USER_NAME ;;
esac
ok "Hello, $USER_NAME"
echo ""

OS=$(uname -s)

echo "What is this machine?"
echo "  1) ZimaBoard  - sets up the AI server (do this first)"
echo "  2) MacBook / laptop  - installs pk CLI only"
read -rp "Choose (1/2): " role_choice

case "$role_choice" in
    1)
        if [[ "$OS" == "Darwin" ]]; then
            warn "macOS detected - switching to laptop mode"
            NODE_ROLE="client"
            IS_LAPTOP=true
            read -rp "ZimaBoard LAN IP (e.g. 192.168.1.10): " CLUSTER_IP
        else
            NODE_ROLE="server"
            IS_LAPTOP=false
            ok "ZimaBoard server setup"
        fi
        ;;
    *)
        NODE_ROLE="client"
        IS_LAPTOP=true
        echo ""
        read -rp "ZimaBoard LAN IP (e.g. 192.168.1.10): " CLUSTER_IP
        ok "Laptop setup - connecting to $CLUSTER_IP"
        ;;
esac

echo ""

# ---------------------------------------------------------------------------
# Step 2: Docker (ZimaBoard only)
# ---------------------------------------------------------------------------
step "Step 2 of 4 - Docker"

if [[ "$IS_LAPTOP" == "false" ]]; then
    if command -v docker &>/dev/null; then
        ok "Docker already installed"
    else
        info "Installing Docker..."
        curl -fsSL https://get.docker.com | sh \
            || die "Docker install failed - see https://docs.docker.com/engine/install"
        sudo usermod -aG docker "$USER" 2>/dev/null || true
        ok "Docker installed"
    fi

    if docker compose version &>/dev/null 2>&1; then
        ok "Docker Compose ready"
    else
        info "Installing Docker Compose plugin..."
        sudo apt-get install -y docker-compose-plugin 2>/dev/null \
            || warn "Install docker-compose-plugin manually if needed"
    fi
else
    ok "Laptop - skipping Docker"
fi

# ---------------------------------------------------------------------------
# Step 3: Start services (ZimaBoard only)
# ---------------------------------------------------------------------------
step "Step 3 of 4 - Starting paperknight AI"

if [[ "$IS_LAPTOP" == "false" ]]; then
    cd "$SCRIPT_DIR"

    info "Building coordinator image..."
    echo "  (3-5 minutes on first build)"
    docker compose build coordinator \
        || die "Coordinator build failed - check src/coordinator/Dockerfile.pk"
    ok "Coordinator built"

    info "Starting Ollama, ChromaDB, and Coordinator..."
    docker compose up -d \
        || die "docker compose up failed"
    ok "All services started"

    # Wait for Ollama to be ready before pulling model
    info "Waiting for Ollama to start..."
    for i in $(seq 1 30); do
        if docker compose exec -T ollama ollama list &>/dev/null 2>&1; then
            ok "Ollama ready"
            break
        fi
        sleep 2
        if [[ $i -eq 30 ]]; then
            die "Ollama did not start in 60 seconds - check: docker compose logs ollama"
        fi
    done

    info "Pulling Llama 3.1 8B (~5GB - takes a while on first run)..."
    echo "  Model will be cached on disk for future starts."
    docker compose exec -T ollama ollama pull llama3.1:8b \
        || die "Model pull failed - check network: docker compose logs ollama"
    ok "Llama 3.1 8B ready"

    BOARD_IP=$(hostname -I | awk '{print $1}')
else
    ok "Laptop - skipping service setup"
fi

# ---------------------------------------------------------------------------
# Step 4: pk CLI
# ---------------------------------------------------------------------------
step "Step 4 of 4 - Installing pk CLI"

if ! command -v python3 &>/dev/null; then
    die "Python 3 required. Install: brew install python3 (Mac) or apt install python3"
fi
ok "Python found"

info "Installing dependencies..."
pip3 install --quiet typer rich httpx pyyaml 2>/dev/null \
    || pip install --quiet typer rich httpx pyyaml 2>/dev/null \
    || die "pip install failed - try: pip3 install typer rich httpx pyyaml"
ok "Dependencies installed"

CLI_SRC="$SCRIPT_DIR/src/cli/main.py"
[[ -f "$CLI_SRC" ]] || die "CLI source not found at $CLI_SRC"

PK_BIN="/usr/local/bin/pk"
cat > /tmp/pk_wrapper << WRAPPER
#!/bin/bash
python3 "$CLI_SRC" "\$@"
WRAPPER
chmod +x /tmp/pk_wrapper
mv /tmp/pk_wrapper "$PK_BIN" 2>/dev/null \
    || sudo mv /tmp/pk_wrapper "$PK_BIN" 2>/dev/null \
    || { mkdir -p "$HOME/.local/bin" && cp /tmp/pk_wrapper "$HOME/.local/bin/pk" && PK_BIN="$HOME/.local/bin/pk"; }
ok "pk CLI installed at $PK_BIN"

mkdir -p "$HOME/.pk"
CLUSTER_URL="${CLUSTER_IP:-localhost}"
cat > "$HOME/.pk/profile.yaml" << PROFILE
name: $USER_NAME
coordinator_url: http://$CLUSTER_URL:30800
PROFILE
ok "Profile saved: ~/.pk/profile.yaml"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}║      paperknight AI is ready!     ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
echo ""
echo "Quick test:"
echo "  pk status            - check everything is running"
echo "  pk ask 'hello'       - test inference"
echo ""

if [[ "$IS_LAPTOP" == "false" ]]; then
    echo -e "${YELLOW}  ZimaBoard IP: ${BOLD}${BOARD_IP:-unknown}${RESET}"
    echo ""
    echo "  On your MacBook:"
    dim "git clone https://github.com/chrisochrisochriso-cmyk/llm-nursery.git"
    dim "cd llm-nursery && bash install.sh"
    dim "→ Choose: MacBook, enter ZimaBoard IP: ${BOARD_IP:-<ip>}"
    echo ""
    echo "  To manage services on this ZimaBoard:"
    dim "docker compose ps             - check status"
    dim "docker compose logs -f        - view logs"
    dim "docker compose restart        - restart all"
    dim "docker compose down           - stop all"
fi

echo ""

if command -v pk &>/dev/null; then
    info "Running pk status..."
    pk status 2>/dev/null || warn "Coordinator still starting - wait a moment then run: pk status"
fi
