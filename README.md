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

## License

MIT
