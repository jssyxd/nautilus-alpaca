# -------------------------------------------------------------------------------------------------
#  Unit and Integration Tests for WebSocket Reliability, Trade Updates & Order State Machine
# -------------------------------------------------------------------------------------------------

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets

from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE
from nautilus_trader.adapters.alpaca.execution import AlpacaExecutionClient
from nautilus_trader.adapters.alpaca.websocket_client import (
    AlpacaMarketDataWebSocketClient,
    AlpacaTradeUpdatesWebSocketClient,
)
from nautilus_trader.common.component import LiveClock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import (
    LiquiditySide,
    OrderSide,
    OrderStatus,
    OrderType,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    InstrumentId,
    StrategyId,
    Symbol,
    TradeId,
    VenueOrderId,
)
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.objects import Price, Quantity


class TestAlpacaWebSocketReliability:
    """
    Tests for WebSocket client authentication, reconnection, backoff, and resubscription.
    """

    @pytest.mark.asyncio
    async def test_trade_updates_ws_authentication_and_dispatch(self):
        """
        Verify trade updates WS completes handshake and dispatches trade updates.
        """
        updates_received = []

        async def on_update(data):
            updates_received.append(data)

        ws_client = AlpacaTradeUpdatesWebSocketClient(
            api_key="TEST_KEY",
            api_secret="TEST_SECRET",
            paper_trading=True,
            on_trade_update=on_update,
        )

        class MockAsyncWS:
            def __init__(self):
                self.messages = [
                    json.dumps({
                        "stream": "trade_updates",
                        "data": {
                            "event": "fill",
                            "execution_id": "exec-12345",
                            "price": "150.25",
                            "qty": "10",
                            "order": {"client_order_id": "O-001", "id": "v-001"},
                        },
                    })
                ]

            async def send(self, data):
                pass

            async def recv(self):
                return json.dumps({"stream": "authorization", "data": {"status": "authorized"}})

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.messages:
                    return self.messages.pop(0)
                # Keep open until test stops it
                await asyncio.sleep(5)
                raise StopAsyncIteration

        mock_ws = MockAsyncWS()

        class MockConnectCM:
            async def __aenter__(self):
                return mock_ws

            async def __aexit__(self, exc_type, exc, tb):
                pass

        with patch("websockets.connect", return_value=MockConnectCM()):
            ws_client._is_running = True
            run_task = asyncio.create_task(ws_client._run_loop())
            await asyncio.sleep(0.05)
            ws_client._is_running = False
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

        assert len(updates_received) == 1
        assert updates_received[0]["event"] == "fill"
        assert updates_received[0]["execution_id"] == "exec-12345"

    @pytest.mark.asyncio
    async def test_trade_updates_reconnect_triggers_reconciliation(self):
        """
        Verify that a reconnection automatically triggers the reconciliation callback.
        """
        reconciled = False

        async def on_reconnected():
            nonlocal reconciled
            reconciled = True

        ws_client = AlpacaTradeUpdatesWebSocketClient(
            api_key="TEST_KEY",
            api_secret="TEST_SECRET",
            on_reconnected=on_reconnected,
        )
        ws_client._reconnect_delay = 0.01

        class MockReconnectWS:
            def __init__(self):
                self.connect_count = 0

            async def send(self, data):
                pass

            async def recv(self):
                return json.dumps({"stream": "authorization", "data": {"status": "authorized"}})

            def __aiter__(self):
                return self

            async def __anext__(self):
                self.connect_count += 1
                if self.connect_count == 1:
                    raise websockets.exceptions.ConnectionClosed(None, None)
                elif self.connect_count == 2:
                    await asyncio.sleep(5)
                    raise StopAsyncIteration
                raise StopAsyncIteration

        mock_reconnect = MockReconnectWS()

        class MockConnectCM:
            async def __aenter__(self):
                return mock_reconnect

            async def __aexit__(self, exc_type, exc, tb):
                pass

        with patch("websockets.connect", return_value=MockConnectCM()):
            ws_client._is_running = True
            run_task = asyncio.create_task(ws_client._run_loop())
            await asyncio.sleep(0.08)
            ws_client._is_running = False
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

        assert reconciled is True

    @pytest.mark.asyncio
    async def test_market_data_ws_resubscribes_on_reconnect(self):
        """
        Verify that the Market Data WS resubscribes to tracked trades and quotes upon reconnection.
        """
        ws_client = AlpacaMarketDataWebSocketClient(
            url="wss://stream.data.alpaca.markets/v2/iex",
            api_key="KEY",
            api_secret="SECRET",
        )
        ws_client._subscribed_trades.add("AAPL")
        ws_client._subscribed_quotes.add("MSFT")

        sent_messages = []

        class MockDataWS:
            async def send(self, data):
                sent_messages.append(data)

            async def recv(self):
                if len(sent_messages) == 0:
                    return json.dumps([{"T": "success", "msg": "connected"}])
                return json.dumps([{"T": "success", "msg": "authenticated"}])

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.sleep(5)
                raise StopAsyncIteration

        class MockConnectCM:
            async def __aenter__(self):
                return MockDataWS()

            async def __aexit__(self, exc_type, exc, tb):
                pass

        with patch("websockets.connect", return_value=MockConnectCM()):
            ws_client._is_running = True
            run_task = asyncio.create_task(ws_client._run_loop())
            await asyncio.sleep(0.05)
            ws_client._is_running = False
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

        resub_msg = None
        for msg_str in sent_messages:
            data = json.loads(msg_str)
            if data.get("action") == "subscribe":
                resub_msg = data
                break

        assert resub_msg is not None
        assert "AAPL" in resub_msg.get("trades", [])
        assert "MSFT" in resub_msg.get("quotes", [])


class TestAlpacaExecutionStateMachine:
    """
    Tests for order state machine transitions, event deduplication, and reconciliation.
    """

    def setup_method(self):
        self.clock = LiveClock()
        self.instrument_id = InstrumentId(Symbol("AAPL"), ALPACA_VENUE)
        self.instrument = TestInstrumentProvider.equity(symbol="AAPL", venue="ALPACA")

    @pytest.mark.asyncio
    async def test_trade_update_fill_event_and_deduplication(self):
        """
        Verify fill event triggers generate_order_filled and ignores duplicate execution IDs.
        """
        cache = MagicMock()
        cache.instrument.return_value = self.instrument

        mock_order = MagicMock()
        mock_order.strategy_id = StrategyId("S-001")
        mock_order.instrument_id = self.instrument_id
        mock_order.side = OrderSide.BUY
        mock_order.order_type = OrderType.LIMIT
        cache.order.return_value = mock_order

        client = MagicMock(spec=AlpacaExecutionClient)
        client._cache = cache
        client._clock = self.clock
        client._log = MagicMock()
        client._processed_trade_ids = set()

        # Bind the real handler
        client._handle_trade_update = lambda data: AlpacaExecutionClient._handle_trade_update(client, data)

        trade_update_data = {
            "event": "fill",
            "execution_id": "exec-abc-123",
            "price": "150.50",
            "qty": "100",
            "order": {
                "client_order_id": "O-TEST-1",
                "id": "venue-ord-1",
            },
        }

        # 1. First event: should generate fill
        await client._handle_trade_update(trade_update_data)
        assert client.generate_order_filled.call_count == 1
        args, kwargs = client.generate_order_filled.call_args
        assert kwargs["trade_id"] == TradeId("exec-abc-123")
        assert kwargs["last_qty"] == Quantity.from_int(100)
        assert kwargs["last_px"] == Price.from_str("150.50")

        # 2. Duplicate event: should be dropped by deduplication set
        await client._handle_trade_update(trade_update_data)
        assert client.generate_order_filled.call_count == 1  # count remains 1!
        assert "exec-abc-123" in client._processed_trade_ids

    @pytest.mark.asyncio
    async def test_order_reconciliation_logic(self):
        """
        Verify post-reconnect reconciliation queries REST orders and generates reports.
        """
        cache = MagicMock()
        cache.instrument.return_value = self.instrument

        http_mock = AsyncMock()
        # Mock GET /v2/account
        http_mock.get.side_effect = [
            json.dumps({"cash": "25000.00", "equity": "30000.00"}).encode(),
            # Mock GET /v2/orders
            json.dumps([
                {
                    "id": "ord-1",
                    "client_order_id": "cli-1",
                    "symbol": "AAPL",
                    "status": "filled",
                    "side": "buy",
                    "type": "limit",
                    "qty": "50",
                    "filled_qty": "50",
                    "filled_avg_price": "145.00",
                    "time_in_force": "day",
                }
            ]).encode(),
            # Mock GET /v2/positions
            json.dumps([]).encode(),
        ]

        client = MagicMock(spec=AlpacaExecutionClient)
        client._cache = cache
        client._clock = self.clock
        client._http_client = http_mock
        client._log = MagicMock()
        client._uuid_factory = UUID4()
        client.account_id = AccountId("ALPACA-master")

        # Bind real reconciliation methods
        client._update_account_state = lambda: AlpacaExecutionClient._update_account_state(client)
        client._parse_order_status_report = lambda data: AlpacaExecutionClient._parse_order_status_report(client, data)
        client._parse_position_status_report = lambda data: AlpacaExecutionClient._parse_position_status_report(client, data)
        client._reconcile_after_reconnect = lambda: AlpacaExecutionClient._reconcile_after_reconnect(client)

        await client._reconcile_after_reconnect()

        # Check account state updated
        assert client.generate_account_state.call_count == 1
        # Check order report sent
        assert client._send_order_status_report.call_count == 1
        report = client._send_order_status_report.call_args[0][0]
        assert report.client_order_id == ClientOrderId("cli-1")
        assert report.order_status == OrderStatus.FILLED
