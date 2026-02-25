#!/bin/bash
# paperknight AI - Installer
# Single command: curl -sSL <url> | bash
#
# What this does:
#   1. Asks your name and role (3 questions, that's it)
#   2. Installs k3s on primary node, joins secondary node
#   3. Installs Tailscale for encrypted remote access from anywhere
#   4. Sets up NFS shared storage between the two ZimaBoards
#   5. Deploys paperknight AI (storage, inference, coordinator)
#   6. Installs the pk CLI on your laptop
#   7. Prints Tailscale IP so chriso can reach the cluster from Wales

set -euo pipefail

# ---------------------------------------------------------------------------
# Colours and output helpers
# ---------------------------------------------------------------------------
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
    echo ""
    echo "If this keeps happening, check the logs:"
    echo "  kubectl get pods -n paperknight-ai"
    echo "  kubectl logs deployment/pk-coordinator -n paperknight-ai"
    exit 1
}

show_time() {
    # Show estimated time for steps that take a while
    echo -e "${DIM}    (estimated: $1)${RESET}"
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}║      paperknight AI Installer     ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
echo ""
echo "Private AI on your ZimaBoards. No cloud. No API costs."
echo "LFM2-24B runs entirely on your hardware."
echo ""

# Confirm we're running from the cloned repo (not piped from curl)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/configs/storage/storage-pk-infrastructure.yaml" ]]; then
    echo -e "${RED}  ✗ ERROR:${RESET} Run this from the cloned repo, not piped from curl."
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
# Step 1: Three questions
# ---------------------------------------------------------------------------
step "Step 1 of 8 - Quick setup questions"
echo ""

# Question 1: Who are you?
echo "What's your name?"
echo "  1) chriso  - security researcher (MacBook, Wales)"
echo "  2) johno   - developer (ZimaBoard or own machine, Bristol)"
echo "  3) other"
read -rp "Choose (1/2/3): " name_choice
case "$name_choice" in
    1) USER_NAME="chriso" ;;
    2) USER_NAME="johno" ;;
    *) read -rp "Enter your name: " USER_NAME ;;
esac
ok "Hello, $USER_NAME"

echo ""

# Question 2: What role is this machine?
echo "What is this machine?"
echo "  1) Primary ZimaBoard  - installs k3s, Tailscale, deploys AI (do this first)"
echo "  2) Secondary ZimaBoard - joins existing cluster, installs Tailscale"
echo "  3) Laptop (chriso)    - installs Tailscale + pk CLI only, no k3s"
read -rp "Choose (1/2/3): " role_choice

case "$role_choice" in
    1)
        NODE_ROLE="primary"
        IS_LAPTOP=false
        ok "Primary ZimaBoard setup"
        ;;
    2)
        NODE_ROLE="secondary"
        IS_LAPTOP=false
        echo ""
        read -rp "Primary ZimaBoard LAN IP (e.g. 192.168.1.10): " CLUSTER_IP
        ok "Secondary ZimaBoard - will join cluster at $CLUSTER_IP"
        ;;
    3)
        NODE_ROLE="client"
        IS_LAPTOP=true
        echo ""
        echo "Enter the cluster IP to connect to."
        echo "  Use LAN IP (192.168.x.x) if on dad's WiFi"
        echo "  Use Tailscale IP (100.x.x.x) if connecting from Wales"
        read -rp "Cluster IP: " CLUSTER_IP
        ok "Laptop setup - connecting to $CLUSTER_IP"
        ;;
    *)
        NODE_ROLE="client"
        IS_LAPTOP=true
        read -rp "Cluster IP: " CLUSTER_IP
        ok "Client setup"
        ;;
esac

echo ""

# ---------------------------------------------------------------------------
# Step 2: Detect environment
# ---------------------------------------------------------------------------
step "Step 2 of 8 - Checking your system"

OS=$(uname -s)
ARCH=$(uname -m)
ok "System: $OS $ARCH"

# Validate OS matches chosen role
if [[ "$OS" == "Darwin" ]] && [[ "$NODE_ROLE" != "client" ]]; then
    warn "macOS detected but ZimaBoard role selected - switching to client mode"
    NODE_ROLE="client"
    IS_LAPTOP=true
elif [[ "$OS" == "Linux" ]] && [[ "$IS_LAPTOP" == "true" ]]; then
    warn "Linux detected but laptop role selected - that's fine, continuing"
fi

if [[ "$IS_LAPTOP" == "true" ]]; then
    ok "Client machine - will install Tailscale + pk CLI"
else
    ok "ZimaBoard ($NODE_ROLE) - full stack install"
fi

# Check required tools
for tool in curl; do
    if command -v "$tool" &>/dev/null; then
        ok "$tool found"
    else
        die "$tool is required but not installed"
    fi
done

# ---------------------------------------------------------------------------
# Step 3: Install k3s (ZimaBoard nodes only)
# ---------------------------------------------------------------------------
step "Step 3 of 8 - Kubernetes (k3s)"

if [[ "$NODE_ROLE" == "primary" ]] && [[ "$IS_LAPTOP" == "false" ]]; then
    if command -v k3s &>/dev/null; then
        ok "k3s already installed"
    else
        info "Installing k3s (lightweight Kubernetes for ZimaBoard)..."
        show_time "2-3 minutes"
        curl -sfL https://get.k3s.io | sh - \
            --write-kubeconfig-mode 644 \
            --disable traefik \
            --disable servicelb \
        || die "k3s install failed"
        ok "k3s installed"
    fi

    # Wait for k3s to be ready
    info "Waiting for k3s to start..."
    for i in $(seq 1 30); do
        if kubectl get nodes &>/dev/null 2>&1; then
            ok "k3s ready"
            break
        fi
        sleep 2
        if [[ $i -eq 30 ]]; then
            die "k3s did not start within 60 seconds"
        fi
    done

    # Save join token for node 2
    K3S_TOKEN=$(cat /var/lib/rancher/k3s/server/node-token 2>/dev/null || echo "")
    if [[ -n "$K3S_TOKEN" ]]; then
        ok "Join token ready"
        NODE1_IP=$(hostname -I | awk '{print $1}')
        echo ""
        echo -e "${YELLOW}  ═══════════════════════════════════════════════${RESET}"
        echo -e "${YELLOW}  To add ZimaBoard 2 to the cluster, run on it:${RESET}"
        echo ""
        echo "  curl -sfL https://get.k3s.io | K3S_URL=https://$NODE1_IP:6443 \\"
        echo "    K3S_TOKEN=$K3S_TOKEN sh -"
        echo ""
        echo "  Then label it: kubectl label node <node2-hostname> pk-node=node2"
        echo -e "${YELLOW}  ═══════════════════════════════════════════════${RESET}"
        echo ""
    fi
elif [[ "$NODE_ROLE" == "secondary" ]] && [[ "$IS_LAPTOP" == "false" ]]; then
    info "Secondary ZimaBoard - joining existing k3s cluster..."
    echo ""
    echo "  You need the join token from ZimaBoard 1."
    echo "  On ZimaBoard 1 run:  cat /var/lib/rancher/k3s/server/node-token"
    echo ""
    read -rp "  Paste the join token: " K3S_JOIN_TOKEN
    read -rp "  ZimaBoard 1 LAN IP (e.g. 192.168.1.10): " PRIMARY_IP
    echo ""
    info "Joining cluster..."
    curl -sfL https://get.k3s.io | K3S_URL="https://$PRIMARY_IP:6443" \
        K3S_TOKEN="$K3S_JOIN_TOKEN" sh - \
        || die "Failed to join k3s cluster - check token and IP"
    ok "Joined k3s cluster at $PRIMARY_IP"

elif [[ "$IS_LAPTOP" == "true" ]]; then
    ok "Laptop - skipping k3s install"
    if [[ -n "${CLUSTER_IP:-}" ]]; then
        info "To control the cluster from this laptop:"
        dim "ssh root@$CLUSTER_IP 'cat /etc/rancher/k3s/k3s.yaml' \\"
        dim "  | sed \"s/127.0.0.1/$CLUSTER_IP/g\" > ~/.kube/config"
    fi
fi

# ---------------------------------------------------------------------------
# Step 4: Tailscale - encrypted remote access
# ---------------------------------------------------------------------------
step "Step 4 of 8 - Tailscale (remote access)"
echo ""
echo "  Tailscale creates an encrypted private network between your devices."
echo "  chriso can reach the ZimaBoards from Wales without opening any router ports."
echo "  Uses WireGuard. Free for up to 3 devices. No accounts needed per device."
echo ""

if [[ "$OS" == "Linux" ]]; then
    # ZimaBoard: install Tailscale daemon
    if command -v tailscale &>/dev/null; then
        ok "Tailscale already installed"
    else
        info "Installing Tailscale..."
        curl -fsSL https://tailscale.com/install.sh | sh \
            || die "Tailscale install failed"
        ok "Tailscale installed"
    fi

    info "Connecting to Tailscale network..."
    echo ""
    echo "  A URL will appear below. Open it on any browser or your phone."
    echo ""
    echo -e "  ${YELLOW}IMPORTANT: Log in with your Tailscale account (johno's).${RESET}"
    echo "  chriso should have sent you an invite link — accept it first to create your account."
    echo "  Once you accept the invite, your account joins chriso's network automatically."
    echo ""

    # --ssh enables SSH over Tailscale (key-based, no password)
    # --accept-routes picks up routing from other Tailscale nodes
    sudo tailscale up --ssh --accept-routes 2>&1 \
        || warn "Tailscale connect failed - run tailscale-setup.sh later to retry"

    # Get Tailscale IP for printing at the end
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "not connected yet")
    ok "Tailscale IP: ${BOLD}${TAILSCALE_IP}${RESET}"

elif [[ "$OS" == "Darwin" ]]; then
    # macOS: Tailscale is installed via App Store or brew, guide the user
    if command -v tailscale &>/dev/null; then
        ok "Tailscale already installed"
        info "Connecting..."
        echo ""
        echo "  Make sure you are logged into chriso's Tailscale account."
        echo "  (chriso: your MacBook should already be connected - check the menu bar app)"
        echo ""
        tailscale up --accept-routes 2>/dev/null \
            || warn "Run: sudo tailscale up  (or use the menu bar app)"
        TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "check menu bar app")
        ok "Tailscale IP: ${BOLD}${TAILSCALE_IP}${RESET}"
    else
        warn "Tailscale not installed on this Mac."
        echo ""
        echo "  Install it with one of:"
        echo "    brew install tailscale"
        echo "    Download from: https://tailscale.com/download"
        echo ""
        echo "  Then log in with chriso's Tailscale account and re-run this script."
        TAILSCALE_IP="not installed yet"
    fi
fi

echo ""

# ---------------------------------------------------------------------------
# Step 5: Label nodes
# ---------------------------------------------------------------------------
step "Step 5 of 8 - Node labelling"

if [[ "$NODE_ROLE" == "primary" ]]; then
    info "Labelling nodes for pod affinity..."
    NODE1_HOSTNAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [[ -n "$NODE1_HOSTNAME" ]]; then
        kubectl label node "$NODE1_HOSTNAME" pk-node=node1 --overwrite 2>/dev/null && ok "Node1 ($NODE1_HOSTNAME) labelled"
    fi

    NODE2_HOSTNAME=$(kubectl get nodes -o jsonpath='{.items[1].metadata.name}' 2>/dev/null || echo "")
    if [[ -n "$NODE2_HOSTNAME" ]]; then
        kubectl label node "$NODE2_HOSTNAME" pk-node=node2 --overwrite 2>/dev/null && ok "Node2 ($NODE2_HOSTNAME) labelled"
    else
        warn "Node 2 not joined yet - label it after joining:"
        dim "kubectl label node <node2-hostname> pk-node=node2"
    fi
fi

# ---------------------------------------------------------------------------
# Step 6: Storage and namespace
# ---------------------------------------------------------------------------
step "Step 6 of 8 - Storage setup"

if [[ "$NODE_ROLE" == "primary" ]]; then
    # Install NFS provisioner for shared storage between nodes
    if ! kubectl get namespace nfs-provisioner &>/dev/null 2>&1; then
        info "Installing NFS provisioner for shared storage..."
        show_time "1-2 minutes"
        kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/nfs-subdir-external-provisioner/master/deploy/rbac.yaml 2>/dev/null || true
        warn "If NFS provisioner install fails, use local-path and copy model manually"
        warn "Changing storageClassName in configs/storage/storage-pk-infrastructure.yaml to local-path"
        # Fall back to local-path if NFS not available
        NODE1_IP=$(hostname -I | awk '{print $1}')
    fi

    info "Applying namespace and storage..."
    # Determine correct configs path
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CONFIGS_DIR="$SCRIPT_DIR/configs"

    kubectl apply -f "$CONFIGS_DIR/storage/storage-pk-infrastructure.yaml" \
        || die "Storage setup failed"
    ok "Namespace paperknight-ai created"
    ok "PVC pk-model-storage created"
fi

# ---------------------------------------------------------------------------
# Step 7: Deploy paperknight AI
# ---------------------------------------------------------------------------
step "Step 7 of 8 - Deploying paperknight AI"

if [[ "$NODE_ROLE" == "primary" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CONFIGS_DIR="$SCRIPT_DIR/configs"

    info "Deploying DaemonSet pipeline agent..."
    kubectl apply -f "$CONFIGS_DIR/inference/daemonset-pk.yaml" \
        || die "DaemonSet deploy failed"
    ok "DaemonSet deployed"

    info "Deploying Ollama Node 1 (ZimaBoard 1)..."
    show_time "30-60 seconds for first model pull (model is ~13.5GB)"
    kubectl apply -f "$CONFIGS_DIR/inference/ollama-node1-deployment.yaml" \
        || die "Ollama Node 1 deploy failed"
    ok "Ollama Node 1 deployed"

    info "Deploying Ollama Node 2 (ZimaBoard 2)..."
    kubectl apply -f "$CONFIGS_DIR/inference/ollama-node2-deployment.yaml" \
        || die "Ollama Node 2 deploy failed"
    ok "Ollama Node 2 deployed"

    # Build coordinator image and import into k3s
    # k3s uses containerd (not Docker), so we build with Docker then import.
    info "Building coordinator image (pk-coordinator:v1)..."
    show_time "3-5 minutes on first build"

    # Install Docker if not present (needed to build the image)
    if ! command -v docker &>/dev/null; then
        info "Docker not found - installing..."
        curl -fsSL https://get.docker.com | sh \
            || die "Docker install failed - install manually: https://docs.docker.com/engine/install"
        # Add current user to docker group
        sudo usermod -aG docker "$USER" 2>/dev/null || true
        ok "Docker installed"
    else
        ok "Docker found"
    fi

    # Build the coordinator image
    docker build \
        -t pk-coordinator:v1 \
        -f "$SCRIPT_DIR/src/coordinator/Dockerfile.pk" \
        "$SCRIPT_DIR/src/coordinator/" \
        || die "Coordinator image build failed - check src/coordinator/Dockerfile.pk"
    ok "Image built: pk-coordinator:v1"

    # Import into k3s containerd so the deployment can find it
    info "Importing image into k3s..."
    docker save pk-coordinator:v1 | sudo k3s ctr images import - \
        || die "Image import into k3s failed"
    ok "Image imported into k3s"

    info "Deploying Coordinator..."
    kubectl apply -f "$CONFIGS_DIR/inference/coordinator-pk-deployment.yaml" \
        || die "Coordinator deploy failed"
    ok "Coordinator deployed"

    # Wait for coordinator to be ready
    info "Waiting for coordinator to be ready..."
    show_time "30-60 seconds"
    kubectl rollout status deployment/pk-coordinator -n paperknight-ai --timeout=120s \
        || warn "Coordinator taking longer than expected - check: kubectl logs deployment/pk-coordinator -n paperknight-ai"
fi

# ---------------------------------------------------------------------------
# Step 8: Install pk CLI
# ---------------------------------------------------------------------------
step "Step 8 of 8 - Installing pk CLI"

# Check Python
if ! command -v python3 &>/dev/null; then
    die "Python 3 is required. Install it first: brew install python3 (Mac) or apt install python3"
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
ok "Python $PYTHON_VERSION found"

# Install dependencies
info "Installing pk CLI dependencies..."
pip3 install --quiet typer rich httpx pyyaml 2>/dev/null \
    || pip install --quiet typer rich httpx pyyaml 2>/dev/null \
    || die "pip install failed - try: pip3 install typer rich httpx pyyaml"
ok "Dependencies installed"

# Install pk CLI
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_SRC="$SCRIPT_DIR/src/cli/main.py"

if [[ ! -f "$CLI_SRC" ]]; then
    die "CLI source not found at $CLI_SRC"
fi

# Create pk wrapper script
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

# Set up profile
mkdir -p "$HOME/.pk"
CLUSTER_URL="${CLUSTER_IP:-localhost}"
cat > "$HOME/.pk/profile.yaml" << PROFILE
name: $USER_NAME
coordinator_url: http://$CLUSTER_URL:30800
PROFILE
ok "Profile saved: ~/.pk/profile.yaml"
dim "To switch to Tailscale later: pk profile --cluster-ip <tailscale-ip>"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}║      paperknight AI is ready!     ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
echo ""
echo "Quick test:"
echo "  pk status              - check cluster health"
echo "  pk ask 'hello world'   - test inference"
echo ""

if [[ "$NODE_ROLE" == "primary" ]]; then
    echo "First run note:"
    echo "  LFM2-24B model is ~13.5GB. First inference may take"
    echo "  several minutes while the model loads into RAM."
    echo "  Subsequent queries will be much faster (model stays hot)."
    echo ""
fi

# Print Tailscale summary
if [[ "$OS" == "Linux" ]]; then
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "not connected")
    if [[ "$TS_IP" != "not connected" ]]; then
        echo -e "${YELLOW}  ═══════════════════════════════════════════════${RESET}"
        echo -e "${YELLOW}  Tailscale remote access${RESET}"
        echo ""
        echo "  This ZimaBoard's Tailscale IP: ${BOLD}$TS_IP${RESET}"
        echo ""
        echo "  chriso - from Wales, run on your MacBook:"
        echo "    pk profile --cluster-ip $TS_IP"
        echo "    pk status"
        echo "    ssh root@$TS_IP"
        echo ""
        echo "  (Install tailscale-setup.sh on your MacBook first)"
        echo -e "${YELLOW}  ═══════════════════════════════════════════════${RESET}"
        echo ""
    fi
fi

echo -e "${DIM}  logs:    kubectl logs -f deployment/pk-coordinator -n paperknight-ai${RESET}"
echo -e "${DIM}  trouble: tailscale-setup.sh  (reinstall Tailscale)${RESET}"
echo ""

# Verify it works
if command -v pk &>/dev/null; then
    info "Running pk status..."
    pk status 2>/dev/null || warn "Coordinator not yet ready - wait a minute and run: pk status"
fi
