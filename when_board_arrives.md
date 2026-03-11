# When the Mini PC Arrives

> **Hardware:** GMKtec Mini PC — AMD Ryzen 5 3500U, 16GB RAM, 1TB SSD, 2.5GbE NIC
> (Originally planned for ZimaBoard 832 — replaced by GMKtec)

## Step 1 - Physical setup
- Plug in power
- Connect to router via ethernet (not WiFi) — use the 2.5GbE port
- Boot it up (use a TV or monitor first time to complete any OS setup)
- SSH in or use keyboard + monitor to get a terminal

## Step 2 - Install on the Mini PC
```bash
sudo apt install -y git
git clone https://github.com/chrisochrisochriso-cmyk/llm-nursery.git
cd llm-nursery
bash install.sh
```
- Choose: **johno/other** (whoever is setting it up)
- Choose: **ZimaBoard** (same option, works fine on the GMKtec)
- Docker installs itself
- Llama 3.1 8B pulls (~5GB, takes a while on first run)
- At the end it prints the Mini PC's LAN IP — **write that IP down**

## Step 3 - Install on chriso's MacBook
```bash
git clone https://github.com/chrisochrisochriso-cmyk/llm-nursery.git
cd llm-nursery
bash install.sh
```
- Choose: **chriso**
- Choose: **MacBook**
- Enter the ZimaBoard LAN IP from Step 2

## Step 4 - Verify it works
```bash
pk status          # should show ollama: ready, rag: ok
pk ask 'hello'     # first response may take 30-60s (model loading)
```

## If something is wrong
```bash
# On the Mini PC (SSH in or use keyboard/TV):
docker compose ps                          # are all 3 containers running?
docker compose logs ollama                 # model pull errors?
docker compose logs pk-coordinator         # coordinator errors?
docker compose logs pk-chromadb            # RAG errors?

# Restart everything:
docker compose restart

# Nuclear option - wipe and start again:
docker compose down -v
bash install.sh
```

## Once it's confirmed working - Phase 2

### ClawHelperBot
A paid RAG bot for OpenClaw developers. OpenClaw is MIT licensed - commercial use confirmed.

**Plan:**
1. Scrape full OpenClaw docs + GitHub issues into ChromaDB
2. Wire a Telegram or Discord bot as the front-end
3. Stripe payments + API key per user
4. Token counter — cut off at 10,000 tokens per £10 purchase
5. Run 24/7 on ZimaBoard

**To build:**
- [ ] Scrape openclaw docs into RAG (`pk add --url` for each docs page)
- [ ] Build bot front-end (Telegram recommended - easy API)
- [ ] Stripe integration + API key generation
- [ ] Token usage tracking middleware in coordinator
- [ ] Deploy and test

### Charity deal
- Sell private AI setup to the charity chriso is working with
- Good anchor income to fund buying 3x 16GB ZimaBoards
- Could do this first before ClawHelperBot

## Hardware goal
3x GMKtec (or similar) Mini PCs = run larger models + handle concurrent users for ClawHelperBot
Note: with 16GB RAM on current box, could already run Llama 3.1 8B Q8 or a 13B Q4 model if needed.
