# -------------------------------------------------------------------------------------------------
#  Unit and Integration Tests for Order Modification, Cancel Rejection & Bar Streaming
# -------------------------------------------------------------------------------------------------

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE
from nautilus_trader.adapters.alpaca.data import AlpacaDataClient
from nautilus_trader.adapters.alpaca.execution import AlpacaExecutionClient
from nautilus_trader.common.component import LiveClock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import CancelOrder, ModifyOrder
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import (
    AccountId,
    TraderId,
    ClientOrderId,
    InstrumentId,
    StrategyId,
    Symbol,
    VenueOrderId,
)
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider


class TestAlpacaEnhancedOrderAndDataFeatures:
    """
    Tests covering order modification, cancel rejection handling, and historical/real-time bar handling.
    """

    def setup_method(self):
        self.clock = LiveClock()
        self.instrument_id = InstrumentId(Symbol("AAPL"), ALPACA_VENUE)
        self.instrument = TestInstrumentProvider.equity(symbol="AAPL", venue="ALPACA")

    @pytest.mark.asyncio
    async def test_order_modification_success(self):
        """
        Verify that _modify_order sends PATCH /v2/orders/{id} and triggers generate_order_updated.
        """
        cache = MagicMock()
        cache.instrument.return_value = self.instrument

        http_mock = AsyncMock()
        http_mock.patch.return_value = json.dumps({
            "id": "venue-ord-mod-1",
            "client_order_id": "cli-mod-1",
            "qty": "20",
            "limit_price": "155.00",
        }).encode()

        client = MagicMock(spec=AlpacaExecutionClient)
        client._cache = cache
        client._clock = self.clock
        client._http_client = http_mock
        client._log = MagicMock()

        # Bind real method
        client._modify_order = lambda cmd: AlpacaExecutionClient._modify_order(client, cmd)

        command = ModifyOrder(
            trader_id=TraderId("TESTER-001"),
            strategy_id=StrategyId("S-001"),
            instrument_id=self.instrument_id,
            client_order_id=ClientOrderId("cli-mod-1"),
            venue_order_id=VenueOrderId("venue-ord-1"),
            quantity=Quantity.from_int(20),
            price=Price.from_str("155.00"),
            trigger_price=None,
            command_id=UUID4(),
            ts_init=self.clock.timestamp_ns(),
        )

        await client._modify_order(command)

        # Verify PATCH called
        assert http_mock.patch.call_count == 1
        path, kwargs = http_mock.patch.call_args
        assert path[0] == "/v2/orders/venue-ord-1"
        assert kwargs["data"]["qty"] == "20"
        assert kwargs["data"]["limit_price"] == "155.00"

        # Verify event generated
        assert client.generate_order_updated.call_count == 1
        _, ev_kwargs = client.generate_order_updated.call_args
        assert ev_kwargs["client_order_id"] == ClientOrderId("cli-mod-1")
        assert ev_kwargs["venue_order_id"] == VenueOrderId("venue-ord-mod-1")

    @pytest.mark.asyncio
    async def test_order_cancel_rejected_on_error(self):
        """
        Verify that _cancel_order generates generate_order_cancel_rejected on HTTP failure.
        """
        cache = MagicMock()
        cache.instrument.return_value = self.instrument

        http_mock = AsyncMock()
        http_mock.delete.side_effect = RuntimeError("Order is already filled")

        client = MagicMock(spec=AlpacaExecutionClient)
        client._cache = cache
        client._clock = self.clock
        client._http_client = http_mock
        client._log = MagicMock()

        client._cancel_order = lambda cmd: AlpacaExecutionClient._cancel_order(client, cmd)

        command = CancelOrder(
            trader_id=TraderId("TESTER-001"),
            strategy_id=StrategyId("S-001"),
            instrument_id=self.instrument_id,
            client_order_id=ClientOrderId("cli-cancel-1"),
            venue_order_id=VenueOrderId("venue-cancel-1"),
            command_id=UUID4(),
            ts_init=self.clock.timestamp_ns(),
        )

        await client._cancel_order(command)

        assert client.generate_order_cancel_rejected.call_count == 1
        _, ev_kwargs = client.generate_order_cancel_rejected.call_args
        assert ev_kwargs["client_order_id"] == ClientOrderId("cli-cancel-1")
        assert "already filled" in ev_kwargs["reason"]

    @pytest.mark.asyncio
    async def test_market_data_bar_streaming_dispatch(self):
        """
        Verify that _handle_market_data_messages dispatches real-time Bar objects when message 'b' arrives.
        """
        cache = MagicMock()
        cache.instrument.return_value = self.instrument

        client = MagicMock(spec=AlpacaDataClient)
        client._cache = cache
        client._clock = self.clock
        client._log = MagicMock()

        # Bind real handler
        client._handle_market_data_messages = lambda msgs: AlpacaDataClient._handle_market_data_messages(client, msgs)

        bar_message = [
            {
                "T": "b",
                "S": "AAPL",
                "o": "150.10",
                "h": "152.00",
                "l": "149.80",
                "c": "151.50",
                "v": "5000",
                "t": "2026-10-17T15:30:00Z",
            }
        ]

        await client._handle_market_data_messages(bar_message)

        assert client._handle_data.call_count == 1
        bar_dispatched = client._handle_data.call_args[0][0]
        assert isinstance(bar_dispatched, Bar)
        assert bar_dispatched.open == Price.from_str("150.10")
        assert bar_dispatched.high == Price.from_str("152.00")
        assert bar_dispatched.low == Price.from_str("149.80")
        assert bar_dispatched.close == Price.from_str("151.50")
        assert bar_dispatched.volume == Quantity.from_int(5000)
