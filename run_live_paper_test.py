#!/usr/bin/env python3
"""
Alpaca Paper Trading live integration verification script.

Tests live API connectivity, account status, instrument fetching,
submitting limit order, receiving order updates, and canceling the order.
"""

import asyncio
import os
import sys

# Ensure local adapter is on path
sys.path.insert(0, ".")
import nautilus_trader.adapters
nautilus_trader.adapters.__path__.append(os.path.abspath("nautilus_trader/adapters"))

from nautilus_trader.adapters.alpaca.config import AlpacaExecClientConfig, AlpacaDataClientConfig
from nautilus_trader.adapters.alpaca.http.client import AlpacaHttpClient
from nautilus_trader.adapters.alpaca.websocket_client import AlpacaTradeUpdatesWebSocketClient
import msgspec


async def verify_alpaca_live_paper(api_key: str, api_secret: str):
    print("=" * 60)
    print("🚀 Starting Alpaca Live Paper Trading End-to-End Test")
    print("=" * 60)

    client = AlpacaHttpClient(
        api_key=api_key,
        api_secret=api_secret,
        paper_trading=True,
    )

    # 1. Test REST Authentication & Account Query
    print("\n[Step 1] Testing REST Authentication & Account Profile...")
    try:
        raw_account = await client.get("/v2/account")
        account = msgspec.json.decode(raw_account)
        print(f"  ✓ Connected! Account ID: {account.get('id')}")
        print(f"  ✓ Account Status: {account.get('status')}")
        print(f"  ✓ Cash Balance: ${account.get('cash')} USD")
        print(f"  ✓ Portfolio Equity: ${account.get('equity')} USD")
        print(f"  ✓ Buying Power: ${account.get('buying_power')} USD")
    except Exception as e:
        print(f"  ✗ Failed to connect or authenticate: {e}")
        return False

    # 2. Test Positions Query
    print("\n[Step 2] Testing Positions Query...")
    try:
        raw_positions = await client.get("/v2/positions")
        positions = msgspec.json.decode(raw_positions)
        print(f"  ✓ Current open positions: {len(positions)}")
        for pos in positions[:3]:
            print(f"    - {pos.get('symbol')}: qty={pos.get('qty')}, market_value=${pos.get('market_value')}")
    except Exception as e:
        print(f"  ✗ Failed to fetch positions: {e}")

    # 3. Test Trade Updates WebSocket
    print("\n[Step 3] Testing WebSocket Handshake & Trade Updates Stream...")
    trade_updates_received = []

    async def on_trade_update(update):
        print(f"  ⚡ Received trade_update: event={update.get('event')}, order_id={update.get('order', {}).get('id')}")
        trade_updates_received.append(update)

    ws_client = AlpacaTradeUpdatesWebSocketClient(
        api_key=api_key,
        api_secret=api_secret,
        paper_trading=True,
        on_trade_update=on_trade_update,
    )
    await ws_client.connect()
    await asyncio.sleep(2.0)
    print(f"  ✓ Trade Updates WebSocket connected: {ws_client.is_connected}")

    # 4. Test Submitting a Safe Limit Order (far below market)
    print("\n[Step 4] Submitting Limit Order for SPY at $100.00 (Buy 1 share)...")
    order_id = None
    try:
        order_req = {
            "symbol": "SPY",
            "qty": "1",
            "side": "buy",
            "type": "limit",
            "limit_price": "100.00",
            "time_in_force": "day",
        }
        raw_order = await client.post("/v2/orders", data=order_req)
        order_resp = msgspec.json.decode(raw_order)
        order_id = order_resp.get("id")
        print(f"  ✓ Order submitted successfully! VenueOrderId={order_id}")
        print(f"  ✓ Status: {order_resp.get('status')}")
    except Exception as e:
        print(f"  ✗ Failed to submit test order: {e}")

    await asyncio.sleep(2.0)

    # 5. Test Canceling the Order
    if order_id:
        print(f"\n[Step 5] Canceling the test order {order_id}...")
        try:
            await client.delete(f"/v2/orders/{order_id}")
            print("  ✓ Cancel request dispatched successfully")
        except Exception as e:
            print(f"  ✗ Failed to cancel test order: {e}")

    await asyncio.sleep(2.0)

    # 6. Cleanup
    await ws_client.disconnect()
    await client.close()

    print("\n" + "=" * 60)
    print("🎉 Live Paper Trading Verification Complete!")
    print(f"   Trade updates captured via WS: {len(trade_updates_received)}")
    print("=" * 60)
    return True


if __name__ == "__main__":
    api_key = os.getenv("ALPACA_API_KEY", "YOUR_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET", "")

    if not api_secret or api_secret == "YOUR_SECRET_KEY_HERE":
        print("[!] Note: ALPACA_API_SECRET not set in environment.")
        print(f"    Current API Key: {api_key}")
        print("    To run against live Paper Trading, run:")
        print("      export ALPACA_API_SECRET=\"your_alpaca_secret_here\"")
        print("      uv run python run_live_paper_test.py")
    else:
        asyncio.run(verify_alpaca_live_paper(api_key, api_secret))
