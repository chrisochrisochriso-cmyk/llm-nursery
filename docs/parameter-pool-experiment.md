# Parameter Pool Experiment - Prep Document

## Problem Statement
DistilGPT-2 (82M params) successfully handles:
- Conversational Q&A (#Q) - 100%
- Basic verification (#V) - Working

But struggles with:
- Structured YAML output (#T) - Partial
- Security scan reports (#S) - Wrong domain

**Hypothesis**: The model lacks specialized capacity for structured output,
not general intelligence. Adding focused parameter modules could solve this.

---

## Parameter Pool Architecture

### Concept
```
┌─────────────────────────────────────────────────────┐
│                   PARAMETER POOL                     │
│                   (On PVC Storage)                   │
├─────────────────────────────────────────────────────┤
│  base-model/      (82M)  - General language         │
│  yaml-expert/     (+20M) - YAML structure           │
│  security-vocab/  (+15M) - Security terminology     │
│  scan-format/     (+10M) - Scan report structure    │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│              DYNAMIC LOADER                          │
│  Detects command → Loads relevant modules           │
│  #Q → base only (fast, 82M)                         │
│  #T → base + yaml-expert (102M)                     │
│  #S → base + yaml-expert + security-vocab (117M)   │
└─────────────────────────────────────────────────────┘
```

### Benefits
1. **Memory efficient** - Only load what's needed
2. **Incremental growth** - Add modules without retraining base
3. **Specialization** - Each module focused on one skill
4. **Swap-able** - Can upgrade individual modules

---

## Implementation Options

### Option A: LoRA Adapters (Recommended)
Low-Rank Adaptation - small trainable matrices added to frozen base.

```python
from peft import LoraConfig, get_peft_model

# Base model stays frozen
base_model = AutoModelForCausalLM.from_pretrained("distilgpt2")

# Add LoRA adapter for YAML
lora_config = LoraConfig(
    r=16,                    # Rank (smaller = fewer params)
    lora_alpha=32,
    target_modules=["c_attn", "c_proj"],
    lora_dropout=0.1
)
yaml_model = get_peft_model(base_model, lora_config)
```

**Pros**:
- Very small adapters (~2-5MB each)
- Fast to train
- Can stack multiple adapters

**Cons**:
- Requires `peft` library
- Slightly more complex loading

### Option B: Separate Fine-tuned Models
Train separate full models for each task.

```
/storage/models/
  base-model/           (327MB)
  yaml-specialist/      (327MB)
  security-specialist/  (327MB)
```

**Pros**:
- Simple to implement
- No new dependencies

**Cons**:
- Storage heavy (1GB+ for 3 models)
- Slower switching

### Option C: Prompt-based Switching
Use different system prompts to activate different "modes".

```python
yaml_prompt = "You are a YAML generator. Output valid YAML only.\n"
scan_prompt = "You are a security scanner. Output findings in YAML.\n"
```

**Pros**:
- No additional training
- Immediate to test

**Cons**:
- Limited effectiveness
- Uses context window

---

## Tomorrow's Experiment Plan

### Phase 1: Test LoRA Feasibility
1. Add `peft` to Dockerfile
2. Create minimal LoRA adapter training
3. Test if adapter improves #T output

### Phase 2: Train YAML Specialist Adapter
```yaml
# train-yaml-adapter.yaml
Training data: 20 YAML-focused examples
Epochs: 5
Output: /storage/adapters/yaml-specialist/
```

### Phase 3: Dynamic Loading Test
```python
# Load base
model = load("base-model")

# Detect command
if command.startswith("#T"):
    model.load_adapter("yaml-specialist")
elif command.startswith("#S"):
    model.load_adapter("yaml-specialist")
    model.load_adapter("security-vocab")

# Generate
output = model.generate(prompt)
```

---

## Files to Create

### 1. Updated Dockerfile
```dockerfile
# Dockerfile.llm-trainer-v3
FROM python:3.9-slim

RUN python -m pip install --upgrade pip
RUN python -m pip install --no-cache-dir \
    transformers \
    torch \
    accelerate \
    peft \                    # NEW: LoRA support
    --extra-index-url https://download.pytorch.org/whl/cpu

ENV PYTHONUNBUFFERED=1

RUN python -c "from transformers import AutoTokenizer, AutoModelForCausalLM; \
    AutoTokenizer.from_pretrained('distilgpt2'); \
    AutoModelForCausalLM.from_pretrained('distilgpt2')"

WORKDIR /workspace
```

### 2. YAML Training Data
```json
// data/yaml-specialist-training.json
[
  {
    "input": "Generate YAML for a critical finding about privileged containers",
    "output": "findings:\n  - id: CRIT-001\n    severity: CRITICAL\n    issue: Privileged container detected\n    evidence: \"privileged: true\"\n    remediation: Remove privileged flag"
  },
  // ... 20 more focused examples
]
```

### 3. Adapter Training Config
```yaml
# configs/training/train-yaml-adapter.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: train-yaml-adapter
  namespace: llm-nursery
spec:
  template:
    spec:
      containers:
      - name: trainer
        image: llm-trainer:v3
        # ... LoRA training script
```

### 4. Dynamic Loader Test
```yaml
# configs/testing/test-parameter-pool.yaml
# Tests loading adapters dynamically based on command
```

---

## Success Metrics

| Test | Current | Target |
|------|---------|--------|
| #T produces valid YAML | Partial | Full structure |
| #T has findings/severity/evidence | No | Yes |
| #S produces security_score | No | Yes |
| #S has verdict | No | Yes |
| Adapter load time | N/A | <2 seconds |
| Adapter size | N/A | <10MB each |

---

## Fallback Plan

If LoRA doesn't work well:
1. **More training data** - Add 20 more #T examples
2. **Longer training** - Try 15 epochs with current data
3. **Larger base model** - Try GPT-2 Medium (355M) instead of DistilGPT-2
4. **Post-processing** - Validate and fix YAML structure after generation

---

## Resources

- [PEFT Documentation](https://huggingface.co/docs/peft)
- [LoRA Paper](https://arxiv.org/abs/2106.09685)
- Current models: `/storage/models/`
- Current adapters: `/storage/adapters/` (to be created)
