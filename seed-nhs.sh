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
# Common illnesses
# ---------------------------------------------------------------------------
echo ""
echo "Common illnesses..."
add_url "https://www.nhs.uk/conditions/common-cold/" "Common cold"
add_url "https://www.nhs.uk/conditions/flu/" "Flu"
add_url "https://www.nhs.uk/conditions/tonsillitis/" "Tonsillitis"
add_url "https://www.nhs.uk/conditions/diarrhoea-and-vomiting/" "Gastroenteritis"
add_url "https://www.nhs.uk/conditions/bronchitis/" "Bronchitis"
add_url "https://www.nhs.uk/conditions/sinusitis-sinus-infection/" "Sinusitis"
add_url "https://www.nhs.uk/conditions/earache/" "Earache"
add_url "https://www.nhs.uk/conditions/sore-throat/" "Sore throat"
add_url "https://www.nhs.uk/conditions/fever-in-adults/" "Fever"

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
# Mental health
# ---------------------------------------------------------------------------
echo ""
echo "Mental health..."
add_url "https://www.nhs.uk/mental-health/conditions/stress/" "Stress"
add_url "https://www.nhs.uk/mental-health/conditions/panic-disorder/" "Panic disorder"
add_url "https://www.nhs.uk/mental-health/conditions/obsessive-compulsive-disorder-ocd/" "OCD"
add_url "https://www.nhs.uk/mental-health/conditions/post-traumatic-stress-disorder-ptsd/" "PTSD"
add_url "https://www.nhs.uk/mental-health/conditions/eating-disorders/" "Eating disorders"
add_url "https://www.nhs.uk/mental-health/feelings-and-symptoms/loneliness-in-adults/" "Loneliness"
add_url "https://www.nhs.uk/mental-health/feelings-and-symptoms/grief-and-bereavement/" "Grief"

# ---------------------------------------------------------------------------
# Lifestyle and prevention
# ---------------------------------------------------------------------------
echo ""
echo "Lifestyle..."
add_url "https://www.nhs.uk/live-well/healthy-weight/" "Healthy weight"
add_url "https://www.nhs.uk/live-well/quit-smoking/" "Stop smoking"
add_url "https://www.nhs.uk/live-well/alcohol-advice/" "Alcohol advice"
add_url "https://www.nhs.uk/live-well/sleep-and-tiredness/sleep-tips/" "Sleep tips"

# ---------------------------------------------------------------------------
# Women's health
# ---------------------------------------------------------------------------
echo ""
echo "Women's health..."
add_url "https://www.nhs.uk/conditions/periods/" "Periods"
add_url "https://www.nhs.uk/conditions/menopause/" "Menopause"
add_url "https://www.nhs.uk/conditions/contraception/" "Contraception"

# ---------------------------------------------------------------------------
# First aid
# ---------------------------------------------------------------------------
echo ""
echo "First aid..."
add_url "https://www.nhs.uk/conditions/burns-and-scalds/" "Burns and scalds"
add_url "https://www.nhs.uk/conditions/choking/" "Choking"
add_url "https://www.nhs.uk/conditions/sprains-and-strains/" "Sprains and strains"

# ---------------------------------------------------------------------------
# Additional medicines
# ---------------------------------------------------------------------------
echo ""
echo "Additional medicines..."
add_url "https://www.nhs.uk/medicines/loratadine/" "Antihistamines (loratadine)"
add_url "https://www.nhs.uk/medicines/sertraline/" "Sertraline"
add_url "https://www.nhs.uk/medicines/ramipril/" "Ramipril"
add_url "https://www.nhs.uk/medicines/levothyroxine/" "Levothyroxine"
add_url "https://www.nhs.uk/medicines/aspirin-to-prevent-blood-clots/" "Aspirin"

# ---------------------------------------------------------------------------
# NHS system / jargon (for Bill's NHS client work)
# ---------------------------------------------------------------------------
echo ""
echo "NHS system and jargon..."
add_url "https://www.nhs.uk/nhs-services/" "NHS services overview"
add_url "https://www.nhs.uk/nhs-services/mental-health-services/" "NHS mental health services"
add_url "https://www.nhs.uk/nhs-services/patient-rights/" "NHS patient rights"
add_url "https://www.nhs.uk/nhs-services/how-to-complain/" "NHS complaints"
add_url "https://www.longtermplan.nhs.uk/" "NHS Long Term Plan"
add_url "https://www.nice.org.uk/about/" "What NICE does"

# ---------------------------------------------------------------------------
# Also seed the health prime as text
# ---------------------------------------------------------------------------
echo ""
echo "Priming documents..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/data/health-prime.md" ]]; then
    pk add "$SCRIPT_DIR/data/health-prime.md" --quiet && ok "health-prime.md"
else
    err "health-prime.md not found at $SCRIPT_DIR/data/"
fi

if [[ -f "$SCRIPT_DIR/data/bill-prime.md" ]]; then
    pk add "$SCRIPT_DIR/data/bill-prime.md" --quiet && ok "bill-prime.md"
else
    err "bill-prime.md not found at $SCRIPT_DIR/data/"
fi

echo ""
echo "Done! Run 'pk status' to see document count."
echo ""
pk status
