#!/usr/bin/env bash
# start-shards.sh - Start pipeline shards sequentially, waiting for each to be ready

set -e

COMPOSE="docker compose"

wait_for_shard() {
    local id=$1
    local port=$((8080 + id))  # shard-0=8080, but they're all internal - use logs instead
    echo "Waiting for shard-$id to be ready..."
    while true; do
        if $COMPOSE logs "shard-$id" 2>/dev/null | grep -q "Shard $id ready"; then
            echo "✓ Shard $id ready"
            break
        fi
        sleep 5
    done
}

echo "Starting shard-0..."
$COMPOSE up -d shard-0
wait_for_shard 0

echo "Starting shard-1..."
$COMPOSE up -d shard-1
wait_for_shard 1

echo "Starting shard-2..."
$COMPOSE up -d shard-2
wait_for_shard 2

echo "Starting shard-3..."
$COMPOSE up -d shard-3
wait_for_shard 3

echo ""
echo "All 4 shards ready. Pipeline is up."
$COMPOSE ps
