# -------------------------------------------------------------------------------------------------
#  Alpaca WebSocket Client with Auto-reconnect & Resubscription
# -------------------------------------------------------------------------------------------------
"""
Alpaca WebSocket clients for Market Data and Trade Updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("AlpacaWebSocketClient")


class AlpacaTradeUpdatesWebSocketClient:
    """
    WebSocket client for Alpaca Trade Updates (`wss://paper-api.alpaca.markets/stream`
    or `wss://api.alpaca.markets/stream`).

    Handles:
    - Authentication handshake
    - Subscribing to `trade_updates`
    - Heartbeat / ping-pong
    - Automatic exponential backoff reconnection
    - Callback dispatch for order / fill events
    - Post-reconnect reconciliation trigger
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper_trading: bool = True,
        url_override: str | None = None,
        on_trade_update: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
        on_reconnected: Callable[[], Coroutine[Any, Any, None]] | None = None,
        log: Any = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._paper_trading = paper_trading

        if url_override:
            self._url = url_override
        elif paper_trading:
            self._url = "wss://paper-api.alpaca.markets/stream"
        else:
            self._url = "wss://api.alpaca.markets/stream"

        self._on_trade_update = on_trade_update
        self._on_reconnected = on_reconnected
        self._log = log or logger

        self._is_running = False
        self._is_connected = False
        self._ws: Any = None
        self._task: asyncio.Task | None = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def connect(self) -> None:
        """Start the WebSocket connection and background run loop."""
        if self._is_running:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._run_loop(), name="alpaca_trade_updates_ws")

    async def disconnect(self) -> None:
        """Gracefully disconnect and stop background loop."""
        self._is_running = False
        self._is_connected = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        is_reconnect = False
        while self._is_running:
            try:
                self._log.info(f"Connecting to Alpaca trade updates WS: {self._url}")
                async with websockets.connect(self._url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws
                    # Step 1: Authenticate
                    auth_msg = {
                        "action": "authenticate",
                        "data": {
                            "key_id": self._api_key,
                            "secret_key": self._api_secret,
                        },
                    }
                    await ws.send(json.dumps(auth_msg))

                    # Await auth response
                    resp = await ws.recv()
                    auth_data = json.loads(resp)
                    stream = auth_data.get("stream")
                    data = auth_data.get("data", {})

                    if stream == "authorization" and data.get("status") == "authorized":
                        self._log.info("Alpaca trade updates WebSocket authorized successfully")
                        self._is_connected = True
                        pass  # keep current reconnect_delay
                    else:
                        self._log.error(f"Alpaca WS auth failed: {auth_data}")
                        await asyncio.sleep(5.0)
                        continue

                    # Step 2: Subscribe to trade_updates
                    sub_msg = {
                        "action": "listen",
                        "data": {
                            "streams": ["trade_updates"],
                        },
                    }
                    await ws.send(json.dumps(sub_msg))

                    # Trigger post-reconnect reconciliation if this was a reconnect
                    if is_reconnect and self._on_reconnected:
                        try:
                            self._log.info("Triggering post-reconnect reconciliation...")
                            await self._on_reconnected()
                        except Exception as e:
                            self._log.error(f"Error during post-reconnect reconciliation: {e}")

                    is_reconnect = True

                    # Step 3: Message read loop
                    async for raw_msg in ws:
                        if not self._is_running:
                            break
                        try:
                            msg = json.loads(raw_msg)
                            msg_stream = msg.get("stream")
                            if msg_stream == "trade_updates" and self._on_trade_update:
                                await self._on_trade_update(msg.get("data", {}))
                            elif msg_stream == "listening":
                                self._log.info(f"Alpaca listening streams: {msg.get('data')}")
                        except Exception as e:
                            self._log.error(f"Error handling WS message: {e}")

            except (ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                self._is_connected = False
                if not self._is_running:
                    break
                self._log.warning(
                    f"Alpaca trade updates WS disconnected: {e}. Reconnecting in {self._reconnect_delay:.1f}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
            except Exception as e:
                self._is_connected = False
                if not self._is_running:
                    break
                self._log.error(f"Unexpected error in Alpaca WS loop: {e}")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)


class AlpacaMarketDataWebSocketClient:
    """
    WebSocket client for Alpaca Market Data (Stock IEX/SIP, Crypto, Options).
    
    Handles:
    - Authentication handshake ({action: auth, key: ..., secret: ...})
    - Dynamic subscription tracking (trades, quotes, bars)
    - Automatic resubscription on reconnect
    - Reconnect backoff
    - Dispatch callbacks to DataClient
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        api_secret: str,
        on_data_message: Callable[[list[dict[str, Any]]], Coroutine[Any, Any, None]] | None = None,
        log: Any = None,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._on_data_message = on_data_message
        self._log = log or logger

        self._is_running = False
        self._is_connected = False
        self._ws: Any = None
        self._task: asyncio.Task | None = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0

        # Subscribed symbols cache for resubscription on reconnect
        self._subscribed_trades: set[str] = set()
        self._subscribed_quotes: set[str] = set()
        self._subscribed_bars: set[str] = set()

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def connect(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._run_loop(), name="alpaca_market_data_ws")

    async def disconnect(self) -> None:
        self._is_running = False
        self._is_connected = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def subscribe(
        self,
        trades: list[str] | None = None,
        quotes: list[str] | None = None,
        bars: list[str] | None = None,
    ) -> None:
        if trades:
            self._subscribed_trades.update(trades)
        if quotes:
            self._subscribed_quotes.update(quotes)
        if bars:
            self._subscribed_bars.update(bars)

        if self._is_connected and self._ws:
            msg: dict[str, Any] = {"action": "subscribe"}
            if trades:
                msg["trades"] = list(trades)
            if quotes:
                msg["quotes"] = list(quotes)
            if bars:
                msg["bars"] = list(bars)
            await self._ws.send(json.dumps(msg))

    async def unsubscribe(
        self,
        trades: list[str] | None = None,
        quotes: list[str] | None = None,
        bars: list[str] | None = None,
    ) -> None:
        if trades:
            self._subscribed_trades.difference_update(trades)
        if quotes:
            self._subscribed_quotes.difference_update(quotes)
        if bars:
            self._subscribed_bars.difference_update(bars)

        if self._is_connected and self._ws:
            msg: dict[str, Any] = {"action": "unsubscribe"}
            if trades:
                msg["trades"] = list(trades)
            if quotes:
                msg["quotes"] = list(quotes)
            if bars:
                msg["bars"] = list(bars)
            await self._ws.send(json.dumps(msg))

    async def _run_loop(self) -> None:
        while self._is_running:
            try:
                self._log.info(f"Connecting to Alpaca Market Data WS: {self._url}")
                async with websockets.connect(self._url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws

                    # 1. Receive connected message
                    raw_greeting = await ws.recv()
                    greeting = json.loads(raw_greeting)
                    self._log.info(f"Connected greeting: {greeting}")

                    # 2. Authenticate
                    auth_msg = {
                        "action": "auth",
                        "key": self._api_key,
                        "secret": self._api_secret,
                    }
                    await ws.send(json.dumps(auth_msg))

                    raw_auth = await ws.recv()
                    auth_resp = json.loads(raw_auth)
                    # Returns a list of dicts, e.g. [{"T":"success","msg":"authenticated"}]
                    is_auth = False
                    if isinstance(auth_resp, list):
                        for item in auth_resp:
                            if item.get("T") == "success" and item.get("msg") == "authenticated":
                                is_auth = True
                                break

                    if not is_auth:
                        self._log.error(f"Market Data WS authentication failed: {auth_resp}")
                        await asyncio.sleep(5.0)
                        continue

                    self._is_connected = True
                    self._reconnect_delay = 1.0
                    self._log.info("Market Data WS authenticated successfully")

                    # 3. Resubscribe to existing subscriptions
                    if self._subscribed_trades or self._subscribed_quotes or self._subscribed_bars:
                        resub_msg: dict[str, Any] = {"action": "subscribe"}
                        if self._subscribed_trades:
                            resub_msg["trades"] = list(self._subscribed_trades)
                        if self._subscribed_quotes:
                            resub_msg["quotes"] = list(self._subscribed_quotes)
                        if self._subscribed_bars:
                            resub_msg["bars"] = list(self._subscribed_bars)
                        self._log.info(f"Resubscribing on reconnect: {resub_msg}")
                        await ws.send(json.dumps(resub_msg))

                    # 4. Message loop
                    async for raw_msg in ws:
                        if not self._is_running:
                            break
                        try:
                            msgs = json.loads(raw_msg)
                            if isinstance(msgs, list) and self._on_data_message:
                                await self._on_data_message(msgs)
                        except Exception as e:
                            self._log.error(f"Error handling market data WS message: {e}")

            except (ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                self._is_connected = False
                if not self._is_running:
                    break
                self._log.warning(
                    f"Alpaca Market Data WS disconnected: {e}. Reconnecting in {self._reconnect_delay:.1f}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
            except Exception as e:
                self._is_connected = False
                if not self._is_running:
                    break
                self._log.error(f"Unexpected error in Alpaca Market Data WS loop: {e}")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
