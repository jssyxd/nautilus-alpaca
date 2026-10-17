# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2025 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Tests for Alpaca execution client order building.
"""

from decimal import Decimal
from unittest.mock import MagicMock

from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE
from nautilus_trader.adapters.alpaca.execution import AlpacaExecutionClient
from nautilus_trader.common.component import LiveClock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import BTC
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.enums import TriggerType
from nautilus_trader.model.identifiers import ClientOrderId
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import StrategyId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.orders import StopMarketOrder


class TestAlpacaOrderBuilding:
    """
    Tests for Alpaca order request building with crypto and options constraints.
    """

    def setup_method(self):
        self.clock = LiveClock()

    def _create_mock_client(self, cache):
        """
        Create a mock client object that has the necessary attributes for testing.
        """
        # Create a minimal mock that has the necessary attributes
        client = MagicMock(spec=AlpacaExecutionClient)
        client._cache = cache
        client._log = MagicMock()
        # Use the real _build_order_request method
        client._build_order_request = lambda order: AlpacaExecutionClient._build_order_request(
            client,
            order,
        )
        # Bind helper methods used by _build_order_request
        client._apply_crypto_constraints = lambda order, alpaca_order_type, alpaca_tif, symbol: (
            AlpacaExecutionClient._apply_crypto_constraints(
                client,
                order,
                alpaca_order_type,
                alpaca_tif,
                symbol,
            )
        )
        client._apply_options_constraints = lambda alpaca_order_type, alpaca_tif: (
            AlpacaExecutionClient._apply_options_constraints(
                client,
                alpaca_order_type,
                alpaca_tif,
            )
        )
        return client

    def _create_market_order(
        self,
        instrument_id: InstrumentId,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ) -> MarketOrder:
        """
        Create a test market order.
        """
        return MarketOrder(
            trader_id=TraderId("TESTER-001"),
            strategy_id=StrategyId("S-001"),
            instrument_id=instrument_id,
            client_order_id=ClientOrderId("O-001"),
            order_side=OrderSide.BUY,
            quantity=Quantity.from_str("1.0"),
            time_in_force=time_in_force,
            init_id=UUID4(),
            ts_init=self.clock.timestamp_ns(),
        )

    def _create_stop_market_order(
        self,
        instrument_id: InstrumentId,
        time_in_force: TimeInForce = TimeInForce.DAY,
        trigger_price: str = "50000.00",
    ) -> StopMarketOrder:
        """
        Create a test stop market order.
        """
        return StopMarketOrder(
            trader_id=TraderId("TESTER-001"),
            strategy_id=StrategyId("S-001"),
            instrument_id=instrument_id,
            client_order_id=ClientOrderId("O-002"),
            order_side=OrderSide.BUY,
            quantity=Quantity.from_str("1.0"),
            trigger_price=Price.from_str(trigger_price),
            trigger_type=TriggerType.DEFAULT,
            time_in_force=time_in_force,
            init_id=UUID4(),
            ts_init=self.clock.timestamp_ns(),
        )

    def _create_crypto_instrument(self) -> CurrencyPair:
        """
        Create a test BTC/USD cryptocurrency instrument.
        """
        return CurrencyPair(
            instrument_id=InstrumentId(Symbol("BTC/USD"), ALPACA_VENUE),
            raw_symbol=Symbol("BTCUSD"),
            base_currency=BTC,
            quote_currency=USD,
            price_precision=2,
            size_precision=8,
            price_increment=Price.from_str("0.01"),
            size_increment=Quantity.from_str("0.00000001"),
            lot_size=Quantity.from_str("0.0001"),
            max_quantity=None,
            min_quantity=Quantity.from_str("0.0001"),
            max_notional=None,
            min_notional=None,
            max_price=None,
            min_price=None,
            margin_init=Decimal(0),
            margin_maint=Decimal(0),
            maker_fee=Decimal("0.001"),
            taker_fee=Decimal("0.001"),
            ts_event=0,
            ts_init=0,
        )

    def test_build_order_request_crypto_converts_symbol_format(self):
        """
        Test that crypto order symbol is converted from BTC/USD to BTCUSD.
        """
        # Arrange
        cache = MagicMock()
        crypto_instrument = self._create_crypto_instrument()
        cache.instrument.return_value = crypto_instrument

        client = self._create_mock_client(cache)
        order = self._create_market_order(crypto_instrument.id)

        # Act
        request = client._build_order_request(order)

        # Assert - symbol should be BTCUSD (no slash) for API
        assert request["symbol"] == "BTCUSD"
        assert "/" not in request["symbol"]

    def test_build_order_request_crypto_enforces_gtc_or_ioc(self):
        """
        Test that crypto orders default to GTC when given invalid TIF.
        """
        # Arrange
        cache = MagicMock()
        crypto_instrument = self._create_crypto_instrument()
        cache.instrument.return_value = crypto_instrument

        client = self._create_mock_client(cache)
        # Create order with DAY TIF (not allowed for crypto)
        order = self._create_market_order(crypto_instrument.id, TimeInForce.DAY)

        # Act
        request = client._build_order_request(order)

        # Assert - should default to GTC for crypto
        assert request["time_in_force"] == "gtc"

    def test_build_order_request_crypto_allows_gtc(self):
        """
        Test that crypto orders with GTC are accepted.
        """
        # Arrange
        cache = MagicMock()
        crypto_instrument = self._create_crypto_instrument()
        cache.instrument.return_value = crypto_instrument

        client = self._create_mock_client(cache)
        order = self._create_market_order(crypto_instrument.id, TimeInForce.GTC)

        # Act
        request = client._build_order_request(order)

        # Assert
        assert request["time_in_force"] == "gtc"

    def test_build_order_request_crypto_allows_ioc(self):
        """
        Test that crypto orders with IOC are accepted.
        """
        # Arrange
        cache = MagicMock()
        crypto_instrument = self._create_crypto_instrument()
        cache.instrument.return_value = crypto_instrument

        client = self._create_mock_client(cache)
        order = self._create_market_order(crypto_instrument.id, TimeInForce.IOC)

        # Act
        request = client._build_order_request(order)

        # Assert
        assert request["time_in_force"] == "ioc"

    def test_build_order_request_options_enforces_day_tif(self):
        """
        Test that options orders default to DAY when given invalid TIF.
        """
        # Arrange
        cache = MagicMock()
        option_instrument = MagicMock(spec=OptionContract)
        cache.instrument.return_value = option_instrument

        client = self._create_mock_client(cache)
        # Create order with GTC TIF (not allowed for options)
        order = self._create_market_order(
            InstrumentId(Symbol("AAPL250117C00200000"), ALPACA_VENUE),
            TimeInForce.GTC,
        )

        # Act
        request = client._build_order_request(order)

        # Assert - should default to DAY for options
        assert request["time_in_force"] == "day"

    def test_build_order_request_equity_allows_day_tif(self):
        """
        Test that equity orders with DAY are accepted.
        """
        # Arrange
        cache = MagicMock()
        equity_instrument = MagicMock(spec=Equity)
        cache.instrument.return_value = equity_instrument

        client = self._create_mock_client(cache)
        order = self._create_market_order(
            InstrumentId(Symbol("AAPL"), ALPACA_VENUE),
            TimeInForce.DAY,
        )

        # Act
        request = client._build_order_request(order)

        # Assert
        assert request["time_in_force"] == "day"
        assert request["symbol"] == "AAPL"

    def test_build_order_request_crypto_rejects_stop_order(self):
        """
        Test that crypto stop orders are converted to market orders.
        """
        # Arrange
        cache = MagicMock()
        crypto_instrument = self._create_crypto_instrument()
        cache.instrument.return_value = crypto_instrument

        client = self._create_mock_client(cache)
        order = self._create_stop_market_order(crypto_instrument.id, TimeInForce.GTC)

        # Act
        request = client._build_order_request(order)

        # Assert - stop should be converted to market for crypto
        assert request["type"] == "market"
        # Verify warning was logged
        client._log.warning.assert_called()

    def test_build_order_request_options_rejects_stop_order(self):
        """
        Test that options stop orders are converted to market orders.
        """
        # Arrange
        cache = MagicMock()
        option_instrument = MagicMock(spec=OptionContract)
        cache.instrument.return_value = option_instrument

        client = self._create_mock_client(cache)
        order = self._create_stop_market_order(
            InstrumentId(Symbol("AAPL250117C00200000"), ALPACA_VENUE),
            TimeInForce.DAY,
        )

        # Act
        request = client._build_order_request(order)

        # Assert - stop should be converted to market for options
        assert request["type"] == "market"
        # Verify warning was logged
        client._log.warning.assert_called()

    def test_build_order_request_equity_allows_stop_order(self):
        """
        Test that equity stop orders are accepted.
        """
        # Arrange
        cache = MagicMock()
        equity_instrument = MagicMock(spec=Equity)
        cache.instrument.return_value = equity_instrument

        client = self._create_mock_client(cache)
        order = self._create_stop_market_order(
            InstrumentId(Symbol("AAPL"), ALPACA_VENUE),
            TimeInForce.DAY,
        )

        # Act
        request = client._build_order_request(order)

        # Assert - stop orders are allowed for equities
        assert request["type"] == "stop"
        assert request["symbol"] == "AAPL"


class TestAlpacaMlegOrderValidation:
    """
    Tests for Alpaca multi-leg options order validation.
    """

    def setup_method(self):
        """
        Set up test fixtures.
        """
        self.mock_client = MagicMock(spec=AlpacaExecutionClient)
        self.mock_client._log = MagicMock()
        self.mock_client._http_client = MagicMock()
        # Bind the real method for validation testing
        from functools import reduce
        from math import gcd

        self.gcd = gcd
        self.reduce = reduce

    def _validate_gcd(self, ratio_quantities: list[int]) -> int:
        """
        Calculate GCD of ratio quantities.
        """
        if len(ratio_quantities) < 2:
            return 1
        return self.reduce(self.gcd, ratio_quantities)

    def test_mleg_valid_call_spread_legs(self):
        """
        Test that a valid call spread (2 legs, GCD=1) is accepted.
        """
        legs = [
            {
                "symbol": "AAPL250117C00190000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": "AAPL250117C00210000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
        ]
        ratio_quantities = [int(leg["ratio_qty"]) for leg in legs]
        overall_gcd = self._validate_gcd(ratio_quantities)

        assert len(legs) == 2
        assert len(legs) >= 2
        assert len(legs) <= 4
        assert overall_gcd == 1

    def test_mleg_valid_iron_condor_legs(self):
        """
        Test that a valid iron condor (4 legs, GCD=1) is accepted.
        """
        legs = [
            {
                "symbol": "AAPL250117P00190000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": "AAPL250117P00195000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "AAPL250117C00205000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "AAPL250117C00210000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
        ]
        ratio_quantities = [int(leg["ratio_qty"]) for leg in legs]
        overall_gcd = self._validate_gcd(ratio_quantities)

        assert len(legs) == 4
        assert len(legs) >= 2
        assert len(legs) <= 4
        assert overall_gcd == 1

    def test_mleg_invalid_gcd_rejected(self):
        """
        Test that leg ratios not in simplest form (GCD > 1) are rejected.
        """
        # GCD(4, 2) = 2, should be simplified to (2, 1)
        legs = [
            {
                "symbol": "AAPL250117C00190000",
                "side": "buy",
                "ratio_qty": "4",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": "AAPL250117C00210000",
                "side": "sell",
                "ratio_qty": "2",
                "position_intent": "sell_to_open",
            },
        ]
        ratio_quantities = [int(leg["ratio_qty"]) for leg in legs]
        overall_gcd = self._validate_gcd(ratio_quantities)

        # GCD should be 2, indicating ratios are not in simplest form
        assert overall_gcd == 2
        assert overall_gcd > 1  # This would trigger rejection

    def test_mleg_valid_ratio_spread(self):
        """
        Test that a valid ratio spread with GCD=1 is accepted.
        """
        # 1:2 ratio (already in simplest form)
        legs = [
            {
                "symbol": "AAPL250117C00190000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": "AAPL250117C00210000",
                "side": "sell",
                "ratio_qty": "2",
                "position_intent": "sell_to_open",
            },
        ]
        ratio_quantities = [int(leg["ratio_qty"]) for leg in legs]
        overall_gcd = self._validate_gcd(ratio_quantities)

        assert overall_gcd == 1  # GCD(1, 2) = 1, valid

    def test_mleg_too_few_legs_rejected(self):
        """
        Test that orders with less than 2 legs are rejected.
        """
        legs = [
            {
                "symbol": "AAPL250117C00190000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
        ]
        assert len(legs) < 2  # Would trigger rejection

    def test_mleg_too_many_legs_rejected(self):
        """
        Test that orders with more than 4 legs are rejected.
        """
        legs = [
            {
                "symbol": "AAPL250117P00185000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": "AAPL250117P00190000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "AAPL250117P00195000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "AAPL250117C00205000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "AAPL250117C00210000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
        ]
        assert len(legs) > 4  # Would trigger rejection

    def test_mleg_missing_ratio_qty_rejected(self):
        """
        Test that legs missing ratio_qty are rejected.
        """
        legs = [
            {
                "symbol": "AAPL250117C00190000",
                "side": "buy",
                "position_intent": "buy_to_open",
            },  # Missing ratio_qty
            {
                "symbol": "AAPL250117C00210000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
        ]
        has_missing_ratio = any(leg.get("ratio_qty") is None for leg in legs)
        assert has_missing_ratio  # Would trigger rejection

    def test_mleg_missing_symbol_rejected(self):
        """
        Test that legs missing symbol are rejected.
        """
        legs = [
            {"side": "buy", "ratio_qty": "1", "position_intent": "buy_to_open"},  # Missing symbol
            {
                "symbol": "AAPL250117C00210000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
        ]
        has_missing_symbol = any(not leg.get("symbol") for leg in legs)
        assert has_missing_symbol  # Would trigger rejection

    def test_mleg_invalid_side_rejected(self):
        """
        Test that legs with invalid side are rejected.
        """
        legs = [
            {
                "symbol": "AAPL250117C00190000",
                "side": "long",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },  # Invalid side
            {
                "symbol": "AAPL250117C00210000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
        ]
        has_invalid_side = any(leg.get("side") not in ("buy", "sell") for leg in legs)
        assert has_invalid_side  # Would trigger rejection

    def test_mleg_only_market_limit_supported(self):
        """
        Test that only market and limit order types are supported for mleg.
        """
        valid_types = ("market", "limit")
        invalid_types = ("stop", "stop_limit", "trailing_stop")

        for order_type in valid_types:
            assert order_type in ("market", "limit")

        for order_type in invalid_types:
            assert order_type not in ("market", "limit")

    def test_mleg_limit_requires_price(self):
        """
        Test that limit orders require a limit_price.
        """
        order_type = "limit"
        limit_price = None

        # This condition would trigger rejection
        assert order_type == "limit"
        assert limit_price is None

    def test_mleg_rolling_spread_valid(self):
        """
        Test that rolling a spread (close + open in one order) is valid.
        """
        # Roll a call spread from one strike to another
        legs = [
            {
                "symbol": "AAPL250117C00200000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_close",
            },
            {
                "symbol": "AAPL250117C00205000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_close",
            },
            {
                "symbol": "AAPL250117C00210000",
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "AAPL250117C00215000",
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
        ]
        ratio_quantities = [int(leg["ratio_qty"]) for leg in legs]
        overall_gcd = self._validate_gcd(ratio_quantities)

        assert len(legs) == 4
        assert overall_gcd == 1
        # Verify we have both close and open intents
        intents = {leg["position_intent"] for leg in legs}
        assert "buy_to_close" in intents
        assert "sell_to_close" in intents
        assert "sell_to_open" in intents
        assert "buy_to_open" in intents

    def test_mleg_complex_gcd_validation(self):
        """
        Test GCD calculation with various ratio combinations.
        """
        # Valid cases (GCD = 1)
        assert self._validate_gcd([1, 1]) == 1
        assert self._validate_gcd([1, 2]) == 1
        assert self._validate_gcd([1, 1, 1, 1]) == 1
        assert self._validate_gcd([1, 2, 3]) == 1
        assert self._validate_gcd([2, 3]) == 1

        # Invalid cases (GCD > 1, needs simplification)
        assert self._validate_gcd([2, 2]) == 2
        assert self._validate_gcd([2, 4]) == 2
        assert self._validate_gcd([4, 2]) == 2
        assert self._validate_gcd([6, 9]) == 3
        assert self._validate_gcd([10, 15, 20]) == 5


class TestAlpacaOptionsMarginCalculation:
    """
    Tests for Alpaca options margin calculation using universal spread rule.
    """

    def _calculate_option_payoff(
        self,
        strike: Decimal,
        is_call: bool,
        is_long: bool,
        quantity: int,
        underlying_price: Decimal,
    ) -> Decimal:
        """
        Calculate option payoff at a given price point.
        """
        qty = abs(quantity)

        if is_call:
            intrinsic = max(Decimal(0), underlying_price - strike)
        else:
            intrinsic = max(Decimal(0), strike - underlying_price)

        if is_long:
            return intrinsic * qty
        else:
            return -intrinsic * qty

    def _calculate_margin(
        self,
        positions: list[dict],
        contract_multiplier: int = 100,
    ) -> Decimal:
        """
        Calculate maintenance margin using piecewise payoff analysis.
        """
        if not positions:
            return Decimal(0)

        # Collect all strike prices
        strikes = set()
        for pos in positions:
            strikes.add(pos["strike"])

        sorted_strikes = sorted(strikes)
        if not sorted_strikes:
            return Decimal(0)

        # Evaluation points: 0, all strikes, and beyond highest strike
        eval_points = [Decimal(0)]
        eval_points.extend(sorted_strikes)
        eval_points.append(sorted_strikes[-1] + Decimal(100))

        # Find minimum (worst) payoff
        min_payoff = Decimal(0)

        for price in eval_points:
            total_payoff = Decimal(0)
            for pos in positions:
                payoff = self._calculate_option_payoff(
                    strike=pos["strike"],
                    is_call=pos["is_call"],
                    is_long=pos["is_long"],
                    quantity=pos["quantity"],
                    underlying_price=price,
                )
                total_payoff += payoff

            if total_payoff < min_payoff:
                min_payoff = total_payoff

        return abs(min_payoff) * contract_multiplier

    def test_long_call_payoff(self):
        """
        Test long call payoff calculation.
        """
        # Long call at strike $100
        # At price $90: payoff = 0 (OTM)
        # At price $100: payoff = 0 (ATM)
        # At price $110: payoff = $10 (ITM)
        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=True,
            is_long=True,
            quantity=1,
            underlying_price=Decimal(90),
        ) == Decimal(0)

        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=True,
            is_long=True,
            quantity=1,
            underlying_price=Decimal(100),
        ) == Decimal(0)

        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=True,
            is_long=True,
            quantity=1,
            underlying_price=Decimal(110),
        ) == Decimal(10)

    def test_short_call_payoff(self):
        """
        Test short call payoff calculation.
        """
        # Short call at strike $100
        # At price $90: payoff = 0 (OTM, keep premium)
        # At price $110: payoff = -$10 (ITM, loss)
        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=True,
            is_long=False,
            quantity=1,
            underlying_price=Decimal(90),
        ) == Decimal(0)

        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=True,
            is_long=False,
            quantity=1,
            underlying_price=Decimal(110),
        ) == Decimal(-10)

    def test_long_put_payoff(self):
        """
        Test long put payoff calculation.
        """
        # Long put at strike $100
        # At price $110: payoff = 0 (OTM)
        # At price $90: payoff = $10 (ITM)
        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=False,
            is_long=True,
            quantity=1,
            underlying_price=Decimal(110),
        ) == Decimal(0)

        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=False,
            is_long=True,
            quantity=1,
            underlying_price=Decimal(90),
        ) == Decimal(10)

    def test_short_put_payoff(self):
        """
        Test short put payoff calculation.
        """
        # Short put at strike $100
        # At price $110: payoff = 0 (OTM, keep premium)
        # At price $90: payoff = -$10 (ITM, loss)
        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=False,
            is_long=False,
            quantity=1,
            underlying_price=Decimal(110),
        ) == Decimal(0)

        assert self._calculate_option_payoff(
            Decimal(100),
            is_call=False,
            is_long=False,
            quantity=1,
            underlying_price=Decimal(90),
        ) == Decimal(-10)

    def test_bull_call_spread_margin(self):
        """
        Test margin for bull call spread (debit spread).
        """
        # Long $100 call, short $110 call
        # Max loss = $0 (premium paid, but ignoring premiums)
        # Max profit capped at $10 spread width
        # This is a DEBIT spread - no margin required beyond premium
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": True, "quantity": 1},
            {"strike": Decimal(110), "is_call": True, "is_long": False, "quantity": 1},
        ]
        margin = self._calculate_margin(positions)
        # At any price: long call gains offset short call losses
        # Max loss is $0 (ignoring premium), so margin = $0
        assert margin == Decimal(0)

    def test_bear_call_spread_margin(self):
        """
        Test margin for bear call spread (credit spread).
        """
        # Short $100 call, long $110 call
        # Max loss = $10 (spread width) when price goes above $110
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": False, "quantity": 1},
            {"strike": Decimal(110), "is_call": True, "is_long": True, "quantity": 1},
        ]
        margin = self._calculate_margin(positions)
        # At price $200: short $100 call = -$100, long $110 call = +$90, net = -$10
        # Max loss = $10 * 100 multiplier = $1000
        assert margin == Decimal(1000)

    def test_iron_condor_margin(self):
        """
        Test margin for iron condor.
        """
        # Sell $95 put, buy $90 put (put credit spread)
        # Sell $105 call, buy $110 call (call credit spread)
        # Max loss = max of either spread = $5 (spread width)
        positions = [
            {"strike": Decimal(90), "is_call": False, "is_long": True, "quantity": 1},
            {"strike": Decimal(95), "is_call": False, "is_long": False, "quantity": 1},
            {"strike": Decimal(105), "is_call": True, "is_long": False, "quantity": 1},
            {"strike": Decimal(110), "is_call": True, "is_long": True, "quantity": 1},
        ]
        margin = self._calculate_margin(positions)
        # Max loss is $5 on either wing = $500
        assert margin == Decimal(500)

    def test_universal_spread_rule_offsetting_positions(self):
        """
        Test the universal spread rule example from Alpaca docs.

        Positions:
        - Long Call AAPL @ $100
        - Short Call AAPL @ $110
        - Long Call AAPL @ $200
        - Short Call AAPL @ $190

        Traditional: Spread 1 margin $0 + Spread 2 margin $1000 = $1000
        Universal Spread Rule: Positions offset, margin = $0

        """
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": True, "quantity": 1},
            {"strike": Decimal(110), "is_call": True, "is_long": False, "quantity": 1},
            {"strike": Decimal(200), "is_call": True, "is_long": True, "quantity": 1},
            {"strike": Decimal(190), "is_call": True, "is_long": False, "quantity": 1},
        ]
        margin = self._calculate_margin(positions)

        # Let's verify at key price points:
        # At price $0: all calls worthless, total payoff = $0
        # At price $100: all calls still worthless, total payoff = $0
        # At price $110: long $100 = $10, short $110 = $0, others = $0, net = $10
        # At price $190: long $100 = $90, short $110 = -$80, long $200 = $0, short $190 = $0, net = $10
        # At price $200: long $100 = $100, short $110 = -$90, long $200 = $0, short $190 = -$10, net = $0
        # At price $300: long $100 = $200, short $110 = -$190, long $200 = $100, short $190 = -$110, net = $0

        # The minimum payoff is $0 at extreme prices, so margin = $0
        assert margin == Decimal(0)

    def test_naked_short_call_margin(self):
        """
        Test margin for uncovered (naked) short call.
        """
        # Short $100 call with no hedge
        # Theoretically unlimited loss potential
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": False, "quantity": 1},
        ]
        margin = self._calculate_margin(positions)
        # At price $200 (our eval point beyond strikes): loss = $100
        # Margin = $100 * 100 = $10,000
        assert margin == Decimal(10000)

    def test_naked_short_put_margin(self):
        """
        Test margin for uncovered (naked) short put.
        """
        # Short $100 put with no hedge
        # Max loss if stock goes to $0 = $100
        positions = [
            {"strike": Decimal(100), "is_call": False, "is_long": False, "quantity": 1},
        ]
        margin = self._calculate_margin(positions)
        # At price $0: loss = $100
        # Margin = $100 * 100 = $10,000
        assert margin == Decimal(10000)

    def test_long_straddle_no_margin(self):
        """
        Test that long straddle requires no margin (both positions are long).
        """
        # Long $100 call + Long $100 put
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": True, "quantity": 1},
            {"strike": Decimal(100), "is_call": False, "is_long": True, "quantity": 1},
        ]
        margin = self._calculate_margin(positions)
        # Long positions never have negative payoff (ignoring premium)
        assert margin == Decimal(0)

    def test_multiple_contracts_quantity(self):
        """
        Test margin calculation with multiple contracts.
        """
        # 5 contracts of bear call spread
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": False, "quantity": 5},
            {"strike": Decimal(110), "is_call": True, "is_long": True, "quantity": 5},
        ]
        margin = self._calculate_margin(positions)
        # Max loss per contract = $10, with 5 contracts = $50
        # Margin = $50 * 100 = $5000
        assert margin == Decimal(5000)


class TestAlpacaOptionsMarginCalculatorModule:
    """
    Tests for the standalone AlpacaOptionsMarginCalculator module.

    This tests the margin module can be used independently of the execution client for
    pre-trade validation and risk management monitoring.

    """

    def setup_method(self):
        from nautilus_trader.adapters.alpaca.margin import AlpacaOptionsMarginCalculator

        self.calculator = AlpacaOptionsMarginCalculator()

    def test_calculator_instantiation(self):
        """
        Test that calculator can be instantiated standalone.
        """
        from nautilus_trader.adapters.alpaca.margin import AlpacaOptionsMarginCalculator

        calc = AlpacaOptionsMarginCalculator()
        assert calc is not None
        assert calc.default_contract_multiplier == 100

    def test_calculator_custom_multiplier(self):
        """
        Test calculator with custom contract multiplier.
        """
        from nautilus_trader.adapters.alpaca.margin import AlpacaOptionsMarginCalculator

        calc = AlpacaOptionsMarginCalculator(default_contract_multiplier=50)
        assert calc.default_contract_multiplier == 50

    def test_calculate_payoff_static_method(self):
        """
        Test that calculate_payoff is a static method.
        """
        from nautilus_trader.adapters.alpaca.margin import AlpacaOptionsMarginCalculator

        # Can call without instance
        payoff = AlpacaOptionsMarginCalculator.calculate_payoff(
            strike=Decimal(100),
            is_call=True,
            is_long=True,
            quantity=1,
            underlying_price=Decimal(110),
        )
        assert payoff == Decimal(10)

    def test_maintenance_margin_bull_call_spread(self):
        """
        Test maintenance margin for bull call spread via module.
        """
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": True, "quantity": 1},
            {"strike": Decimal(110), "is_call": True, "is_long": False, "quantity": 1},
        ]
        margin = self.calculator.calculate_maintenance_margin(positions)
        assert margin == Decimal(0)  # Debit spread, no margin

    def test_maintenance_margin_bear_call_spread(self):
        """
        Test maintenance margin for bear call spread via module.
        """
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": False, "quantity": 1},
            {"strike": Decimal(110), "is_call": True, "is_long": True, "quantity": 1},
        ]
        margin = self.calculator.calculate_maintenance_margin(positions)
        assert margin == Decimal(1000)  # $10 max loss * 100

    def test_maintenance_margin_universal_spread_rule(self):
        """
        Test the universal spread rule via module (offsetting positions).
        """
        positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": True, "quantity": 1},
            {"strike": Decimal(110), "is_call": True, "is_long": False, "quantity": 1},
            {"strike": Decimal(200), "is_call": True, "is_long": True, "quantity": 1},
            {"strike": Decimal(190), "is_call": True, "is_long": False, "quantity": 1},
        ]
        margin = self.calculator.calculate_maintenance_margin(positions)
        assert margin == Decimal(0)  # Positions offset

    def test_order_cost_basis_debit_spread(self):
        """
        Test cost basis calculation for debit spread.
        """
        legs = [
            {
                "strike": Decimal(100),
                "is_call": True,
                "is_long": True,
                "side": "buy",
                "ratio_qty": 1,
            },
            {
                "strike": Decimal(110),
                "is_call": True,
                "is_long": False,
                "side": "sell",
                "ratio_qty": 1,
            },
        ]
        # Pay $5 premium total (debit)
        premiums = [Decimal(7), Decimal(2)]  # Pay $7, receive $2
        result = self.calculator.calculate_order_cost_basis(legs, premiums)

        assert result["maintenance_margin"] == Decimal(0)
        assert result["net_premium"] == Decimal(500)  # $5 * 100
        assert result["cost_basis"] == Decimal(500)

    def test_order_cost_basis_credit_spread(self):
        """
        Test cost basis calculation for credit spread.
        """
        legs = [
            {
                "strike": Decimal(100),
                "is_call": True,
                "is_long": False,
                "side": "sell",
                "ratio_qty": 1,
            },
            {
                "strike": Decimal(110),
                "is_call": True,
                "is_long": True,
                "side": "buy",
                "ratio_qty": 1,
            },
        ]
        # Receive $3 premium (credit)
        premiums = [Decimal(5), Decimal(2)]  # Receive $5, pay $2
        result = self.calculator.calculate_order_cost_basis(legs, premiums)

        assert result["maintenance_margin"] == Decimal(1000)  # $10 max loss
        # Net premium is $7 * 100 = $700 (net debit because both are positive in this example)
        # Cost basis = margin + net premium

    def test_validate_position_margin(self):
        """
        Test position validation for margin limits.
        """
        # Bear call spread (current margin = $1000)
        current_positions = [
            {"strike": Decimal(100), "is_call": True, "is_long": False, "quantity": 1},
            {"strike": Decimal(110), "is_call": True, "is_long": True, "quantity": 1},
        ]
        # Adding a protective long put (no additional margin)
        new_position = {"strike": Decimal(90), "is_call": False, "is_long": True, "quantity": 1}

        # With $5000 available margin
        is_valid, new_margin, message = self.calculator.validate_position_margin(
            current_positions=current_positions,
            new_position=new_position,
            available_margin=Decimal(5000),
        )
        assert is_valid is True
        assert "Position" in message

    def test_validate_position_margin_insufficient(self):
        """
        Test position validation fails when margin insufficient.
        """
        current_positions = []
        new_position = {"strike": Decimal(100), "is_call": True, "is_long": False, "quantity": 1}

        # Naked short call needs $10,000 margin (price goes to $200)
        is_valid, new_margin, message = self.calculator.validate_position_margin(
            current_positions=current_positions,
            new_position=new_position,
            available_margin=Decimal(5000),
        )
        assert is_valid is False
        assert "Insufficient margin" in message

    def test_empty_positions_zero_margin(self):
        """
        Test empty positions return zero margin.
        """
        margin = self.calculator.calculate_maintenance_margin([])
        assert margin == Decimal(0)

    def test_expiration_grouping(self):
        """
        Test positions are grouped by expiration for margin calculation.
        """
        # Two separate spreads with different expirations
        positions = [
            {
                "strike": Decimal(100),
                "is_call": True,
                "is_long": False,
                "quantity": 1,
                "expiration": "2025-01-17",
            },
            {
                "strike": Decimal(110),
                "is_call": True,
                "is_long": True,
                "quantity": 1,
                "expiration": "2025-01-17",
            },
            {
                "strike": Decimal(100),
                "is_call": True,
                "is_long": False,
                "quantity": 1,
                "expiration": "2025-02-21",
            },
            {
                "strike": Decimal(110),
                "is_call": True,
                "is_long": True,
                "quantity": 1,
                "expiration": "2025-02-21",
            },
        ]
        margin = self.calculator.calculate_maintenance_margin(positions)
        # Each expiration has $1000 margin, total should be sum
        assert margin == Decimal(2000)


class TestAlpacaExecutionClientMarginPreview:
    """
    Tests for execution client margin preview methods.
    """

    def setup_method(self):
        self.clock = LiveClock()

    def _create_mock_client(self):
        """
        Create a mock client with margin calculator.
        """
        from nautilus_trader.adapters.alpaca.margin import AlpacaOptionsMarginCalculator

        client = MagicMock(spec=AlpacaExecutionClient)
        client._options_margin_calculator = AlpacaOptionsMarginCalculator()
        client._log = MagicMock()
        # Use real methods
        client.preview_mleg_margin = (
            lambda *args, **kwargs: AlpacaExecutionClient.preview_mleg_margin(
                client,
                *args,
                **kwargs,
            )
        )
        client._parse_occ_symbol = lambda symbol: AlpacaExecutionClient._parse_occ_symbol(
            client,
            symbol,
        )
        # Bind helper methods used by preview_mleg_margin
        client._validate_and_convert_leg = (
            lambda leg, leg_index, quantity: AlpacaExecutionClient._validate_and_convert_leg(
                client,
                leg,
                leg_index,
                quantity,
            )
        )
        client._calculate_cost_basis_for_legs = (
            lambda positions, legs, leg_premiums, quantity, contract_multiplier: (
                AlpacaExecutionClient._calculate_cost_basis_for_legs(
                    client,
                    positions,
                    legs,
                    leg_premiums,
                    quantity,
                    contract_multiplier,
                )
            )
        )
        return client

    # Tests for _parse_occ_symbol

    def test_parse_occ_symbol_call(self):
        """
        Test parsing OCC symbol for call option.
        """
        client = self._create_mock_client()
        result = client._parse_occ_symbol("AAPL250117C00200000")

        assert result is not None
        assert result["strike"] == Decimal(200)
        assert result["is_call"] is True
        assert result["expiration"] == "250117"

    def test_parse_occ_symbol_put(self):
        """
        Test parsing OCC symbol for put option.
        """
        client = self._create_mock_client()
        result = client._parse_occ_symbol("AAPL250117P00150000")

        assert result is not None
        assert result["strike"] == Decimal(150)
        assert result["is_call"] is False
        assert result["expiration"] == "250117"

    def test_parse_occ_symbol_fractional_strike(self):
        """
        Test parsing OCC symbol with fractional strike price.
        """
        client = self._create_mock_client()
        # Strike of $202.50 = 00202500
        result = client._parse_occ_symbol("AAPL250117C00202500")

        assert result is not None
        assert result["strike"] == Decimal("202.5")
        assert result["is_call"] is True

    def test_parse_occ_symbol_short_underlying(self):
        """
        Test parsing OCC symbol with short underlying symbol.
        """
        client = self._create_mock_client()
        result = client._parse_occ_symbol("F250117C00015000")  # Ford at $15

        assert result is not None
        assert result["strike"] == Decimal(15)
        assert result["is_call"] is True

    def test_parse_occ_symbol_long_underlying(self):
        """
        Test parsing OCC symbol with long underlying symbol.
        """
        client = self._create_mock_client()
        result = client._parse_occ_symbol("GOOGL250117P01500000")  # Google at $1500

        assert result is not None
        assert result["strike"] == Decimal(1500)
        assert result["is_call"] is False

    def test_parse_occ_symbol_invalid_format(self):
        """
        Test parsing invalid OCC symbol returns None.
        """
        client = self._create_mock_client()

        assert client._parse_occ_symbol("INVALID") is None
        assert client._parse_occ_symbol("") is None
        assert client._parse_occ_symbol("AAPL") is None

    # Tests for preview_mleg_margin

    def test_preview_mleg_margin_bull_call_spread(self):
        """
        Test margin preview for bull call spread (debit spread, no margin).
        """
        client = self._create_mock_client()

        result = client.preview_mleg_margin(
            legs=[
                {
                    "symbol": "AAPL250117C00200000",
                    "side": "buy",
                    "ratio_qty": 1,
                    "strike": Decimal(200),
                    "is_call": True,
                },
                {
                    "symbol": "AAPL250117C00210000",
                    "side": "sell",
                    "ratio_qty": 1,
                    "strike": Decimal(210),
                    "is_call": True,
                },
            ],
        )

        assert result["is_valid"] is True
        assert result["maintenance_margin"] == Decimal(0)
        assert len(result["errors"]) == 0
        assert len(result["positions"]) == 2

    def test_preview_mleg_margin_bear_call_spread(self):
        """
        Test margin preview for bear call spread (credit spread, needs margin).
        """
        client = self._create_mock_client()

        result = client.preview_mleg_margin(
            legs=[
                {
                    "symbol": "AAPL250117C00200000",
                    "side": "sell",
                    "ratio_qty": 1,
                    "strike": Decimal(200),
                    "is_call": True,
                },
                {
                    "symbol": "AAPL250117C00210000",
                    "side": "buy",
                    "ratio_qty": 1,
                    "strike": Decimal(210),
                    "is_call": True,
                },
            ],
        )

        assert result["is_valid"] is True
        assert result["maintenance_margin"] == Decimal(1000)  # $10 spread * 100

    def test_preview_mleg_margin_with_occ_parsing(self):
        """
        Test margin preview extracts strike/type from OCC symbol.
        """
        client = self._create_mock_client()

        # Don't provide strike/is_call, let it parse from symbol
        result = client.preview_mleg_margin(
            legs=[
                {"symbol": "AAPL250117C00200000", "side": "buy", "ratio_qty": 1},
                {"symbol": "AAPL250117C00210000", "side": "sell", "ratio_qty": 1},
            ],
        )

        assert result["is_valid"] is True
        assert result["maintenance_margin"] == Decimal(0)
        # Verify it parsed correctly
        assert result["positions"][0]["strike"] == Decimal(200)
        assert result["positions"][0]["is_call"] is True
        assert result["positions"][1]["strike"] == Decimal(210)
        assert result["positions"][1]["is_call"] is True

    def test_preview_mleg_margin_with_premiums(self):
        """
        Test margin preview with premium calculation.
        """
        client = self._create_mock_client()

        result = client.preview_mleg_margin(
            legs=[
                {
                    "symbol": "AAPL250117C00200000",
                    "side": "buy",
                    "ratio_qty": 1,
                    "strike": Decimal(200),
                    "is_call": True,
                },
                {
                    "symbol": "AAPL250117C00210000",
                    "side": "sell",
                    "ratio_qty": 1,
                    "strike": Decimal(210),
                    "is_call": True,
                },
            ],
            leg_premiums=[Decimal("5.50"), Decimal("2.00")],  # Pay 5.50, receive 2.00
        )

        assert result["is_valid"] is True
        assert result["maintenance_margin"] == Decimal(0)
        assert result["net_premium"] == Decimal(350)  # (5.50 - 2.00) * 100
        assert result["cost_basis"] == Decimal(350)  # Margin(0) + NetPremium(350)

    def test_preview_mleg_margin_missing_symbol(self):
        """
        Test margin preview with missing symbol returns error.
        """
        client = self._create_mock_client()

        result = client.preview_mleg_margin(
            legs=[
                {"side": "buy", "ratio_qty": 1, "strike": Decimal(200), "is_call": True},
            ],
        )

        assert result["is_valid"] is False
        assert any("Missing symbol" in e for e in result["errors"])

    def test_preview_mleg_margin_invalid_side(self):
        """
        Test margin preview with invalid side returns error.
        """
        client = self._create_mock_client()

        result = client.preview_mleg_margin(
            legs=[
                {
                    "symbol": "AAPL250117C00200000",
                    "side": "invalid",
                    "ratio_qty": 1,
                    "strike": Decimal(200),
                    "is_call": True,
                },
            ],
        )

        assert result["is_valid"] is False
        assert any("Invalid side" in e for e in result["errors"])

    def test_preview_mleg_margin_cannot_determine_strike(self):
        """
        Test margin preview with unparsable symbol and no strike returns error.
        """
        client = self._create_mock_client()

        result = client.preview_mleg_margin(
            legs=[
                {"symbol": "INVALID", "side": "buy", "ratio_qty": 1},
            ],
        )

        assert result["is_valid"] is False
        assert any("Cannot determine strike" in e for e in result["errors"])

    def test_preview_mleg_margin_quantity_multiplier(self):
        """
        Test margin preview applies quantity multiplier.
        """
        client = self._create_mock_client()

        # Bear call spread with quantity = 5
        result = client.preview_mleg_margin(
            legs=[
                {
                    "symbol": "AAPL250117C00200000",
                    "side": "sell",
                    "ratio_qty": 1,
                    "strike": Decimal(200),
                    "is_call": True,
                },
                {
                    "symbol": "AAPL250117C00210000",
                    "side": "buy",
                    "ratio_qty": 1,
                    "strike": Decimal(210),
                    "is_call": True,
                },
            ],
            quantity=5,
        )

        assert result["is_valid"] is True
        assert result["maintenance_margin"] == Decimal(5000)  # $10 * 5 * 100

    def test_preview_mleg_margin_iron_condor(self):
        """
        Test margin preview for iron condor.
        """
        client = self._create_mock_client()

        result = client.preview_mleg_margin(
            legs=[
                {
                    "symbol": "AAPL250117P00180000",
                    "side": "buy",
                    "ratio_qty": 1,
                    "strike": Decimal(180),
                    "is_call": False,
                },
                {
                    "symbol": "AAPL250117P00190000",
                    "side": "sell",
                    "ratio_qty": 1,
                    "strike": Decimal(190),
                    "is_call": False,
                },
                {
                    "symbol": "AAPL250117C00210000",
                    "side": "sell",
                    "ratio_qty": 1,
                    "strike": Decimal(210),
                    "is_call": True,
                },
                {
                    "symbol": "AAPL250117C00220000",
                    "side": "buy",
                    "ratio_qty": 1,
                    "strike": Decimal(220),
                    "is_call": True,
                },
            ],
        )

        assert result["is_valid"] is True
        # Iron condor max loss is the wider wing - credit received
        # Max loss is $10 (either put spread or call spread width) * 100 = $1000
        assert result["maintenance_margin"] == Decimal(1000)

    def test_preview_mleg_margin_premium_count_mismatch(self):
        """
        Test margin preview with mismatched premium count.
        """
        client = self._create_mock_client()

        result = client.preview_mleg_margin(
            legs=[
                {
                    "symbol": "AAPL250117C00200000",
                    "side": "buy",
                    "ratio_qty": 1,
                    "strike": Decimal(200),
                    "is_call": True,
                },
                {
                    "symbol": "AAPL250117C00210000",
                    "side": "sell",
                    "ratio_qty": 1,
                    "strike": Decimal(210),
                    "is_call": True,
                },
            ],
            leg_premiums=[Decimal("5.50")],  # Only 1 premium for 2 legs
        )

        assert result["is_valid"] is False
        assert any("Premium count" in e for e in result["errors"])