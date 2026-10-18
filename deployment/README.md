# Alpaca NautilusTrader Docker Deployment & Memory Guard

Production-grade Docker packaging and resource-guarded deployment configuration for running NautilusTrader with Alpaca Markets on resource-constrained VPS hosts.

---

## 🛡️ VPS Memory Guard & Resource Allocation

The deployment host operates on **961MB total RAM** hosting two existing containers. To prevent out-of-memory (OOM) killer incidents and ensure VPS stability, this container strictly enforces:

| Resource Guard | Specification | Mechanism |
| :--- | :--- | :--- |
| **RAM Hard Limit** | **180 MB** (`180m` / `180M`) | Docker memory cgroup limit (`mem_limit` + `deploy.resources.limits.memory`) |
| **Swap Limit** | **360 MB** (`360m`) | Prevents runaway memory paging while absorbing transient GC spikes |
| **CPU Limit** | **0.75 Cores** (`0.75`) | Cgroup CFS quota (`cpus` + `deploy.resources.limits.cpus`) |
| **Memory Allocation** | `MALLOC_ARENA_MAX=2` | Restricts glibc multi-threaded arena allocation to prevent heap fragmentation |
| **Bytecode Caching** | `PYTHONDONTWRITEBYTECODE=1` | Suppresses `.pyc` writing to reduce disk and overlayfs memory overhead |
| **Stream Buffering** | `PYTHONUNBUFFERED=1` | Direct log flushing without in-memory buffering |
| **Disk Protection** | `max-size: 10m`, `max-file: 3` | JSON log rotation capping total container disk usage to **30MB** |

---

## 📁 Directory Structure

```
deployment/
├── Dockerfile              # Multi-stage lean Debian Bookworm build with non-root security
├── docker-compose.yml      # Orchestration with 180MB memory, 0.75 CPU, health check & log rotation
├── entrypoint.sh           # Safe container entrypoint with memory flags
├── healthcheck.py          # Real-time memory threshold and connectivity monitor
├── .env.example            # Environment template for Alpaca API credentials
└── README.md               # Operations and verification guide
```

---

## 🚀 Quick Start

### 1. Configure Credentials
Copy `.env.example` to `.env` in the repository root (or set environment variables):
```bash
cp deployment/.env.example .env
# Edit .env with your Alpaca API credentials
nano .env
```

### 2. Build and Launch
Launch using Docker Compose:
```bash
# Build and run in detached mode
docker compose -f deployment/docker-compose.yml up -d --build
```

### 3. Verify Container Status & Resource Guard
Check container status and health check:
```bash
# Verify container is running and healthy
docker compose -f deployment/docker-compose.yml ps

# Monitor real-time memory usage (must remain strictly <= 180MB)
docker stats alpaca-nautilus-trader --no-stream
```

### 4. View Container Logs
```bash
# Follow logs
docker compose -f deployment/docker-compose.yml logs -f
```

### 5. Graceful Stop
The container is configured with `stop_grace_period: 30s` to allow active WebSocket streams and open orders to disconnect cleanly:
```bash
docker compose -f deployment/docker-compose.yml down
```

---

## 🔍 Health Check Specifications

The health check runs `deployment/healthcheck.py` every **30 seconds**:
- **Cgroup Memory Audit**: Reads `/sys/fs/cgroup/memory.current` (cgroups v2) or `/sys/fs/cgroup/memory/memory.usage_in_bytes` (cgroups v1) and verifies memory consumption is under 175MB.
- **Alpaca Connectivity Audit**: Pings `https://paper-api.alpaca.markets/v2/clock` to ensure network connectivity to Alpaca venue endpoints.
- **Fail Threshold**: 3 consecutive failures trigger Docker unhealthy status.
