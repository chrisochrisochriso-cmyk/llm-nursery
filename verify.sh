#!/bin/bash
# paperknight AI - Health Check
# Run this any time to verify the system is working correctly
#
# Usage:
#   bash verify.sh              - full check, coloured output
#   bash verify.sh --quiet      - plain text, exit code 0/1 (for scripting)
#   bash verify.sh --fix        - attempt to restart degraded components

set -euo pipefail

QUIET=false
FIX=false
for arg in "$@"; do
    case "$arg" in
        --quiet|-q) QUIET=true ;;
        --fix)      FIX=true ;;
    esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() {
    PASS=$((PASS+1))
    if [[ "$QUIET" == "true" ]]; then
        echo "PASS: $*"
    else
        echo -e "${GREEN}  ✓${RESET} $*"
    fi
}

fail() {
    FAIL=$((FAIL+1))
    if [[ "$QUIET" == "true" ]]; then
        echo "FAIL: $*"
    else
        echo -e "${RED}  ✗${RESET} $*"
    fi
}

warn() {
    WARN=$((WARN+1))
    if [[ "$QUIET" == "true" ]]; then
        echo "WARN: $*"
    else
        echo -e "${YELLOW}  !${RESET} $*"
    fi
}

section() {
    if [[ "$QUIET" != "true" ]]; then
        echo -e "\n${BOLD}$*${RESET}"
    fi
}

# ---------------------------------------------------------------------------
if [[ "$QUIET" != "true" ]]; then
    echo ""
    echo -e "${BOLD}paperknight AI - Verification${RESET}"
    echo ""
fi

# ---------------------------------------------------------------------------
section "Cluster"

if ! command -v kubectl &>/dev/null; then
    fail "kubectl not found"
else
    pass "kubectl available"

    # Namespace exists
    if kubectl get namespace paperknight-ai &>/dev/null 2>&1; then
        pass "namespace paperknight-ai exists"
    else
        fail "namespace paperknight-ai missing  →  kubectl apply -f configs/storage/storage-pk-infrastructure.yaml"
    fi

    # Node count
    NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$NODE_COUNT" -ge 2 ]]; then
        pass "k3s nodes: $NODE_COUNT (both ZimaBoards joined)"
    elif [[ "$NODE_COUNT" -eq 1 ]]; then
        warn "k3s nodes: 1 (ZimaBoard 2 not joined yet)"
    else
        fail "k3s nodes: $NODE_COUNT (cluster not running?)"
    fi

    # Node labels
    NODE1=$(kubectl get nodes -l pk-node=node1 --no-headers 2>/dev/null | wc -l | tr -d ' ')
    NODE2=$(kubectl get nodes -l pk-node=node2 --no-headers 2>/dev/null | wc -l | tr -d ' ')
    [[ "$NODE1" -ge 1 ]] && pass "Node 1 labelled (pk-node=node1)" || warn "Node 1 not labelled  →  kubectl label node <hostname> pk-node=node1"
    [[ "$NODE2" -ge 1 ]] && pass "Node 2 labelled (pk-node=node2)" || warn "Node 2 not labelled  →  kubectl label node <hostname> pk-node=node2"
fi

# ---------------------------------------------------------------------------
section "Storage"

if command -v kubectl &>/dev/null; then
    PVC_STATUS=$(kubectl get pvc pk-model-storage -n paperknight-ai -o jsonpath='{.status.phase}' 2>/dev/null || echo "missing")
    if [[ "$PVC_STATUS" == "Bound" ]]; then
        pass "PVC pk-model-storage: Bound"
    elif [[ "$PVC_STATUS" == "Pending" ]]; then
        warn "PVC pk-model-storage: Pending (storage provisioner may still be starting)"
    else
        fail "PVC pk-model-storage: $PVC_STATUS  →  kubectl apply -f configs/storage/storage-pk-infrastructure.yaml"
    fi

    STORAGE_POD=$(kubectl get deployment pk-storage-node -n paperknight-ai -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    [[ "$STORAGE_POD" -ge 1 ]] && pass "Storage node: running" || warn "Storage node: not ready"
fi

# ---------------------------------------------------------------------------
section "Inference"

if command -v kubectl &>/dev/null; then
    for node in ollama-node1 ollama-node2; do
        READY=$(kubectl get deployment "$node" -n paperknight-ai -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        if [[ "${READY:-0}" -ge 1 ]]; then
            # Check model is loaded
            POD=$(kubectl get pod -n paperknight-ai -l "app=$node" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
            if [[ -n "$POD" ]]; then
                HAS_MODEL=$(kubectl exec -n paperknight-ai "$POD" -- ollama list 2>/dev/null | grep -c "lfm2" || echo "0")
                if [[ "$HAS_MODEL" -ge 1 ]]; then
                    pass "$node: running + LFM2-24B loaded"
                else
                    warn "$node: running but model not loaded yet (may still be pulling)"
                fi
            else
                pass "$node: running"
            fi
        else
            fail "$node: not ready"
            if [[ "$FIX" == "true" ]]; then
                echo "  → Restarting $node..."
                kubectl rollout restart deployment/"$node" -n paperknight-ai 2>/dev/null || true
            fi
        fi
    done

    # Coordinator
    COORD_READY=$(kubectl get deployment pk-coordinator -n paperknight-ai -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [[ "${COORD_READY:-0}" -ge 1 ]]; then
        # Test coordinator health endpoint
        COORD_HEALTH=$(kubectl exec -n paperknight-ai deployment/pk-coordinator -- \
            curl -sf http://localhost:8000/health 2>/dev/null || echo "")
        if [[ -n "$COORD_HEALTH" ]]; then
            pass "coordinator: running + /health OK"
        else
            warn "coordinator: running but /health not responding yet"
        fi
    else
        fail "coordinator: not ready"
        if [[ "$FIX" == "true" ]]; then
            kubectl rollout restart deployment/pk-coordinator -n paperknight-ai 2>/dev/null || true
        fi
    fi

    # DaemonSet
    DS_DESIRED=$(kubectl get daemonset pk-pipeline-agent -n paperknight-ai -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
    DS_READY=$(kubectl get daemonset pk-pipeline-agent -n paperknight-ai -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
    if [[ "${DS_READY:-0}" -ge 1 ]] && [[ "$DS_READY" == "$DS_DESIRED" ]]; then
        pass "DaemonSet: $DS_READY/$DS_DESIRED agents running"
    else
        warn "DaemonSet: $DS_READY/$DS_DESIRED agents ready"
    fi
fi

# ---------------------------------------------------------------------------
section "RAG"

if command -v kubectl &>/dev/null; then
    CHROMA_READY=$(kubectl get deployment chromadb -n paperknight-ai -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [[ "${CHROMA_READY:-0}" -ge 1 ]]; then
        # Test ChromaDB heartbeat
        CHROMA_HB=$(kubectl exec -n paperknight-ai deployment/chromadb -- \
            curl -sf http://localhost:8000/api/v1/heartbeat 2>/dev/null || echo "")
        if [[ -n "$CHROMA_HB" ]]; then
            pass "ChromaDB: running + heartbeat OK"
        else
            warn "ChromaDB: running but heartbeat not responding yet"
        fi
    else
        warn "ChromaDB: not deployed (run: kubectl apply -f configs/rag/chromadb-pk-deployment.yaml)"
    fi
fi

# ---------------------------------------------------------------------------
section "Remote Access (Tailscale)"

if command -v tailscale &>/dev/null; then
    TS_STATUS=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('BackendState',''))" 2>/dev/null || echo "unknown")
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "")
    if [[ "$TS_STATUS" == "Running" ]] && [[ -n "$TS_IP" ]]; then
        pass "Tailscale: connected ($TS_IP)"
    elif [[ "$TS_STATUS" == "NeedsLogin" ]]; then
        warn "Tailscale: needs login  →  sudo tailscale up --ssh"
    else
        warn "Tailscale: $TS_STATUS  →  run tailscale-setup.sh"
    fi
else
    warn "Tailscale: not installed  →  run tailscale-setup.sh"
fi

# ---------------------------------------------------------------------------
section "pk CLI"

if command -v pk &>/dev/null; then
    pass "pk CLI: installed"
    PROFILE_FILE="$HOME/.pk/profile.yaml"
    if [[ -f "$PROFILE_FILE" ]]; then
        PROFILE_NAME=$(python3 -c "import yaml; d=yaml.safe_load(open('$PROFILE_FILE')); print(d.get('name','not set'))" 2>/dev/null || echo "?")
        COORD_URL=$(python3 -c "import yaml; d=yaml.safe_load(open('$PROFILE_FILE')); print(d.get('coordinator_url','not set'))" 2>/dev/null || echo "?")
        pass "profile: $PROFILE_NAME → $COORD_URL"
    else
        warn "No profile found  →  run install.sh or pk profile chriso"
    fi
else
    warn "pk not in PATH  →  run install.sh or add ~/.local/bin to PATH"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
TOTAL=$((PASS+FAIL+WARN))

if [[ "$QUIET" != "true" ]]; then
    echo ""
    echo -e "${BOLD}Results: ${GREEN}${PASS} passed${RESET}  ${YELLOW}${WARN} warnings${RESET}  ${RED}${FAIL} failed${RESET}  (${TOTAL} checks)"
    echo ""

    if [[ "$FAIL" -eq 0 ]] && [[ "$WARN" -eq 0 ]]; then
        echo -e "${GREEN}  All checks passed. paperknight AI is healthy.${RESET}"
    elif [[ "$FAIL" -eq 0 ]]; then
        echo -e "${YELLOW}  Warnings present but system should be functional.${RESET}"
    else
        echo -e "${RED}  $FAIL check(s) failed. See above for fix commands.${RESET}"
        echo ""
        echo "  Run with --fix to attempt automatic restart of failed components:"
        echo "    bash verify.sh --fix"
    fi
    echo ""
fi

# Exit 1 if any hard failures
[[ "$FAIL" -eq 0 ]]
