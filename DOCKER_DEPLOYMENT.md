# nautilus-alpaca-live-docker

Docker deployment configurations for NautilusTrader with Alpaca Markets on VPS.

### 🛡️ VPS Memory & Resource Guard
VPS memory is constrained (~960MB total). This deployment enforces:
- Docker memory limit: `--memory="180m"` and `--memory-swap="360m"`.
- NanoCPUs limit: `--cpus="0.75"`.
- Swap optimization to avoid OOM killer from killing other active containers.

### 📊 Strategy Asset Matrix & Sub-Account Isolation
The strategy runs the **IntraBar Recalculation Matrix** across 5 isolated buckets:
1. **Silver (15m)** - `SLV` (15m bars)
2. **ES (15m)** - `SPY` (15m bars)
3. **Gold (1h)** - `GLD` (1h bars)
4. **BTC (1h)** - `BTC/USD` (1h bars)
5. **NQ (3h)** - `QQQ` (3h bars)

Each target is strictly allocated **exactly 1/5 (20%)** of initial starting equity.
- If a target's 20% allocation is lost, that asset's **Kill Switch** activates and permanently shuts down trading for that asset.
- Cross-bucket capital contamination is strictly blocked (cannot touch other assets' funds).
