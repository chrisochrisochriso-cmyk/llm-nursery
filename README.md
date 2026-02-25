# LLM-Nursery

Local AI model training platform on Kubernetes. Train language models on your laptop with zero cloud costs.

## What It Does

LLM-Nursery runs AI training workloads as Kubernetes Jobs with persistent storage. Models survive pod restarts and can be progressively improved through multiple training sessions.

**Key Features:**
- **CPU-only training** - No GPU required
- **Persistent models** - Trained weights survive pod deletion
- **Progressive training** - Each session builds on previous checkpoints
- **Ephemeral compute** - Training pods terminate after saving, freeing RAM
- **Local-first** - Runs on Docker Desktop, Minikube, or any K8s cluster

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM-NURSERY CLUSTER                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │ Training Job │    │ Training Job │    │  Test Job    │   │
│  │ (Basic Level)│───▶│(Cmd System)  │───▶│ (Inference)  │   │
│  │              │    │              │    │              │   │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘   │
│         │                   │                   │           │
│         │    ┌──────────────┴──────────────┐    │           │
│         └───▶│     Persistent Storage      │◀───┘           │
│              │         (PVC 5Gi)           │                │
│              │  /models/basic-level/       │                │
│              │  /models/command-system/    │                │
│              └─────────────────────────────┘                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

Training Jobs are ephemeral - they train, save to storage, and terminate. Models persist on the PVC and can be loaded by subsequent jobs.

## Results Achieved

| Training Level | Score | Status |
|----------------|-------|--------|
| Basic Q&A | 100% (4/4) | Working |
| Command System | 50% (2/4) | Needs parameter pool |

### Basic Training
- 10 epochs, loss dropped from 4.18 to 0.31
- 100% accuracy on security Q&A
- ~10 minutes on MacBook CPU

### Command System
- Learns command prefixes (#Q, #T, #V, #S)
- Conversational (#Q) and verification (#V) working
- Structured output (#T, #S) needs more capacity

See [Session Notes](docs/2026-01-19-session-notes.md) for detailed results.

## Quick Start

### Prerequisites
- Kubernetes cluster (Docker Desktop, Minikube, or cloud)
- kubectl configured
- ~4GB RAM available

### 1. Create Namespace and Storage

```bash
kubectl create namespace llm-nursery
kubectl apply -f configs/storage/storage-infrastructure.yaml
```

### 2. Build Training Image

```bash
docker build -f configs/Dockerfile.llm-trainer -t llm-trainer:v2 .
```

### 3. Load Training Data

```bash
kubectl create configmap security-training-data \
  --from-file=training-data.json=data/security-training-data-v2.json \
  -n llm-nursery
```

### 4. Run Basic Training

```bash
kubectl apply -f configs/training/train-basic-level.yaml
kubectl logs -f job/train-basic-level -n llm-nursery
```

### 5. Verify Persistence

```bash
# Delete the job
kubectl delete job train-basic-level -n llm-nursery

# Model still exists on storage
kubectl exec -n llm-nursery deployment/storage-node -- \
  ls -la /storage/models/basic-level/
```

## Project Structure

```
llm-nursery/
├── configs/
│   ├── Dockerfile.llm-trainer    # Training image with PyTorch + Transformers
│   ├── storage/
│   │   └── storage-infrastructure.yaml  # PVC and storage node
│   ├── training/
│   │   ├── train-basic-level.yaml       # Basic Q&A training
│   │   └── train-command-system.yaml    # Command format training
│   └── testing/
│       ├── test-commands.yaml           # Inference testing
│       └── test-security-qa-v4.yaml     # Q&A evaluation
├── data/
│   ├── security-training-data-v2.json        # Basic training pairs
│   └── security-training-data-commands.json  # Command format examples
├── docs/
│   ├── 2026-01-19-session-notes.md      # Training results
│   └── parameter-pool-experiment.md     # Next phase design
└── README.md
```

## How It Works

### Training Pipeline

1. **ConfigMap** holds training data (JSON format)
2. **Job** spins up with training image (DistilGPT-2 base)
3. **Training** runs for N epochs, logs loss in real-time
4. **Evaluation** tests model against held-out questions
5. **Save** writes model + metadata to PVC
6. **Terminate** - Job completes, RAM freed

### Progressive Training

Each training level can load from previous checkpoints:

```python
# In train-command-system.yaml
base_model_path = "/storage/models/basic-level"
if os.path.exists(base_model_path):
    model = AutoModelForCausalLM.from_pretrained(base_model_path)
else:
    model = AutoModelForCausalLM.from_pretrained("distilgpt2")
```

### Model Persistence

Models are saved to a PersistentVolumeClaim that survives pod deletion:

```yaml
volumes:
- name: storage
  persistentVolumeClaim:
    claimName: model-storage
```

## Commands Reference

### Check Models
```bash
kubectl exec -n llm-nursery deployment/storage-node -- \
  ls -la /storage/models/

kubectl exec -n llm-nursery deployment/storage-node -- \
  cat /storage/models/basic-level/metadata.json
```

### Run Command System Training
```bash
kubectl create configmap command-training-data \
  --from-file=training-data.json=data/security-training-data-commands.json \
  -n llm-nursery

kubectl apply -f configs/training/train-command-system.yaml
kubectl logs -f job/train-command-system -n llm-nursery
```

### Test Inference
```bash
kubectl apply -f configs/testing/test-commands.yaml
kubectl logs -f job/test-commands -n llm-nursery
```

### Clean Up
```bash
kubectl delete namespace llm-nursery
```

## Resource Requirements

| Component | Memory | CPU |
|-----------|--------|-----|
| Training Job | 2-4 Gi | 1-2 cores |
| Storage Node | 128 Mi | 0.05 cores |
| PVC | 5 Gi | - |

Total: ~4GB RAM during training, minimal when idle.

## Roadmap

### Phase 2: Parameter Pool
Add specialized LoRA adapters for structured output:
- YAML generation module
- Security vocabulary module
- Dynamic loading based on command type

See [Parameter Pool Experiment](docs/parameter-pool-experiment.md) for design.

### Phase 3: Self-Scanning
Model analyzes its own Kubernetes manifests for security issues.

### Phase 4: Multi-Model Coordination
Multiple specialized models communicating through shared storage.

## Why This Exists

Cloud AI training is expensive and opaque. LLM-Nursery proves you can:

1. **Train locally** - No API costs, no data leaving your machine
2. **Use commodity hardware** - CPU-only, runs on laptops
3. **Build incrementally** - Progressive training, persistent storage
4. **Scale when needed** - Same configs work on cloud K8s

It's a proof-of-concept for parameter pool expansion: growing model capabilities by adding specialized modules rather than scaling base model size.

---

## Phase 2: Persistent Inference Extension

paperknight Threat Labs inference system extending LLM-Nursery with
Qwen2.5-Coder-1.5B-Instruct, a Signal interface, and distributed
pipeline parallelism.

### What Was Added

```
llm-nursery/
├── configs/inference/
│   ├── ollama-deployment.yaml      # Ollama Q4 inference server
│   ├── coordinator-deployment.yaml # FastAPI Signal<->inference bridge
│   ├── signal-cli-deployment.yaml  # Signal E2E messaging interface
│   └── daemonset-pipeline.yaml     # DaemonSet agent + 4 pipeline shards
└── src/
    ├── coordinator/
    │   ├── main.py                 # FastAPI coordinator service
    │   ├── Dockerfile
    │   └── requirements.txt
    └── shard/
        ├── shard.py                # HuggingFace pipeline shard service
        ├── Dockerfile
        └── requirements.txt
```

### Architecture

```
Signal Message
      │
      ▼
signal-cli-rest-api (port 8080)
      │  poll every 3s
      ▼
coordinator (FastAPI, port 8000)
      │
      ├─── [ollama mode, default] ──────────────────────────────────┐
      │                                                             │
      │    ollama-service:11434                                     │
      │    Qwen2.5-Coder:1.5b-instruct-q4_0                       │
      │                                                             │
      └─── [pipeline mode, multi-node] ────────────────────────────┤
                                                                    │
           shard-0 (layers 0-6, embed)                             │
                │  hidden states [batch, seq, hidden_dim]           │
           shard-1 (layers 7-13)                                    │
                │  hidden states                                     │
           shard-2 (layers 14-20)                                   │
                │  hidden states                                     │
           shard-3 (layers 21-27 + norm + lm_head)                  │
                │  next token ID (repeat for each generated token)   │
                │                                                    │
      ◄─────────┴────────────────────────────────────────────────────┘
      │
Signal Reply (in-thread)
```

The DaemonSet (`pipeline-agent`) runs on every K8s node and polls each
shard for health, providing a `/topology` endpoint that the coordinator
can query before choosing an inference mode.

### Quick Start

#### 1. Prerequisites

Existing LLM-Nursery namespace and PVC must be in place:

```bash
kubectl create namespace llm-nursery              # if not exists
kubectl apply -f configs/storage/storage-infrastructure.yaml
```

#### 2. Signal Credentials Secret

```bash
kubectl create secret generic signal-credentials \
  --from-literal=phone-number=+15551234567 \
  -n llm-nursery
```

#### 3. Build Images

```bash
# Coordinator
docker build -t coordinator:v1 src/coordinator/

# Pipeline shard (one image, used by all 4 shards via SHARD_ID env var)
docker build -t pipeline-shard:v1 src/shard/
```

#### 4. Deploy Inference Stack

```bash
# Ollama + Signal + coordinator (default: ollama inference mode)
kubectl apply -f configs/inference/ollama-deployment.yaml
kubectl apply -f configs/inference/signal-cli-deployment.yaml
kubectl apply -f configs/inference/coordinator-deployment.yaml

# DaemonSet routing agent (always deploy; shards start at replicas:0)
kubectl apply -f configs/inference/daemonset-pipeline.yaml
```

#### 5. Register Signal Account

```bash
# Register (triggers SMS/voice verification)
kubectl exec -n llm-nursery deployment/signal-cli -- \
  curl -X POST http://localhost:8080/v1/register/+15551234567

# Verify with the code Signal sends
kubectl exec -n llm-nursery deployment/signal-cli -- \
  curl -X POST http://localhost:8080/v1/verify/+15551234567/123456
```

#### 6. Test Inference

```bash
# Direct inference without Signal (coordinator must be running)
kubectl exec -n llm-nursery deployment/coordinator -- \
  curl -s -X POST http://localhost:8000/infer \
    -H 'Content-Type: application/json' \
    -d '{"message": "Write a Python MITM proxy skeleton using mitmproxy"}' \
  | python -m json.tool
```

### Pipeline Mode (Multi-Node or Opt-In)

Pipeline mode chains inference through 4 shard Deployments, each holding
1/4 of the transformer layers. On a single-node cluster, shards should be
started one at a time to avoid memory spikes during model loading:

```bash
# Scale shards sequentially (each briefly uses ~3GB during init)
for i in 0 1 2 3; do
  kubectl scale deployment pipeline-shard-$i --replicas=1 -n llm-nursery
  echo "Waiting for shard-$i to be ready..."
  kubectl rollout status deployment/pipeline-shard-$i -n llm-nursery
done

# Check all shards are healthy
kubectl exec -n llm-nursery deployment/coordinator -- \
  curl -s http://localhost:8000/pipeline/health | python -m json.tool

# Switch coordinator to pipeline mode
kubectl set env deployment/coordinator INFERENCE_MODE=pipeline -n llm-nursery
```

For true distributed deployment across 4 nodes:

```bash
# Minikube multi-node
minikube start --nodes 4 --memory 4096

# DaemonSet will schedule one pipeline-agent pod per node
# Shard deployments can be assigned to specific nodes via nodeSelector
```

### Resource Requirements

| Component | RAM Request | RAM Limit | Notes |
|-----------|------------|-----------|-------|
| Ollama | 1 Gi | 3 Gi | Q4 model ~1.1GB on PVC |
| signal-cli | 256 Mi | 512 Mi | |
| coordinator | 128 Mi | 256 Mi | |
| pipeline-agent (DaemonSet) | 64 Mi | 128 Mi | per node |
| pipeline-shard-{0..3} | 512 Mi each | 1.5 Gi each | default replicas: 0 |
| PVC | 5 Gi | - | Ollama model + HF weights + signal data |

**Ollama mode** (default): ~2-3 GB total RAM. Fits comfortably on 8 GB.

**Pipeline mode**: Each shard uses ~400 MB at steady state (~1.6 GB total for 4 shards)
but peaks at ~3 GB during startup while loading the full model to extract layers.
Start shards sequentially as shown above.

### Operational Commands

```bash
# Watch coordinator logs (Signal messages + responses)
kubectl logs -f deployment/coordinator -n llm-nursery

# Check what model is cached in Ollama
kubectl exec -n llm-nursery deployment/ollama -- ollama list

# Check pipeline topology
kubectl exec -n llm-nursery deployment/coordinator -- \
  curl -s http://localhost:8000/pipeline/health

# Check DaemonSet routing agent
kubectl exec -n llm-nursery daemonset/pipeline-agent -- \
  curl -s http://localhost:9090/topology

# Verify Signal connectivity
kubectl exec -n llm-nursery deployment/signal-cli -- \
  curl -s http://localhost:8080/v1/about
```

---

## paperknight AI - Remote Access from Wales

chriso can use paperknight AI from anywhere in the world, not just when connected
to dad's home network in Bristol. Here's how it works and how to set it up.

### How it works

The ZimaBoards in Bristol run a piece of software called **Tailscale**. Tailscale
creates a private, encrypted tunnel between your devices — the two ZimaBoards and
chriso's MacBook in Wales — without opening any ports on dad's router.

When chriso runs `pk ask` from Wales, the request travels through Tailscale's
WireGuard tunnel, gets processed by LFM2-24B on the ZimaBoards in Bristol, and
the response comes back to Wales. All traffic originates from dad's Bristol IP.
Nothing from outside can initiate a connection to the ZimaBoards.

```
chriso (Wales)                          Dad's house (Bristol)
──────────────                          ─────────────────────
MacBook                                 ZimaBoard 1
  │                                       │
  │  WireGuard encrypted tunnel           │
  └───────────── Tailscale ──────────────▶│  LFM2-24B inference
                                          │  paperknight AI
                                        ZimaBoard 2
```

**Security properties:**
- WireGuard encryption — same protocol used by major VPNs
- No ports opened on dad's router — ZimaBoards initiate outbound connections to Tailscale
- SSH is key-based — no passwords, no brute force risk
- Free tier covers 3 devices (both ZimaBoards + chriso's MacBook)
- All inference traffic stays within the Tailscale network — never touches the public internet

### Setup (one time)

**Step 0 — chriso creates the Tailscale account (do this first, in Wales):**

1. Go to [tailscale.com](https://tailscale.com) and create a free account
2. Install Tailscale on your MacBook: `brew install tailscale` or download from tailscale.com/download
3. Log in with that account: `sudo tailscale up`
4. Share the account email and password with johno so he can log the ZimaBoards in

**On the ZimaBoards** — `install.sh` handles this automatically.
During install, johno will be shown a URL and asked to log in — he uses chriso's account.
Each ZimaBoard gets a Tailscale IP like `100.x.x.x`. The installer prints it at the end.

**On chriso's MacBook** — already done if you followed Step 0 above.
To reconnect after a reboot or check status:

```bash
sudo tailscale up
tailscale ip -4    # shows your MacBook's Tailscale IP
```

Then point `pk` at the ZimaBoard's Tailscale IP:

```bash
pk profile --cluster-ip 100.x.x.x    # replace with ZimaBoard 1's Tailscale IP
pk status                              # verify it works from Wales
```

### Switching between home and remote

When you're on dad's WiFi in Bristol, use the LAN IP (faster, no Tailscale hop):

```bash
pk profile --cluster-ip 192.168.1.10   # or whatever ZimaBoard 1's LAN IP is
```

When you're back in Wales:

```bash
pk profile --cluster-ip 100.x.x.x     # Tailscale IP
```

`pk` works identically either way — same commands, same output.

### SSH access

Tailscale also gives chriso SSH access to both ZimaBoards from Wales:

```bash
ssh root@100.x.x.x    # ZimaBoard 1
ssh root@100.x.x.y    # ZimaBoard 2 (different Tailscale IP)
```

No password needed. Tailscale handles authentication — all devices are in chriso's account.

### Finding Tailscale IPs

- Run `tailscale ip -4` on any ZimaBoard to see its IP
- Or check the Tailscale admin panel at tailscale.com/admin
- The installer prints the IP at the end of setup

### If Tailscale stops working

```bash
# On the ZimaBoard (SSH in first, or use LAN):
sudo tailscale up --ssh --accept-routes

# Or re-run the standalone setup script:
bash tailscale-setup.sh
```

---

## License

MIT
