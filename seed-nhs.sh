#!/usr/bin/env bash
# seed-nhs.sh - Seed NHS health content into PaperKnight RAG
# Run this once after setup to prime the health knowledge base
#
# Usage: bash seed-nhs.sh

set -euo pipefail

ok()   { echo "  ✓ $*"; }
info() { echo "  → $*"; }
err()  { echo "  ✗ $*" >&2; }

add_url() {
    local url="$1"
    local label="$2"
    info "Adding: $label"
    if pk add --url "$url" --quiet; then
        ok "$label"
    else
        err "Failed: $label (skipping)"
    fi
    sleep 1  # be polite to NHS servers
}

echo ""
echo "PaperKnight AI - NHS Knowledge Base Seeder"
echo "==========================================="
echo ""

# ---------------------------------------------------------------------------
# Symptoms
# ---------------------------------------------------------------------------
echo "Symptoms..."
add_url "https://www.nhs.uk/conditions/headaches/" "Headaches"
add_url "https://www.nhs.uk/conditions/migraine/" "Migraine"
add_url "https://www.nhs.uk/conditions/tension-headaches/" "Tension headaches"
add_url "https://www.nhs.uk/conditions/chest-pain/" "Chest pain"
add_url "https://www.nhs.uk/conditions/shortness-of-breath/" "Shortness of breath"
add_url "https://www.nhs.uk/conditions/fatigue/" "Fatigue"
add_url "https://www.nhs.uk/conditions/dizziness/" "Dizziness"
add_url "https://www.nhs.uk/conditions/back-pain/" "Back pain"
add_url "https://www.nhs.uk/conditions/stomach-ache/" "Stomach ache"
add_url "https://www.nhs.uk/conditions/nausea-and-vomiting/" "Nausea and vomiting"
add_url "https://www.nhs.uk/conditions/joint-pain/" "Joint pain"
add_url "https://www.nhs.uk/conditions/insomnia/" "Insomnia / sleep problems"
add_url "https://www.nhs.uk/conditions/anxiety/" "Anxiety"
add_url "https://www.nhs.uk/conditions/depression/" "Depression"
add_url "https://www.nhs.uk/conditions/high-blood-pressure-hypertension/" "High blood pressure"

# ---------------------------------------------------------------------------
# Common conditions
# ---------------------------------------------------------------------------
echo ""
echo "Common conditions..."
add_url "https://www.nhs.uk/conditions/type-2-diabetes/" "Type 2 diabetes"
add_url "https://www.nhs.uk/conditions/type-1-diabetes/" "Type 1 diabetes"
add_url "https://www.nhs.uk/conditions/asthma/" "Asthma"
add_url "https://www.nhs.uk/conditions/chronic-obstructive-pulmonary-disease-copd/" "COPD"
add_url "https://www.nhs.uk/conditions/heart-disease/" "Heart disease"
add_url "https://www.nhs.uk/conditions/stroke/" "Stroke"
add_url "https://www.nhs.uk/conditions/atrial-fibrillation/" "Atrial fibrillation"
add_url "https://www.nhs.uk/conditions/high-cholesterol/" "High cholesterol"
add_url "https://www.nhs.uk/conditions/kidney-disease/" "Kidney disease"
add_url "https://www.nhs.uk/conditions/thyroid-disorders/" "Thyroid disorders"
add_url "https://www.nhs.uk/conditions/irritable-bowel-syndrome-ibs/" "IBS"
add_url "https://www.nhs.uk/conditions/acid-reflux/" "Acid reflux"
add_url "https://www.nhs.uk/conditions/urinary-tract-infections-utis/" "UTI"
add_url "https://www.nhs.uk/conditions/eczema-atopic/" "Eczema"
add_url "https://www.nhs.uk/conditions/psoriasis/" "Psoriasis"

# ---------------------------------------------------------------------------
# Urgent / emergency guidance
# ---------------------------------------------------------------------------
echo ""
echo "Urgent care guidance..."
add_url "https://www.nhs.uk/conditions/heart-attack/" "Heart attack"
add_url "https://www.nhs.uk/conditions/sepsis/" "Sepsis"
add_url "https://www.nhs.uk/conditions/anaphylaxis/" "Anaphylaxis / severe allergic reaction"
add_url "https://www.nhs.uk/nhs-services/urgent-and-emergency-care-services/when-to-go-to-ae/" "When to go to A&E"
add_url "https://www.nhs.uk/nhs-services/urgent-and-emergency-care-services/when-to-call-999/" "When to call 999"
add_url "https://www.nhs.uk/nhs-services/urgent-and-emergency-care-services/when-to-use-111/" "When to use NHS 111"

# ---------------------------------------------------------------------------
# Medicines / prescriptions
# ---------------------------------------------------------------------------
echo ""
echo "Medicines..."
add_url "https://www.nhs.uk/medicines/paracetamol-for-adults/" "Paracetamol"
add_url "https://www.nhs.uk/medicines/ibuprofen-for-adults/" "Ibuprofen"
add_url "https://www.nhs.uk/medicines/amoxicillin/" "Amoxicillin"
add_url "https://www.nhs.uk/medicines/metformin/" "Metformin"
add_url "https://www.nhs.uk/medicines/atorvastatin/" "Atorvastatin (statins)"
add_url "https://www.nhs.uk/medicines/omeprazole/" "Omeprazole"
add_url "https://www.nhs.uk/medicines/salbutamol/" "Salbutamol (inhaler)"

# ---------------------------------------------------------------------------
# Also seed the health prime as text
# ---------------------------------------------------------------------------
echo ""
echo "Health prime..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/data/health-prime.md" ]]; then
    pk add "$SCRIPT_DIR/data/health-prime.md" --quiet && ok "health-prime.md"
else
    err "health-prime.md not found at $SCRIPT_DIR/data/"
fi

echo ""
echo "Done! Run 'pk status' to see document count."
echo ""
pk status
