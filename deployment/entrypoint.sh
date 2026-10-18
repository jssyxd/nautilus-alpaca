#!/usr/bin/env bash
set -e

# ==============================================================================
# Container Entrypoint for NautilusTrader Alpaca Instance
# Enforces VPS Memory Guards & Environment Configurations
# ==============================================================================

# Glibc memory allocation optimization for tight memory constraints
export MALLOC_ARENA_MAX=${MALLOC_ARENA_MAX:-2}
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

echo "=========================================================="
echo "🛡️  NautilusTrader Alpaca Container Initializing"
echo "   - Target Memory Limit : 180MB"
echo "   - Target CPU Limit    : 0.75"
echo "   - MALLOC_ARENA_MAX    : ${MALLOC_ARENA_MAX}"
echo "   - Paper Trading Mode  : ${ALPACA_PAPER_TRADING:-true}"
echo "=========================================================="

# Check credentials warning
if [ -z "${ALPACA_API_SECRET}" ] || [ "${ALPACA_API_SECRET}" = "YOUR_SECRET_KEY_HERE" ]; then
    echo "[!] NOTE: ALPACA_API_SECRET is not configured or set to default placeholder."
    echo "    To connect with live paper trading, pass valid credentials via environment."
fi

# Execute user command or default runner
if [ $# -eq 0 ]; then
    exec python3 run_live_paper_test.py
else
    exec "$@"
fi
