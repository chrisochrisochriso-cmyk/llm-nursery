#!/usr/bin/env bash
# start-hybrid.sh - Start PaperKnight in hybrid mode
# shard-0 (embeddings) + Ollama (generation)
#
# Startup order:
#   1. shard-0  → loads Qwen2.5-3B, waits for healthy (2-3 min)
#   2. Ollama   → loads after shard-0 settles (avoids OOM)
#   3. ChromaDB → starts in parallel with Ollama
#   4. Coordinator → starts last

set -e

COMPOSE="docker compose"

echo ""
echo "PaperKnight AI - Hybrid Startup"
echo "================================"
echo ""

echo "Step 1/3 - Starting shard-0 (embeddings)..."
echo "  This takes 2-3 minutes while Qwen2.5-3B loads."
echo "  Memory will spike to ~6GB then drop to ~1.5GB."
echo ""
$COMPOSE up -d shard-0

echo "Waiting for shard-0 to be ready..."
until $COMPOSE ps shard-0 | grep -q "healthy"; do
    printf "."
    sleep 5
done
echo ""
echo "  ✓ shard-0 ready (embeddings online)"
echo ""

echo "Step 2/3 - Starting Ollama + ChromaDB..."
$COMPOSE up -d ollama chromadb
sleep 5
echo "  ✓ Ollama and ChromaDB starting"
echo ""

echo "Step 3/3 - Starting Coordinator..."
$COMPOSE up -d coordinator
echo "  ✓ Coordinator starting (model warmup ~30s)"
echo ""

echo "Waiting for coordinator to be ready..."
for i in $(seq 1 24); do
    if $COMPOSE logs coordinator 2>/dev/null | grep -q "Model warm and ready"; then
        echo "  ✓ Coordinator ready"
        break
    fi
    sleep 5
done

echo ""
echo "All services up. Running status check..."
echo ""
$COMPOSE ps
echo ""
echo "Test with: pk ask 'hello'"
echo "Web UI:    https://$(hostname -I | awk '{print $1}'):30800"
echo ""
