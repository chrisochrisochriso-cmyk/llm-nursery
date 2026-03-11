#!/bin/bash
# paperknight AI - Seed Security RAG
# Populates ChromaDB with CVEs, OWASP, and security references
# Run once after install: bash seed-rag-security.sh
#
# Takes ~10-20 mins depending on connection speed

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
info() { echo -e "${BLUE}  →${RESET} $*"; }
warn() { echo -e "${YELLOW}  !${RESET} $*"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   paperknight AI - Security RAG   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
echo ""
echo "Seeding knowledge base with CVEs, OWASP, and security references."
echo ""

# ---------------------------------------------------------------------------
# Top CVEs - Web App Security (bug bounty relevant)
# ---------------------------------------------------------------------------
echo -e "${BOLD}OWASP Top 10 CVEs${RESET}"

CVES=(
    # SQL Injection
    CVE-2021-27101
    # XSS
    CVE-2021-21315
    # RCE / deserialization
    CVE-2021-44228   # Log4Shell
    CVE-2022-22965   # Spring4Shell
    CVE-2021-26084   # Confluence RCE
    # SSRF
    CVE-2021-22005   # VMware SSRF
    # Auth bypass
    CVE-2022-0847    # Dirty Pipe
    CVE-2021-3156    # Sudo Baron Samedit
    # Web frameworks
    CVE-2022-42889   # Text4Shell
    CVE-2021-41773   # Apache path traversal
    CVE-2021-42013   # Apache RCE
    # APIs
    CVE-2022-27925   # Zimbra RCE
    CVE-2022-1388    # F5 BIG-IP auth bypass
)

for cve in "${CVES[@]}"; do
    info "Adding $cve..."
    pk add --cve "$cve" --quiet || warn "Skipped $cve (not found or already added)"
done

ok "CVEs added"

# ---------------------------------------------------------------------------
# OWASP URLs
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}OWASP References${RESET}"

URLS=(
    "https://owasp.org/www-project-top-ten/"
    "https://owasp.org/www-community/attacks/SQL_Injection"
    "https://owasp.org/www-community/attacks/xss/"
    "https://owasp.org/www-community/attacks/Server_Side_Request_Forgery"
    "https://owasp.org/www-community/attacks/Path_Traversal"
    "https://owasp.org/www-community/vulnerabilities/Insecure_Direct_Object_Reference"
    "https://owasp.org/www-community/attacks/Command_Injection"
    "https://owasp.org/www-community/attacks/CSRF"
    "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html"
    "https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html"
    "https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html"
    "https://cheatsheetseries.owasp.org/cheatsheets/JWT_Security_Cheat_Sheet.html"
    "https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html"
)

for url in "${URLS[@]}"; do
    info "Adding $url..."
    pk add --url "$url" --quiet || warn "Skipped $url"
done

ok "OWASP references added"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}║      Security RAG is ready!       ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
echo ""
echo "  Verify with:  pk search 'SQL injection'"
echo "  Or ask:       pk ask 'what CVEs should I check for in a login form?'"
echo ""
