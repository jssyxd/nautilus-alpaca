# nautilus-alpaca

[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NautilusTrader](https://img.shields.io/badge/NautilusTrader-1.231.0+-green.svg)](https://github.com/nautechsystems/nautilus_trader)
[![Tests: 85 Passed](https://img.shields.io/badge/Tests-85%20Passed-brightgreen.svg)]()

Production-ready **Alpaca Markets** API Adapter for the **NautilusTrader** algorithmic trading platform.

---

## 🌟 Key Highlights & Enhancements

This adapter resolves critical reliability issues found in unmerged prototypes (such as PR #3375) and brings production-grade stability:

1. **Dual WebSocket Channels**:
   - **Trade Updates Stream (`wss://paper-api.alpaca.markets/stream`)**: Direct integration with real-time order lifecycle events (`new`, `fill`, `partial_fill`, `canceled`, `expired`, `rejected`).
   - **Market Data Stream (`wss://stream.data.alpaca.markets/v2/{feed}`)**: High-performance streaming of Quotes (`q`), Trades (`t`), and Minute Bars (`b`) for US equities and crypto.
2. **Auto-Reconnect with Exponential Backoff**:
   - Connection watchdog with ping/pong heartbeats.
   - Automatic reconnect backoff (1.0s to 30.0s) to prevent API rate-limit penalties during network flickers.
3. **Automated Post-Reconnect Reconciliation (State Self-Healing)**:
   - When a WebSocket reconnects, the adapter automatically triggers a 3-step state audit against Alpaca REST APIs:
     1. Refreshes cash balance and portfolio equity (`AccountState`).
     2. Reconciles open and in-flight orders (`OrderStatusReport`).
     3. Reconciles open portfolio positions (`PositionStatusReport`).
4. **Trade Event Deduplication**:
   - Built-in `_processed_trade_ids` filter preventing duplicate execution reports from inflating position size and cash balance.
5. **Full Order Management**:
   - Support for market, limit, stop, stop-limit, trailing stop, bracket, and multi-leg option orders.
   - Order modification via `PATCH /v2/orders/{id}` with `generate_order_updated`.
   - Cancel failure protection with `generate_order_cancel_rejected`.
6. **Multi-Asset Support**:
   - US Equities & ETFs.
   - Cryptocurrencies (with spot TIF constraints and zero-margin guards).
   - Equity Options with margin requirements and Non-Trade Activity (NTA: Exercise, Assignment, Expiry) tracking.

---

## 📁 Repository Structure

```
.
├── nautilus_trader/adapters/alpaca/
│   ├── websocket_client.py     # Resilient dual WebSocket clients
│   ├── execution.py            # ExecutionClient with state machine & reconciliation
│   ├── data.py                 # DataClient with real-time streaming & bar queries
│   ├── config.py               # AlpacaDataClientConfig & AlpacaExecClientConfig
│   ├── providers.py            # Instrument & currency providers
│   ├── margin.py               # Complex options margin calculator
│   └── http/                   # HTTP client and authentication helpers
├── tests/                      # 85 comprehensive unit, integration & reliability tests
├── audit_reports/              # Independent multi-agent audit reports
│   ├── auditor_01_api_interface.md
│   ├── auditor_02_state_machine.md
│   └── auditor_03_websocket_data.md
├── run_live_paper_test.py      # End-to-end Paper Trading live verification script
├── .env.example                # Configuration template
├── pyproject.toml              # Dependencies & packaging metadata
└── ALPACATRADING_ADAPTER_REPORT.md # Technical specification & evaluation
```

---

## 🚀 Quick Start

### 1. Installation

Using `uv` (recommended):

```bash
uv sync
```

Or install with pip:
```bash
pip install nautilus-trader websockets msgspec httpx pytest pytest-asyncio
```

### 2. Run Test Suite

```bash
uv run pytest tests/ -v
```
All **85 tests** (configuration, state machine, reliability injection, options margin, order modification) pass out of the box.

### 3. Paper Trading Live Verification

Set your Alpaca API credentials in `.env` (or environment variables):

```bash
export ALPACA_API_KEY="your_api_key"
export ALPACA_API_SECRET="your_api_secret"
export ALPACA_PAPER_TRADING=true
```

Execute the live smoke test script:

```bash
uv run python run_live_paper_test.py
```

The script will automatically test:
- REST authentication and account equity/cash check.
- Open positions retrieval.
- WebSocket Trade Updates long-lived handshake.
- Submitting a safe limit buy order.
- Capturing the real-time order acceptance event over WebSocket.
- Canceling the test order and verifying the canceled status.

---

## 🛡️ License

This project is licensed under the GNU Lesser General Public License Version 3.0 (LGPL-3.0).
