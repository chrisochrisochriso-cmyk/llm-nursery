#!/usr/bin/env bash
# seed-nhs-extra.sh - Seed additional NHS content into PaperKnight RAG
# For EXISTING GMKtec installs that already ran seed-nhs.sh
# (Fresh installs: use seed-nhs.sh which now includes all of this)
#
# Usage: bash seed-nhs-extra.sh

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
echo "PaperKnight AI - NHS Extra Seed (existing installs)"
echo "===================================================="
echo ""

# ---------------------------------------------------------------------------
# Mental health
# ---------------------------------------------------------------------------
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
# Bill prime document
# ---------------------------------------------------------------------------
echo ""
echo "Bill prime document..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/data/bill-prime.md" ]]; then
    pk add "$SCRIPT_DIR/data/bill-prime.md" --quiet && ok "bill-prime.md"
else
    err "bill-prime.md not found at $SCRIPT_DIR/data/"
fi

echo ""
echo "Done! Run 'pk status' to see updated document count."
echo ""
pk status
