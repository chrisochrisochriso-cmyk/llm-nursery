# LLM-Nursery Session Notes - January 19, 2026

## Summary
First successful training run with persistence proven. Command system partially working.

---

## WHAT WORKED

### 1. Basic Training Pipeline (100% Success)
- **train-basic-level.yaml** achieved 100% score (4/4 questions)
- Loss decreased from 4.18 → 0.31 over 10 epochs
- Model saved to PVC at `/storage/models/basic-level/`
- **Persistence verified**: Deleted job, model survived
- Runtime: ~10 minutes on CPU

### 2. Infrastructure
- Namespace `llm-nursery` stable
- PVC `model-storage` (5Gi) working with `standard` storageClass
- Storage node deployment running for file inspection
- ConfigMaps for training data working

### 3. Docker Image Fixes
- Added `accelerate` to Dockerfile (was failing at runtime)
- Added `PYTHONUNBUFFERED=1` for real-time logs
- Image tag: `llm-trainer:v2`

### 4. Generation Parameter Fix
- `repetition_penalty=1.5` eliminated infinite loops
- `temperature=0.8` improved output variety
- Model now generates without repeating

---

## WHAT PARTIALLY WORKED

### Command System Training
- **Score**: 50% (2/4 commands passing)
- **#Q (Question)**: PASS - Generates conversational text about security
- **#V (Verify)**: PASS - Outputs true/false structure
- **#T (Task)**: FAIL - Outputs partial structure, not full YAML
- **#S (Scan)**: FAIL - Wrong domain output

### Analysis
The model learned:
- Command prefix recognition (#Q, #T, #V, #S)
- Basic output format differences
- Some security vocabulary

The model struggles with:
- Generating complete structured YAML
- Consistent field names (findings, severity, etc.)
- Domain-specific scan output

### Root Cause
DistilGPT-2 (82M params) may lack capacity for complex structured output.
Training data has 30 examples - may need more for structured formats.

---

## WHAT NEEDS PARAMETER POOL

### Current Limitation
82M parameter model can do:
- Simple Q&A (conversational)
- Basic true/false verification
- Pattern recognition

82M parameter model struggles with:
- Complex structured output (nested YAML)
- Multiple field generation
- Security-specific vocabulary depth

### Parameter Pool Hypothesis
Adding specialized parameter modules could help:
1. **YAML Structure Module** - Trained specifically on YAML generation
2. **Security Vocabulary Module** - CVE terms, K8s security concepts
3. **Structured Output Module** - findings/severity/evidence format

### Tomorrow's Experiment
Test if loading additional parameters improves #T and #S outputs.

---

## FILES CREATED/MODIFIED TODAY

### Configs
| File | Purpose | Status |
|------|---------|--------|
| `train-basic-level.yaml` | Basic Q&A training | Working |
| `train-command-system.yaml` | Command format training | Needs tuning |
| `test-commands.yaml` | Inference testing | Working |
| `Dockerfile.llm-trainer` | Base image with deps | Updated to v2 |

### Data
| File | Examples | Purpose |
|------|----------|---------|
| `security-training-data-v2.json` | 20 | Basic Q&A pairs |
| `security-training-data-commands.json` | 30 | Command format examples |

### Models Saved
| Path | Score | Status |
|------|-------|--------|
| `/storage/models/basic-level/` | 100% | Production ready |
| `/storage/models/command-system/` | 50% | Needs improvement |

---

## METRICS

### Training Performance
```
Basic Level:
  Epochs: 10
  Final Loss: 0.31
  Score: 100% (4/4)
  Runtime: 10m 18s

Command System:
  Epochs: 7
  Final Loss: 0.75
  Score: 50% (2/4)
  Runtime: 31m 12s
```

### Resource Usage
- Memory: 3-4Gi during training
- CPU: 1-2 cores (CPU-only training)
- Storage: ~650MB total models

---

## TOMORROW'S PLAN: Parameter Pool

### Concept
Instead of retraining entire model, add specialized "parameter packs":
1. Load base model (82M)
2. Load YAML-specialist weights
3. Merge/switch based on command type

### Files to Create
- `parameter-pool-loader.py` - Dynamic weight loading
- `yaml-specialist-training.yaml` - Train YAML-focused module
- `test-parameter-pool.yaml` - Test merged capabilities

### Success Criteria
- #T command produces valid YAML with all fields
- #S command produces security_score and findings
- No increase in base model size during inference
- Dynamic loading works (load on demand)

---

## QUICK REFERENCE

### Run Basic Training
```bash
kubectl apply -f configs/training/train-basic-level.yaml
kubectl logs -f job/train-basic-level -n llm-nursery
```

### Run Command Training
```bash
kubectl create configmap command-training-data \
  --from-file=training-data.json=data/security-training-data-commands.json \
  -n llm-nursery
kubectl apply -f configs/training/train-command-system.yaml
```

### Test Inference
```bash
kubectl apply -f configs/testing/test-commands.yaml
kubectl logs -f job/test-commands -n llm-nursery
```

### Check Models
```bash
kubectl exec -n llm-nursery deployment/storage-node -- ls -la /storage/models/
kubectl exec -n llm-nursery deployment/storage-node -- cat /storage/models/basic-level/metadata.json
```

---

## KEY LEARNINGS

1. **pip install at runtime is fragile** - Bake deps into Docker image
2. **PYTHONUNBUFFERED=1 is essential** - Otherwise logs appear stuck
3. **repetition_penalty prevents loops** - Critical for small models
4. **7 epochs is enough for small datasets** - 15 was overkill
5. **Structured output needs more capacity** - Parameter pool may solve this
