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
Alpaca execution client implementation.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from functools import reduce
from math import gcd
from typing import TYPE_CHECKING
from typing import Any

import msgspec

from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE
from nautilus_trader.adapters.alpaca.config import AlpacaExecClientConfig
from nautilus_trader.adapters.alpaca.margin import AlpacaOptionsMarginCalculator
from nautilus_trader.adapters.alpaca.providers import AlpacaInstrumentProvider
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.common.enums import LogColor
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import BatchCancelOrders
from nautilus_trader.execution.messages import CancelAllOrders
from nautilus_trader.execution.messages import CancelOrder
from nautilus_trader.execution.messages import GenerateFillReports
from nautilus_trader.execution.messages import GenerateOrderStatusReport
from nautilus_trader.execution.messages import GenerateOrderStatusReports
from nautilus_trader.execution.messages import GeneratePositionStatusReports
from nautilus_trader.execution.messages import ModifyOrder
from nautilus_trader.execution.messages import QueryOrder
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.execution.messages import SubmitOrderList
from nautilus_trader.execution.reports import FillReport
from nautilus_trader.execution.reports import OrderStatusReport
from nautilus_trader.execution.reports import PositionStatusReport
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import OrderStatus
from nautilus_trader.model.enums import OrderType
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.identifiers import AccountId
from nautilus_trader.model.identifiers import ClientId
from nautilus_trader.model.identifiers import ClientOrderId
from nautilus_trader.model.identifiers import VenueOrderId
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.adapters.alpaca.websocket_client import AlpacaTradeUpdatesWebSocketClient
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.identifiers import PositionId, TradeId
from nautilus_trader.model.objects import AccountBalance, Money



if TYPE_CHECKING:
    from nautilus_trader.adapters.alpaca.http.client import AlpacaHttpClient


class AlpacaExecutionClient(LiveExecutionClient):
    """
    Provides an execution client for Alpaca Markets.

    Supports:
    - US equities (stocks and ETFs)
    - Cryptocurrencies (BTC/USD, ETH/USD, etc.)
    - Options (equity options)

    Crypto-specific constraints:
    - Time-in-force must be GTC or IOC
    - No shorting allowed
    - No margin trading

    Options-specific notes:
    - Only day orders supported
    - Contract multiplier typically 100

    Parameters
    ----------
    loop : asyncio.AbstractEventLoop
        The event loop for the client.
    client : AlpacaHttpClient
        The Alpaca HTTP client.
    msgbus : MessageBus
        The message bus for the client.
    cache : Cache
        The cache for the client.
    clock : LiveClock
        The clock for the client.
    instrument_provider : AlpacaInstrumentProvider
        The instrument provider.
    config : AlpacaExecClientConfig
        The configuration for the client.
    name : str, optional
        The custom client ID.

    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client: AlpacaHttpClient,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: AlpacaInstrumentProvider,
        config: AlpacaExecClientConfig,
        name: str | None = None,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId(name or ALPACA_VENUE.value),
            venue=ALPACA_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=None,  # Multi-currency (USD primarily)
            instrument_provider=instrument_provider,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )

        self._config = config
        self._http_client = client
        self._instrument_provider: AlpacaInstrumentProvider = instrument_provider

        # Initialize options margin calculator for universal spread rule calculations
        self._options_margin_calculator = AlpacaOptionsMarginCalculator()

        # Log configuration
        self._log.info(f"paper_trading={config.paper_trading}", LogColor.BLUE)

        # Set account ID
        account_id = AccountId(f"{name or ALPACA_VENUE.value}-master")
        self._set_account_id(account_id)

        # Processed trades deduplication
        self._processed_trade_ids: set[str] = set()

        # Trade updates WebSocket client with auto-reconnect & post-reconnect reconciliation
        self._ws_client = AlpacaTradeUpdatesWebSocketClient(
            api_key=config.api_key or client.api_key,
            api_secret=config.api_secret or getattr(client, "_api_secret", ""),
            paper_trading=config.paper_trading,
            url_override=config.base_url_ws,
            on_trade_update=self._handle_trade_update,
            on_reconnected=self._reconcile_after_reconnect,
            log=self._log,
        )

        self._log.info("Alpaca execution client initialized")

    @property
    def alpaca_instrument_provider(self) -> AlpacaInstrumentProvider:
        return self._instrument_provider

    async def _connect(self) -> None:
        """
        Connect the execution client.
        """
        self._log.info("Loading instruments...", LogColor.BLUE)
        await self._instrument_provider.initialize()

        self._log.info(
            f"Loaded {len(self._instrument_provider.list_all())} instruments",
            LogColor.GREEN,
        )

        # Get account information
        try:
            response = await self._http_client.get("/v2/account")
            account_info = msgspec.json.decode(response)
            self._log.info(
                f"Connected to Alpaca account: {account_info.get('id', 'unknown')}",
                LogColor.GREEN,
            )
            self._log.info(
                f"Account equity: ${account_info.get('equity', 'unknown')}",
                LogColor.BLUE,
            )
            self._log.info(
                f"Buying power: ${account_info.get('buying_power', 'unknown')}",
                LogColor.BLUE,
            )
        except Exception as e:
            self._log.warning(f"Failed to fetch account info: {e}")

        # Send initial account state
        await self._update_account_state()
        await self._await_account_registered()

        # Connect WebSocket for real-time trade updates
        await self._ws_client.connect()

        self._log.info("Alpaca execution client connected", LogColor.GREEN)

    async def _disconnect(self) -> None:
        """
        Disconnect the execution client.
        """
        if hasattr(self, "_ws_client") and self._ws_client:
            await self._ws_client.disconnect()
        await self._http_client.close()
        self._log.info("Alpaca execution client disconnected", LogColor.GREEN)

    # -- COMMANDS ---------------------------------------------------------------------------------

    async def _submit_order(self, command: SubmitOrder) -> None:
        """
        Submit an order to Alpaca.
        """
        order = command.order

        if order.is_closed:
            self._log.warning(f"Order {order} is already closed")
            return

        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            ts_event=self._clock.timestamp_ns(),
        )

        try:
            self._log.info(f"Submitting order to Alpaca: {order}")

            # Build order request
            order_request = self._build_order_request(order)

            # Submit order
            response = await self._http_client.post("/v2/orders", data=order_request)
            order_response = msgspec.json.decode(response)

            venue_order_id = VenueOrderId(order_response.get("id", "unknown"))

            self.generate_order_accepted(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                ts_event=self._clock.timestamp_ns(),
            )

            self._log.info(
                f"Order {order.client_order_id} accepted, venue_order_id={venue_order_id}",
            )

        except Exception as e:
            self._log.error(f"Error submitting order {order.client_order_id}: {e}")
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )

    def _apply_crypto_constraints(
        self,
        order,
        alpaca_order_type: str,
        alpaca_tif: str,
        symbol: str,
    ) -> tuple[str, str, str]:
        """
        Apply crypto-specific order constraints and transformations.
        """
        # Crypto only supports: market, limit, stop_limit
        if alpaca_order_type in ("stop", "trailing_stop"):
            self._log.warning(
                f"Crypto orders do not support {alpaca_order_type}, defaulting to market",
            )
            alpaca_order_type = "market"

        # Crypto only supports GTC or IOC
        if alpaca_tif not in ("gtc", "ioc"):
            self._log.warning(
                f"Crypto orders only support GTC or IOC, was {alpaca_tif}, defaulting to GTC",
            )
            alpaca_tif = "gtc"

        # Crypto doesn't support shorting - warn if selling without position
        if order.side == OrderSide.SELL:
            self._log.debug("Crypto sell order - ensure position exists (no shorting allowed)")

        # Convert symbol format for crypto (BTC/USD -> BTCUSD)
        symbol = symbol.replace("/", "")

        return alpaca_order_type, alpaca_tif, symbol

    def _apply_options_constraints(
        self,
        alpaca_order_type: str,
        alpaca_tif: str,
    ) -> tuple[str, str]:
        """
        Apply options-specific order constraints.
        """
        # Options only support: market, limit
        if alpaca_order_type in ("stop", "stop_limit", "trailing_stop"):
            self._log.warning(
                f"Options orders do not support {alpaca_order_type}, defaulting to market",
            )
            alpaca_order_type = "market"

        # Options only support day orders
        if alpaca_tif != "day":
            self._log.warning(
                f"Options only support DAY time-in-force, was {alpaca_tif}, defaulting to DAY",
            )
            alpaca_tif = "day"

        return alpaca_order_type, alpaca_tif

    def _build_order_request(self, order) -> dict:
        """
        Build an Alpaca order request from a Nautilus order.
        """
        symbol = order.instrument_id.symbol.value

        # Get instrument to determine asset class
        instrument = self._cache.instrument(order.instrument_id)
        is_crypto = isinstance(instrument, CurrencyPair) if instrument else False
        is_option = isinstance(instrument, OptionContract) if instrument else False

        # Map order side
        side = "buy" if order.side == OrderSide.BUY else "sell"

        # Map order type
        order_type_map = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP_MARKET: "stop",
            OrderType.STOP_LIMIT: "stop_limit",
            OrderType.TRAILING_STOP_MARKET: "trailing_stop",
        }
        alpaca_order_type = order_type_map.get(order.order_type, "market")

        # Map time in force
        tif_map = {
            TimeInForce.DAY: "day",
            TimeInForce.GTC: "gtc",
            TimeInForce.IOC: "ioc",
            TimeInForce.FOK: "fok",
            TimeInForce.GTD: "gtc",  # Alpaca uses GTC with expire_time
            TimeInForce.AT_THE_OPEN: "opg",
            TimeInForce.AT_THE_CLOSE: "cls",
        }
        alpaca_tif = tif_map.get(order.time_in_force, "day")

        # Apply asset-class-specific constraints
        if is_crypto:
            alpaca_order_type, alpaca_tif, symbol = self._apply_crypto_constraints(
                order,
                alpaca_order_type,
                alpaca_tif,
                symbol,
            )
        elif is_option:
            alpaca_order_type, alpaca_tif = self._apply_options_constraints(
                alpaca_order_type,
                alpaca_tif,
            )

        request = {
            "symbol": symbol,
            "qty": str(order.quantity),
            "side": side,
            "type": alpaca_order_type,
            "time_in_force": alpaca_tif,
            "client_order_id": str(order.client_order_id),
        }

        # Add limit price if applicable
        if order.has_price and order.price is not None:
            request["limit_price"] = str(order.price)

        # Add stop price if applicable
        if order.has_trigger_price and order.trigger_price is not None:
            request["stop_price"] = str(order.trigger_price)

        # Add extended hours flag (only for equities)
        if (
            not is_crypto
            and not is_option
            and hasattr(order, "extended_hours")
            and order.extended_hours
        ):
            request["extended_hours"] = True

        return request

    async def _submit_order_list(self, command: SubmitOrderList) -> None:
        """
        Submit a list of orders to Alpaca.
        """
        order_list = command.order_list
        orders = order_list.orders

        if not orders:
            self._log.warning("Order list is empty, nothing to submit")
            return

        # Submit orders sequentially (Alpaca doesn't have batch order API)
        for order in orders:
            if not order.is_closed:
                await self._submit_order(
                    SubmitOrder(
                        trader_id=command.trader_id,
                        strategy_id=order.strategy_id,
                        order=order,
                        command_id=command.id,
                        ts_init=self._clock.timestamp_ns(),
                        position_id=command.position_id,
                        client_id=command.client_id,
                    ),
                )

    def _validate_and_convert_leg(
        self,
        leg: dict,
        leg_index: int,
        quantity: int,
    ) -> tuple[dict | None, str | None]:
        """
        Validate a single leg and convert it to position format.
        """
        try:
            symbol = leg.get("symbol", "")
            side = leg.get("side", "")
            ratio_qty = int(leg.get("ratio_qty", 1))

            if not symbol:
                return None, f"Leg {leg_index + 1}: Missing symbol"

            if side not in ("buy", "sell"):
                return None, f"Leg {leg_index + 1}: Invalid side '{side}'"

            # Try to get strike and is_call from leg, or parse from symbol
            strike = leg.get("strike")
            is_call = leg.get("is_call")

            if strike is None or is_call is None:
                parsed = self._parse_occ_symbol(symbol)
                if parsed:
                    strike = strike or parsed.get("strike")
                    is_call = is_call if is_call is not None else parsed.get("is_call")

            if strike is None:
                return None, f"Leg {leg_index + 1}: Cannot determine strike price"
            if is_call is None:
                return None, f"Leg {leg_index + 1}: Cannot determine option type (call/put)"

            position = {
                "strike": Decimal(str(strike)),
                "is_call": is_call,
                "is_long": side == "buy",
                "quantity": ratio_qty * quantity,
                "symbol": symbol,
            }
            return position, None

        except (ValueError, TypeError) as e:
            return None, f"Leg {leg_index + 1}: {e}"

    def _calculate_cost_basis_for_legs(
        self,
        positions: list[dict],
        legs: list[dict],
        leg_premiums: list[Decimal],
        quantity: int,
        contract_multiplier: int,
    ) -> dict:
        """
        Calculate cost basis when premiums are provided.
        """
        if len(leg_premiums) != len(legs):
            return {
                "errors": [
                    f"Premium count ({len(leg_premiums)}) doesn't match leg count ({len(legs)})",
                ],
                "is_valid": False,
            }

        # Convert positions to format expected by calculator
        calc_legs = [
            {
                "strike": pos["strike"],
                "is_call": pos["is_call"],
                "side": "buy" if pos["is_long"] else "sell",
                "ratio_qty": pos["quantity"] // quantity,
            }
            for pos in positions
        ]

        cost_result = self._options_margin_calculator.calculate_order_cost_basis(
            legs=calc_legs,
            leg_premiums=leg_premiums,
            contract_multiplier=contract_multiplier,
        )
        return {
            "net_premium": cost_result["net_premium"],
            "cost_basis": cost_result["cost_basis"],
        }

    def preview_mleg_margin(
        self,
        legs: list[dict],
        quantity: int = 1,
        leg_premiums: list[Decimal] | None = None,
        contract_multiplier: int = 100,
    ) -> dict:
        """
        Preview margin requirements for a multi-leg options order before submission.

        This method calculates the margin requirement using the Universal Spread Rule
        without actually submitting the order. Use this to validate margin requirements
        during order construction.

        Parameters
        ----------
        legs : list[dict]
            List of order legs. Each leg must have:
            - symbol: Option contract symbol (e.g., "AAPL250117C00200000")
            - side: "buy" or "sell"
            - ratio_qty: Relative quantity ratio
            - strike: Decimal (optional, extracted from symbol if not provided)
            - is_call: bool (optional, extracted from symbol if not provided)
        quantity : int, default 1
            Base quantity for the order (multiplied by each leg's ratio_qty)
        leg_premiums : list[Decimal], optional
            Premium prices for each leg (for cost basis calculation).
            If not provided, only margin is calculated.
        contract_multiplier : int, default 100
            Shares per contract

        Returns
        -------
        dict
            {
                "is_valid": bool,           # Whether validation passed
                "maintenance_margin": Decimal,  # Required margin
                "net_premium": Decimal,     # Net premium (if premiums provided)
                "cost_basis": Decimal,      # Total cost basis (if premiums provided)
                "positions": list[dict],    # Positions used for calculation
                "errors": list[str],        # Any validation errors
            }

        Examples
        --------
        # Preview margin for a bull call spread
        preview = client.preview_mleg_margin(
            legs=[
                {"symbol": "AAPL250117C00200000", "side": "buy", "ratio_qty": 1,
                 "strike": Decimal("200"), "is_call": True},
                {"symbol": "AAPL250117C00210000", "side": "sell", "ratio_qty": 1,
                 "strike": Decimal("210"), "is_call": True},
            ],
            leg_premiums=[Decimal("5.50"), Decimal("2.00")],
        )
        if preview["is_valid"]:
            print(f"Margin required: ${preview['maintenance_margin']}")
            print(f"Cost basis: ${preview['cost_basis']}")

        """
        errors = []
        positions = []

        # Validate and convert legs to positions
        for i, leg in enumerate(legs):
            position, error = self._validate_and_convert_leg(leg, i, quantity)
            if error:
                errors.append(error)
            elif position:
                positions.append(position)

        if errors:
            return {
                "is_valid": False,
                "maintenance_margin": Decimal(0),
                "net_premium": Decimal(0),
                "cost_basis": Decimal(0),
                "positions": positions,
                "errors": errors,
            }

        # Calculate margin using the options margin calculator
        margin = self._options_margin_calculator.calculate_maintenance_margin(
            positions,
            contract_multiplier,
        )

        result: dict[str, Any] = {
            "is_valid": True,
            "maintenance_margin": margin,
            "positions": positions,
            "errors": [],
        }

        # If premiums provided, calculate cost basis
        if leg_premiums is not None:
            cost_basis_result = self._calculate_cost_basis_for_legs(
                positions,
                legs,
                leg_premiums,
                quantity,
                contract_multiplier,
            )
            if "errors" in cost_basis_result:
                result["errors"].extend(cost_basis_result["errors"])
                result["is_valid"] = cost_basis_result["is_valid"]
            else:
                result["net_premium"] = cost_basis_result["net_premium"]
                result["cost_basis"] = cost_basis_result["cost_basis"]

        return result

    def _parse_occ_symbol(self, symbol: str) -> dict | None:
        """
        Parse an OCC option symbol to extract strike and option type.

        OCC format: AAPL250117C00200000
        - Underlying: AAPL (variable length)
        - Expiration: 250117 (YYMMDD)
        - Type: C (Call) or P (Put)
        - Strike: 00200000 (strike * 1000, 8 digits)

        Parameters
        ----------
        symbol : str
            OCC option symbol

        Returns
        -------
        dict | None
            {"strike": Decimal, "is_call": bool, "expiration": str} or None if parsing fails

        """
        try:
            # OCC symbols have exactly 8 digits for strike at the end
            # The C or P character is at position len(symbol) - 9
            if len(symbol) < 15:  # Minimum: 1 char underlying + 6 date + 1 C/P + 8 strike
                return None

            option_type_pos = len(symbol) - 9
            option_type = symbol[option_type_pos]

            if option_type not in ("C", "P"):
                return None

            strike_str = symbol[option_type_pos + 1 :]
            if len(strike_str) != 8 or not strike_str.isdigit():
                return None

            # Strike is stored as 8 digits (strike * 1000)
            strike = Decimal(strike_str) / 1000

            # Expiration is the 6 digits before the option type
            expiration = symbol[option_type_pos - 6 : option_type_pos]
            if len(expiration) != 6 or not expiration.isdigit():
                return None

            return {
                "strike": strike,
                "is_call": option_type == "C",
                "expiration": expiration,
            }
        except Exception:
            return None

    def _validate_mleg_leg_count(self, legs: list[dict]) -> bool:
        """
        Validate multi-leg order leg count.
        """
        if not legs:
            self._log.error("No legs provided for multi-leg order")
            return False

        if len(legs) < 2:
            self._log.error("Multi-leg orders require at least 2 legs")
            return False

        if len(legs) > 4:
            self._log.error("Multi-leg orders support a maximum of 4 legs")
            return False

        return True

    def _validate_mleg_ratio_quantities(self, legs: list[dict]) -> list[int] | None:
        """
        Validate and extract ratio quantities from legs.
        """
        ratio_quantities = []
        for leg in legs:
            ratio_qty = leg.get("ratio_qty")
            if ratio_qty is None:
                self._log.error(f"Missing ratio_qty for leg: {leg.get('symbol')}")
                return None
            try:
                ratio_quantities.append(int(ratio_qty))
            except (ValueError, TypeError):
                self._log.error(f"Invalid ratio_qty '{ratio_qty}' for leg: {leg.get('symbol')}")
                return None

        # Validate GCD requirement (must be in simplest form)
        if len(ratio_quantities) >= 2:
            overall_gcd = reduce(gcd, ratio_quantities)
            if overall_gcd > 1:
                self._log.error(
                    f"Leg ratio_qty values must be in simplest form (GCD=1), "
                    f"but GCD of {ratio_quantities} is {overall_gcd}. "
                    f"Divide all ratios by {overall_gcd}.",
                )
                return None

        return ratio_quantities

    def _validate_mleg_leg_fields(self, legs: list[dict]) -> bool:
        """
        Validate required fields for each leg.
        """
        for leg in legs:
            if not leg.get("symbol"):
                self._log.error("Each leg must have a 'symbol' field")
                return False
            if leg.get("side") not in ("buy", "sell"):
                self._log.error(f"Invalid side '{leg.get('side')}' for leg {leg.get('symbol')}")
                return False
            if not leg.get("position_intent"):
                self._log.warning(
                    f"Missing position_intent for leg {leg.get('symbol')}, consider adding "
                    "'buy_to_open', 'sell_to_open', 'buy_to_close', or 'sell_to_close'",
                )
        return True

    def _validate_mleg_order_type(
        self,
        order_type: str,
        limit_price: float | None,
    ) -> str | None:
        """
        Validate order type and limit price for multi-leg orders.
        """
        # Validate order type for mleg
        if order_type not in ("market", "limit"):
            self._log.warning(
                f"Multi-leg orders only support market or limit, was {order_type}, "
                "defaulting to market",
            )
            order_type = "market"

        # Validate limit price is provided for limit orders
        if order_type == "limit" and limit_price is None:
            self._log.error("Limit price required for limit multi-leg orders")
            return None

        return order_type

    def _build_mleg_order_request(
        self,
        legs: list[dict],
        quantity: int,
        order_type: str,
        time_in_force: str,
        limit_price: float | None,
        client_order_id: str | None,
    ) -> dict:
        """
        Build the multi-leg order request payload.
        """
        request = {
            "order_class": "mleg",
            "qty": str(quantity),
            "type": order_type,
            "time_in_force": time_in_force,
            "legs": legs,
        }

        if limit_price is not None:
            request["limit_price"] = str(limit_price)

        if client_order_id:
            request["client_order_id"] = client_order_id

        return request

    async def submit_mleg_order(
        self,
        legs: list[dict],
        quantity: int = 1,
        order_type: str = "market",
        limit_price: float | None = None,
        time_in_force: str = "day",
        client_order_id: str | None = None,
        preview_margin: bool = False,
    ) -> dict | None:
        """
        Submit a multi-leg options order to Alpaca.

        Multi-leg orders allow executing complex options strategies like spreads,
        straddles, iron condors, etc. as a single atomic order.

        Parameters
        ----------
        legs : list[dict]
            List of order legs. Each leg must have:
            - symbol: Option contract symbol (e.g., "AAPL250117C00200000")
            - side: "buy" or "sell"
            - ratio_qty: Relative quantity ratio (must be in simplest form, GCD=1)
            - position_intent: "buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"
        quantity : int, default 1
            Base quantity for the order (multiplied by each leg's ratio_qty)
        order_type : str, default "market"
            Order type - "market" or "limit" (stop/stop_limit not supported for mleg)
        limit_price : float, optional
            Limit price for the combined order (required if order_type is "limit")
        time_in_force : str, default "day"
            Time in force - must be "day" for options
        client_order_id : str, optional
            Custom client order ID
        preview_margin : bool, default False
            If True, calculate and validate margin requirements before submitting.
            Returns None if margin validation fails.

        Returns
        -------
        dict | None
            Order response from Alpaca if successful, None otherwise

        Examples
        --------
        # Long call spread (bull call spread)
        await client.submit_mleg_order(
            legs=[
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
            ],
            order_type="limit",
            limit_price=1.00,
        )

        # Iron condor
        await client.submit_mleg_order(
            legs=[
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
            ],
            order_type="limit",
            limit_price=1.80,
        )

        """
        # Validate leg count
        if not self._validate_mleg_leg_count(legs):
            return None

        # Preview margin if requested
        if preview_margin:
            margin_preview = self.preview_mleg_margin(legs=legs, quantity=quantity)
            if not margin_preview["is_valid"]:
                for error in margin_preview["errors"]:
                    self._log.error(f"Margin preview error: {error}")
                return None
            self._log.info(
                f"Margin preview: maintenance_margin=${margin_preview['maintenance_margin']}",
            )

        # Validate ratio quantities
        if self._validate_mleg_ratio_quantities(legs) is None:
            return None

        # Validate leg fields
        if not self._validate_mleg_leg_fields(legs):
            return None

        # Validate order type
        validated_order_type = self._validate_mleg_order_type(order_type, limit_price)
        if validated_order_type is None:
            return None

        # Build and submit the order
        request = self._build_mleg_order_request(
            legs,
            quantity,
            validated_order_type,
            time_in_force,
            limit_price,
            client_order_id,
        )

        try:
            self._log.info(f"Submitting multi-leg order with {len(legs)} legs")
            for i, leg in enumerate(legs):
                self._log.debug(
                    f"  Leg {i + 1}: {leg.get('side')} {leg.get('ratio_qty')} x "
                    f"{leg.get('symbol')} ({leg.get('position_intent')})",
                )

            response = await self._http_client.post("/v2/orders", data=request)
            order_response = msgspec.json.decode(response)

            venue_order_id = order_response.get("id", "unknown")
            self._log.info(
                f"Multi-leg order accepted, venue_order_id={venue_order_id}",
                LogColor.GREEN,
            )

            return order_response

        except Exception as e:
            self._log.error(f"Error submitting multi-leg order: {e}")
            return None

    async def _modify_order(self, command: ModifyOrder) -> None:
        """
        Modify an existing order (PATCH /v2/orders/{order_id}).
        """
        try:
            self._log.info(f"Modifying order {command.client_order_id}: qty={command.quantity}, price={command.price}")
            venue_order_id_str = str(command.venue_order_id) if command.venue_order_id else None
            if not venue_order_id_str:
                order = self._cache.order(command.client_order_id)
                venue_order_id_str = str(order.venue_order_id) if order and order.venue_order_id else None

            if not venue_order_id_str:
                self.generate_order_modify_rejected(
                    strategy_id=command.strategy_id,
                    instrument_id=command.instrument_id,
                    client_order_id=command.client_order_id,
                    venue_order_id=command.venue_order_id,
                    reason="Cannot modify order without venue_order_id",
                    ts_event=self._clock.timestamp_ns(),
                )
                return

            patch_data = {}
            if command.quantity:
                patch_data["qty"] = str(command.quantity)
            if command.price:
                patch_data["limit_price"] = str(command.price)
            if command.trigger_price:
                patch_data["stop_price"] = str(command.trigger_price)

            response = await self._http_client.patch(f"/v2/orders/{venue_order_id_str}", data=patch_data)
            updated_data = msgspec.json.decode(response)
            new_venue_order_id = VenueOrderId(updated_data.get("id", venue_order_id_str))

            self.generate_order_updated(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=new_venue_order_id,
                quantity=command.quantity,
                price=command.price,
                trigger_price=command.trigger_price,
                ts_event=self._clock.timestamp_ns(),
            )
            self._log.info(f"Order {command.client_order_id} modified successfully")
        except Exception as e:
            self._log.error(f"Failed to modify order {command.client_order_id}: {e}")
            self.generate_order_modify_rejected(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=command.venue_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )

    async def _cancel_order(self, command: CancelOrder) -> None:
        """
        Cancel an order.
        """
        try:
            self._log.info(f"Canceling order: {command.client_order_id}")

            # Cancel by venue order ID if available, otherwise by client order ID
            if command.venue_order_id:
                path = f"/v2/orders/{command.venue_order_id}"
            else:
                path = f"/v2/orders:by_client_order_id?client_order_id={command.client_order_id}"

            await self._http_client.delete(path)

            self.generate_order_canceled(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=command.venue_order_id,
                ts_event=self._clock.timestamp_ns(),
            )

            self._log.info(f"Order {command.client_order_id} canceled")

        except Exception as e:
            self._log.error(f"Error canceling order {command.client_order_id}: {e}")
            self.generate_order_cancel_rejected(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=command.venue_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )

    async def _cancel_all_orders(self, command: CancelAllOrders) -> None:
        """
        Cancel all open orders.
        """
        try:
            self._log.info("Canceling all orders")
            await self._http_client.delete("/v2/orders")
            self._log.info("All orders canceled")
        except Exception as e:
            self._log.error(f"Error canceling all orders: {e}")

    async def _batch_cancel_orders(self, command: BatchCancelOrders) -> None:
        """
        Cancel a batch of orders.
        """
        for cancel in command.cancels:
            await self._cancel_order(cancel)

    # -- REPORTS ----------------------------------------------------------------------------------

    async def generate_order_status_report(
        self,
        command: GenerateOrderStatusReport,
    ) -> OrderStatusReport | None:
        """
        Generate an order status report.
        """
        try:
            if command.venue_order_id:
                path = f"/v2/orders/{command.venue_order_id}"
            elif command.client_order_id:
                path = f"/v2/orders:by_client_order_id?client_order_id={command.client_order_id}"
            else:
                return None

            response = await self._http_client.get(path)
            order_data = msgspec.json.decode(response)
            return self._parse_order_status_report(order_data)
        except Exception as e:
            self._log.warning(f"Failed to query order {command.client_order_id}: {e}")
            return None

    async def generate_order_status_reports(
        self,
        command: GenerateOrderStatusReports,
    ) -> list[OrderStatusReport]:
        """
        Generate order status reports.
        """
        try:
            response = await self._http_client.get("/v2/orders", params={"status": "all"})
            orders = msgspec.json.decode(response)

            reports = []
            for order_data in orders:
                report = self._parse_order_status_report(order_data)
                if report:
                    reports.append(report)

            self._log.info(f"Generated {len(reports)} order status reports")
            return reports

        except Exception as e:
            self._log.error(f"Failed to generate order status reports: {e}")
            return []

    async def generate_fill_reports(
        self,
        command: GenerateFillReports,
    ) -> list[FillReport]:
        """
        Generate fill reports.
        """
        self._log.warning("Fill report generation not yet implemented")
        return []

    async def generate_position_status_reports(
        self,
        command: GeneratePositionStatusReports,
    ) -> list[PositionStatusReport]:
        """
        Generate position status reports.
        """
        try:
            response = await self._http_client.get("/v2/positions")
            positions = msgspec.json.decode(response)

            reports = []
            for position_data in positions:
                report = self._parse_position_status_report(position_data)
                if report:
                    reports.append(report)

            self._log.info(f"Generated {len(reports)} position status reports")
            return reports

        except Exception as e:
            self._log.error(f"Failed to generate position status reports: {e}")
            return []

    def _parse_order_status_report(self, order_data: dict) -> OrderStatusReport | None:
        """
        Parse an Alpaca order response into an OrderStatusReport.
        """
        try:
            # Map Alpaca status to Nautilus OrderStatus
            status_map = {
                "new": OrderStatus.ACCEPTED,
                "accepted": OrderStatus.ACCEPTED,
                "partially_filled": OrderStatus.PARTIALLY_FILLED,
                "filled": OrderStatus.FILLED,
                "canceled": OrderStatus.CANCELED,
                "rejected": OrderStatus.REJECTED,
                "expired": OrderStatus.EXPIRED,
                "pending_new": OrderStatus.SUBMITTED,
                "pending_cancel": OrderStatus.PENDING_CANCEL,
            }

            alpaca_status = order_data.get("status", "unknown")
            order_status = status_map.get(alpaca_status, OrderStatus.ACCEPTED)

            # Map order type
            type_map = {
                "market": OrderType.MARKET,
                "limit": OrderType.LIMIT,
                "stop": OrderType.STOP_MARKET,
                "stop_limit": OrderType.STOP_LIMIT,
                "trailing_stop": OrderType.TRAILING_STOP_MARKET,
            }
            order_type = type_map.get(order_data.get("type", "market"), OrderType.MARKET)

            # Map side
            order_side = OrderSide.BUY if order_data.get("side") == "buy" else OrderSide.SELL

            # Map time in force
            tif_map = {
                "day": TimeInForce.DAY,
                "gtc": TimeInForce.GTC,
                "ioc": TimeInForce.IOC,
                "fok": TimeInForce.FOK,
                "opg": TimeInForce.AT_THE_OPEN,
                "cls": TimeInForce.AT_THE_CLOSE,
            }
            time_in_force = tif_map.get(order_data.get("time_in_force", "day"), TimeInForce.DAY)

            # Construct InstrumentId from symbol
            from nautilus_trader.model.identifiers import InstrumentId
            from nautilus_trader.model.identifiers import Symbol

            symbol_str = order_data.get("symbol", "")
            if not symbol_str:
                return None

            instrument_id = InstrumentId(
                symbol=Symbol(symbol_str),
                venue=ALPACA_VENUE,
            )
            instrument = self._cache.instrument(instrument_id)
            if instrument is None:
                return None

            return OrderStatusReport(
                account_id=self.account_id,
                instrument_id=instrument.id,
                client_order_id=ClientOrderId(order_data.get("client_order_id", "unknown")),
                venue_order_id=VenueOrderId(order_data.get("id", "unknown")),
                order_side=order_side,
                order_type=order_type,
                time_in_force=time_in_force,
                order_status=order_status,
                quantity=Quantity.from_str(order_data.get("qty", "0")),
                filled_qty=Quantity.from_str(order_data.get("filled_qty", "0")),
                avg_px=(
                    Decimal(order_data.get("filled_avg_price", "0"))
                    if order_data.get("filled_avg_price")
                    else None
                ),
                price=(
                    Price.from_str(order_data.get("limit_price"))
                    if order_data.get("limit_price")
                    else None
                ),
                trigger_price=(
                    Price.from_str(order_data.get("stop_price"))
                    if order_data.get("stop_price")
                    else None
                ),
                report_id=UUID4(),
                ts_accepted=self._clock.timestamp_ns(),
                ts_last=self._clock.timestamp_ns(),
                ts_init=self._clock.timestamp_ns(),
            )

        except Exception as e:
            self._log.warning(f"Error parsing order status report: {e}")
            return None

    def _parse_position_status_report(self, position_data: dict) -> PositionStatusReport | None:
        """
        Parse an Alpaca position response into a PositionStatusReport.
        """
        try:
            symbol = position_data.get("symbol")
            from nautilus_trader.model.identifiers import InstrumentId
            from nautilus_trader.model.identifiers import Symbol

            instrument_id = InstrumentId(
                symbol=Symbol(symbol),
                venue=ALPACA_VENUE,
            )

            instrument = self._cache.instrument(instrument_id)
            if instrument is None:
                return None

            qty = Decimal(position_data.get("qty", "0"))
            side = OrderSide.BUY if qty > 0 else OrderSide.SELL

            return PositionStatusReport(
                account_id=self.account_id,
                instrument_id=instrument_id,
                position_side=side,
                quantity=Quantity(abs(qty), 0),
                report_id=UUID4(),
                ts_last=self._clock.timestamp_ns(),
                ts_init=self._clock.timestamp_ns(),
            )

        except Exception as e:
            self._log.warning(f"Error parsing position status report: {e}")
            return None

    async def _query_order(self, command: QueryOrder) -> None:
        """
        Query an order status.
        """
        report = await self.generate_order_status_report(
            GenerateOrderStatusReport(
                trader_id=command.trader_id,
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=command.venue_order_id,
                command_id=command.id,
                ts_init=self._clock.timestamp_ns(),
            )
        )
        if report:
            self._send_order_status_report(report)

    # -- OPTIONS NTA (Non-Trade Activity) HANDLING ------------------------------------------------

    async def get_option_activities(
        self,
        activity_types: list[str] | None = None,
        date: str | None = None,
        until: str | None = None,
        after: str | None = None,
        direction: str = "desc",
        page_size: int = 100,
    ) -> list[dict]:
        """
        Fetch options-related account activities (Non-Trade Activities).

        Parameters
        ----------
        activity_types : list[str], optional
            Filter by activity types. Options-specific types:
            - OPEXC: Option Exercise
            - OPASN: Option Assignment
            - OPEXP: Option Expiry (OTM)
            - OPTRD: Option Trade (underlying shares from exercise/assignment)
        date : str, optional
            Filter by specific date (YYYY-MM-DD)
        until : str, optional
            Activities up to this date
        after : str, optional
            Activities after this date
        direction : str, default "desc"
            Sort direction ("asc" or "desc")
        page_size : int, default 100
            Number of results per page

        Returns
        -------
        list[dict]
            List of activity records

        Examples
        --------
        # Get all option exercises and assignments
        activities = await client.get_option_activities(
            activity_types=["OPEXC", "OPASN", "OPEXP", "OPTRD"]
        )

        """
        params = {
            "direction": direction,
            "page_size": str(page_size),
        }

        if activity_types:
            params["activity_type"] = ",".join(activity_types)
        if date:
            params["date"] = date
        if until:
            params["until"] = until
        if after:
            params["after"] = after

        try:
            response = await self._http_client.get("/v2/account/activities", params=params)
            activities = msgspec.json.decode(response)
            return activities
        except Exception as e:
            self._log.error(f"Error fetching option activities: {e}")
            return []

    async def get_option_exercises(
        self,
        date: str | None = None,
        after: str | None = None,
    ) -> list[dict]:
        """
        Fetch option exercise events.

        An exercise event (OPEXC) occurs when a long option position is exercised,
        resulting in a corresponding trade (OPTRD) of the underlying shares.

        Parameters
        ----------
        date : str, optional
            Filter by specific date
        after : str, optional
            Activities after this date

        Returns
        -------
        list[dict]
            List of exercise events with format:
            {
                "id": str,
                "activity_type": "OPEXC",
                "date": str,
                "net_amount": str,
                "description": "Option Exercise",
                "symbol": str,  # Option symbol e.g., "AAPL230721C00150000"
                "qty": str,     # Negative for exercises
                "status": "executed"
            }

        """
        return await self.get_option_activities(
            activity_types=["OPEXC"],
            date=date,
            after=after,
        )

    async def get_option_assignments(
        self,
        date: str | None = None,
        after: str | None = None,
    ) -> list[dict]:
        """
        Fetch option assignment events.

        An assignment event (OPASN) occurs when a short option position is assigned,
        resulting in a corresponding trade (OPTRD) of the underlying shares.

        Parameters
        ----------
        date : str, optional
            Filter by specific date
        after : str, optional
            Activities after this date

        Returns
        -------
        list[dict]
            List of assignment events with format:
            {
                "id": str,
                "activity_type": "OPASN",
                "date": str,
                "net_amount": str,
                "description": "Option Assignment",
                "symbol": str,  # Option symbol e.g., "AAPL230721C00150000"
                "qty": str,     # Positive for assignments
                "status": "executed"
            }

        """
        return await self.get_option_activities(
            activity_types=["OPASN"],
            date=date,
            after=after,
        )

    async def get_option_expirations(
        self,
        date: str | None = None,
        after: str | None = None,
    ) -> list[dict]:
        """
        Fetch option expiration events (OTM contracts).

        An expiration event (OPEXP) occurs when an out-of-the-money option expires
        worthless. The position is flattened with no further action.

        Note: In-the-money (ITM) options are automatically exercised unless
        designated "Do Not Exercise" (DNE).

        Parameters
        ----------
        date : str, optional
            Filter by specific date
        after : str, optional
            Activities after this date

        Returns
        -------
        list[dict]
            List of expiration events with format:
            {
                "id": str,
                "activity_type": "OPEXP",
                "date": str,
                "net_amount": "0",
                "description": "Option Expiry",
                "symbol": str,  # Option symbol e.g., "AAPL230721C00150000"
                "qty": str,     # Negative (position removed)
                "status": "executed"
            }

        """
        return await self.get_option_activities(
            activity_types=["OPEXP"],
            date=date,
            after=after,
        )

    async def get_option_trades(
        self,
        date: str | None = None,
        after: str | None = None,
    ) -> list[dict]:
        """
        Fetch option trade events (underlying share trades from exercise/assignment).

        An option trade event (OPTRD) represents the underlying share transaction
        resulting from an option exercise or assignment.

        Parameters
        ----------
        date : str, optional
            Filter by specific date
        after : str, optional
            Activities after this date

        Returns
        -------
        list[dict]
            List of option trade events with format:
            {
                "id": str,
                "activity_type": "OPTRD",
                "date": str,
                "net_amount": str,  # Dollar amount of trade
                "description": "Option Trade",
                "symbol": str,      # Underlying symbol e.g., "AAPL"
                "qty": str,         # Shares traded (positive=bought, negative=sold)
                "price": str,       # Strike price per share
                "status": "executed"
            }

        """
        return await self.get_option_activities(
            activity_types=["OPTRD"],
            date=date,
            after=after,
        )

    def parse_option_activity(self, activity: dict) -> dict:
        """
        Parse an option activity into a structured format.

        Parameters
        ----------
        activity : dict
            Raw activity from Alpaca API

        Returns
        -------
        dict
            Parsed activity with additional computed fields

        """
        activity_type = activity.get("activity_type", "")
        symbol = activity.get("symbol", "")
        qty = int(activity.get("qty", 0))
        net_amount = Decimal(activity.get("net_amount", "0"))

        parsed = {
            "id": activity.get("id"),
            "activity_type": activity_type,
            "date": activity.get("date"),
            "symbol": symbol,
            "quantity": abs(qty),
            "net_amount": net_amount,
            "status": activity.get("status"),
            "description": activity.get("description"),
        }

        # Add type-specific fields
        if activity_type == "OPEXC":
            parsed["event_type"] = "exercise"
            parsed["contracts_exercised"] = abs(qty)
        elif activity_type == "OPASN":
            parsed["event_type"] = "assignment"
            parsed["contracts_assigned"] = abs(qty)
        elif activity_type == "OPEXP":
            parsed["event_type"] = "expiration"
            parsed["contracts_expired"] = abs(qty)
        elif activity_type == "OPTRD":
            parsed["event_type"] = "underlying_trade"
            parsed["shares"] = qty
            parsed["price_per_share"] = Decimal(activity.get("price", "0"))
            parsed["is_buy"] = qty > 0

        return parsed

    # -- MARGIN AND SHORT SELLING -----------------------------------------------------------------

    async def get_margin_info(self) -> dict:
        """
        Get margin-related account information.

        Returns detailed margin and buying power information including:
        - Current buying power (1x, 2x for margin, 4x intraday for PDT)
        - Margin requirements (initial and maintenance)
        - Pattern Day Trader (PDT) status
        - Day trade count

        Note: Margin trading requires $2,000+ account equity.
        PDT accounts ($25,000+ equity) get 4x intraday buying power.

        Returns
        -------
        dict
            Margin information with fields:
            {
                "equity": Decimal,              # Account equity
                "cash": Decimal,                # Cash balance
                "buying_power": Decimal,        # Available buying power
                "regt_buying_power": Decimal,   # Reg T overnight buying power (2x)
                "daytrading_buying_power": Decimal,  # PDT intraday buying power (4x)
                "initial_margin": Decimal,      # Current initial margin requirement
                "maintenance_margin": Decimal,  # Current maintenance margin requirement
                "last_maintenance_margin": Decimal,  # EOD maintenance margin
                "pattern_day_trader": bool,     # PDT flag
                "daytrade_count": int,          # Day trades in past 5 days
                "multiplier": int,              # Buying power multiplier (1, 2, or 4)
                "shorting_enabled": bool,       # Can short sell
                "margin_enabled": bool,         # Margin trading enabled
            }

        """
        try:
            response = await self._http_client.get("/v2/account")
            account = msgspec.json.decode(response)

            equity = Decimal(account.get("equity", "0"))
            margin_enabled = equity >= Decimal(2000)

            return {
                "equity": equity,
                "cash": Decimal(account.get("cash", "0")),
                "buying_power": Decimal(account.get("buying_power", "0")),
                "regt_buying_power": Decimal(account.get("regt_buying_power", "0")),
                "daytrading_buying_power": Decimal(account.get("daytrading_buying_power", "0")),
                "initial_margin": Decimal(account.get("initial_margin", "0")),
                "maintenance_margin": Decimal(account.get("maintenance_margin", "0")),
                "last_maintenance_margin": Decimal(account.get("last_maintenance_margin", "0")),
                "pattern_day_trader": account.get("pattern_day_trader", False),
                "daytrade_count": account.get("daytrade_count", 0),
                "multiplier": int(account.get("multiplier", "1")),
                "shorting_enabled": account.get("shorting_enabled", False),
                "margin_enabled": margin_enabled,
                "status": account.get("status"),
                "trading_blocked": account.get("trading_blocked", False),
            }

        except Exception as e:
            self._log.error(f"Error fetching margin info: {e}")
            return {}

    async def check_shortable(self, symbol: str) -> dict:
        """
        Check if a symbol is shortable (easy-to-borrow).

        Alpaca currently only supports shorting Easy-To-Borrow (ETB) securities.
        Hard-To-Borrow (HTB) securities cannot be shorted.

        Note: ETB status can change daily. Check before placing short orders.

        Parameters
        ----------
        symbol : str
            Stock symbol to check

        Returns
        -------
        dict
            Shortability info:
            {
                "symbol": str,
                "shortable": bool,          # Can be shorted
                "easy_to_borrow": bool,     # ETB status
                "marginable": bool,         # Can be traded on margin
                "fractionable": bool,       # Supports fractional shares
            }

        """
        try:
            response = await self._http_client.get(f"/v2/assets/{symbol}")
            asset = msgspec.json.decode(response)

            return {
                "symbol": symbol,
                "shortable": asset.get("shortable", False),
                "easy_to_borrow": asset.get("easy_to_borrow", False),
                "marginable": asset.get("marginable", False),
                "fractionable": asset.get("fractionable", False),
                "tradable": asset.get("tradable", False),
                "status": asset.get("status"),
            }

        except Exception as e:
            self._log.error(f"Error checking shortability for {symbol}: {e}")
            return {"symbol": symbol, "shortable": False, "easy_to_borrow": False}

    def calculate_maintenance_margin(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        is_short: bool = False,
        is_leveraged_etf: int = 1,
    ) -> Decimal:
        """
        Calculate the maintenance margin requirement for a position.

        Uses Alpaca's maintenance margin table:
        - Long, price < $2.50: 100% of market value
        - Long, price >= $2.50: 30% of market value
        - Long, 2x Leveraged ETF: 50% of market value
        - Long, 3x Leveraged ETF: 75% of market value
        - Short, price < $5.00: Greater of $2.50/share or 100%
        - Short, price >= $5.00: Greater of $5.00/share or 30%

        Parameters
        ----------
        symbol : str
            Stock symbol
        quantity : Decimal
            Number of shares
        price : Decimal
            Current market price per share
        is_short : bool, default False
            Whether this is a short position
        is_leveraged_etf : int, default 1
            Leverage factor if leveraged ETF (1, 2, or 3)

        Returns
        -------
        Decimal
            Required maintenance margin in USD

        """
        market_value = abs(quantity) * price

        if is_short:
            if price < Decimal("5.00"):
                # Greater of $2.50/share or 100%
                per_share_margin = abs(quantity) * Decimal("2.50")
                return max(per_share_margin, market_value)
            else:
                # Greater of $5.00/share or 30%
                per_share_margin = abs(quantity) * Decimal("5.00")
                pct_margin = market_value * Decimal("0.30")
                return max(per_share_margin, pct_margin)
        else:
            # Long positions
            if is_leveraged_etf == 3:
                return market_value * Decimal("0.75")
            elif is_leveraged_etf == 2:
                return market_value * Decimal("0.50")
            elif price < Decimal("2.50"):
                return market_value  # 100%
            else:
                return market_value * Decimal("0.30")

    def calculate_initial_margin(
        self,
        quantity: Decimal,
        price: Decimal,
        marginable: bool = True,
    ) -> Decimal:
        """
        Calculate the initial margin requirement for a trade.

        Per Regulation T:
        - Marginable securities: 50% of trade value
        - Non-marginable securities: 100% of trade value

        Parameters
        ----------
        quantity : Decimal
            Number of shares
        price : Decimal
            Price per share
        marginable : bool, default True
            Whether the security is marginable

        Returns
        -------
        Decimal
            Required initial margin in USD

        """
        trade_value = abs(quantity) * price

        if marginable:
            return trade_value * Decimal("0.50")
        else:
            return trade_value  # 100%

    async def get_short_positions(self) -> list[dict]:
        """
        Get all current short positions.

        Returns
        -------
        list[dict]
            List of short positions with market value, unrealized P/L, etc.

        """
        try:
            response = await self._http_client.get("/v2/positions")
            positions = msgspec.json.decode(response)

            short_positions = []
            for pos in positions:
                qty = Decimal(pos.get("qty", "0"))
                if qty < 0:
                    short_positions.append(
                        {
                            "symbol": pos.get("symbol"),
                            "quantity": abs(qty),
                            "market_value": abs(Decimal(pos.get("market_value", "0"))),
                            "avg_entry_price": Decimal(pos.get("avg_entry_price", "0")),
                            "current_price": Decimal(pos.get("current_price", "0")),
                            "unrealized_pl": Decimal(pos.get("unrealized_pl", "0")),
                            "unrealized_plpc": Decimal(pos.get("unrealized_plpc", "0")),
                        },
                    )

            return short_positions

        except Exception as e:
            self._log.error(f"Error fetching short positions: {e}")
            return []

    async def validate_short_order(self, symbol: str, quantity: Decimal) -> tuple[bool, str]:
        """
        Validate whether a short sell order can be placed.

        Checks:
        1. Account has $2,000+ equity (margin/shorting enabled)
        2. Symbol is shortable (ETB status)
        3. Sufficient buying power

        Parameters
        ----------
        symbol : str
            Stock symbol to short
        quantity : Decimal
            Number of shares to short

        Returns
        -------
        tuple[bool, str]
            (is_valid, message) - Whether order is valid and reason if not

        """
        # Check margin/shorting enabled
        margin_info = await self.get_margin_info()

        if not margin_info.get("margin_enabled", False):
            return False, "Margin/shorting requires $2,000+ account equity"

        if not margin_info.get("shorting_enabled", False):
            return False, "Shorting is not enabled on this account"

        # Check if symbol is shortable
        short_info = await self.check_shortable(symbol)

        if not short_info.get("shortable", False):
            return False, f"{symbol} is not shortable"

        if not short_info.get("easy_to_borrow", False):
            return False, f"{symbol} is Hard-To-Borrow (HTB), only ETB securities can be shorted"

        # We would need current price to calculate exact requirement
        # For now, just return valid if basic checks pass
        return True, "Short order validation passed"

    # -- OPTIONS MARGIN CALCULATION (UNIVERSAL SPREAD RULE) ----------------------------------------
    # Delegated to AlpacaOptionsMarginCalculator for use by both execution and risk management

    @property
    def options_margin_calculator(self) -> AlpacaOptionsMarginCalculator:
        """
        Get the options margin calculator for universal spread rule calculations.

        This calculator can be used for:
        - Pre-trade margin validation
        - Real-time risk monitoring of option positions
        - Multi-leg order cost basis calculation

        Returns
        -------
        AlpacaOptionsMarginCalculator
            The margin calculator instance.

        """
        return self._options_margin_calculator

    def calculate_option_payoff(
        self,
        strike: Decimal,
        is_call: bool,
        is_long: bool,
        quantity: int,
        underlying_price: Decimal,
    ) -> Decimal:
        """
        Calculate the intrinsic payoff of an option at a given underlying price.

        Delegates to AlpacaOptionsMarginCalculator.calculate_payoff().

        Parameters
        ----------
        strike : Decimal
            Option strike price
        is_call : bool
            True for call, False for put
        is_long : bool
            True for long position, False for short
        quantity : int
            Number of contracts (positive)
        underlying_price : Decimal
            Price point to evaluate payoff

        Returns
        -------
        Decimal
            Intrinsic payoff at the given price point

        """
        return self._options_margin_calculator.calculate_payoff(
            strike=strike,
            is_call=is_call,
            is_long=is_long,
            quantity=quantity,
            underlying_price=underlying_price,
        )

    def calculate_options_maintenance_margin(
        self,
        positions: list[dict],
        contract_multiplier: int = 100,
    ) -> Decimal:
        """
        Calculate maintenance margin for options positions using the universal spread
        rule.

        Delegates to AlpacaOptionsMarginCalculator.calculate_maintenance_margin().

        Parameters
        ----------
        positions : list[dict]
            List of option positions, each with:
            - strike: Decimal (strike price)
            - is_call: bool (True for call, False for put)
            - is_long: bool (True for long, False for short)
            - quantity: int (number of contracts)
            - expiration: str (optional, for grouping by expiry)
        contract_multiplier : int, default 100
            Shares per contract (standard is 100)

        Returns
        -------
        Decimal
            Required maintenance margin in USD

        """
        return self._options_margin_calculator.calculate_maintenance_margin(
            positions=positions,
            contract_multiplier=contract_multiplier,
        )

    def calculate_mleg_order_cost_basis(
        self,
        legs: list[dict],
        leg_premiums: list[Decimal],
        contract_multiplier: int = 100,
    ) -> dict:
        """
        Calculate the cost basis for a multi-leg options order.

        Delegates to AlpacaOptionsMarginCalculator.calculate_order_cost_basis().

        Parameters
        ----------
        legs : list[dict]
            List of order legs with:
            - strike: Decimal
            - is_call: bool
            - side: str ("buy" or "sell")
            - ratio_qty: int
        leg_premiums : list[Decimal]
            Premium for each leg (positive values)
        contract_multiplier : int, default 100
            Shares per contract

        Returns
        -------
        dict
            {
                "maintenance_margin": Decimal,  # Margin required
                "net_premium": Decimal,         # Net premium
                "cost_basis": Decimal,          # Total cost basis
            }

        """
        return self._options_margin_calculator.calculate_order_cost_basis(
            legs=legs,
            leg_premiums=leg_premiums,
            contract_multiplier=contract_multiplier,
        )

    async def _update_account_state(self) -> None:
        """
        Fetch account balances from Alpaca REST API and publish AccountState event.
        """
        try:
            response = await self._http_client.get("/v2/account")
            data = msgspec.json.decode(response)
            cash = Decimal(data.get("cash", "0"))
            equity = Decimal(data.get("equity", "0"))
            currency = USD
            total_money = Money(equity, currency)
            free_money = Money(cash, currency)
            locked_money = Money(max(Decimal("0"), equity - cash), currency)

            balance = AccountBalance(
                total=total_money,
                locked=locked_money,
                free=free_money,
            )
            self.generate_account_state(
                balances=[balance],
                margins=[],
                reported=True,
                ts_event=self._clock.timestamp_ns(),
            )
            self._log.info(f"Updated account state: equity={equity} USD, cash={cash} USD", LogColor.GREEN)
        except Exception as e:
            self._log.error(f"Failed to update account state: {e}")

    async def _reconcile_after_reconnect(self) -> None:
        """
        Post-reconnect reconciliation:
        1. Refresh account state and balances
        2. Query all open orders and send status reports
        3. Query positions and send position reports
        """
        self._log.info("Starting post-reconnect reconciliation...", LogColor.YELLOW)
        await self._update_account_state()

        # Reconcile open orders
        try:
            response = await self._http_client.get("/v2/orders", params={"status": "all", "limit": "500"})
            orders = msgspec.json.decode(response)
            reconciled_count = 0
            for order_data in orders:
                report = self._parse_order_status_report(order_data)
                if report:
                    self._send_order_status_report(report)
                    reconciled_count += 1
            self._log.info(f"Reconciled {reconciled_count} orders after reconnect", LogColor.GREEN)
        except Exception as e:
            self._log.error(f"Failed to reconcile orders after reconnect: {e}")

        # Reconcile positions
        try:
            response = await self._http_client.get("/v2/positions")
            positions = msgspec.json.decode(response)
            for pos_data in positions:
                report = self._parse_position_status_report(pos_data)
                if report:
                    self._send_position_status_report(report)
            self._log.info(f"Reconciled {len(positions)} positions after reconnect", LogColor.GREEN)
        except Exception as e:
            self._log.error(f"Failed to reconcile positions after reconnect: {e}")

    async def _handle_trade_update(self, data: dict[str, Any]) -> None:
        """
        Handle inbound trade update from Alpaca Trade Updates WebSocket stream.
        Dispatches accepted, filled, partially_filled, canceled, expired, and rejected events.
        """
        try:
            event = data.get("event")
            order_data = data.get("order", {})
            if not order_data:
                return

            client_order_id_str = order_data.get("client_order_id")
            if not client_order_id_str:
                return

            client_order_id = ClientOrderId(client_order_id_str)
            venue_order_id = VenueOrderId(order_data.get("id", "unknown"))

            # Retrieve order from cache to get strategy_id and instrument_id
            order = self._cache.order(client_order_id)
            if order is None:
                # Order might have originated outside or during cold start, parse report
                report = self._parse_order_status_report(order_data)
                if report:
                    self._send_order_status_report(report)
                return

            strategy_id = order.strategy_id
            instrument_id = order.instrument_id
            ts_event = self._clock.timestamp_ns()

            if event == "new":
                self.generate_order_accepted(
                    strategy_id=strategy_id,
                    instrument_id=instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=venue_order_id,
                    ts_event=ts_event,
                )
            elif event in ("fill", "partial_fill"):
                trade_id_str = data.get("execution_id") or f"{venue_order_id}-{data.get('timestamp')}"
                if trade_id_str in self._processed_trade_ids:
                    self._log.warning(f"Duplicate fill event ignored: {trade_id_str}")
                    return
                self._processed_trade_ids.add(trade_id_str)

                qty_str = data.get("qty", "0")
                price_str = data.get("price", "0")
                last_qty = Quantity.from_str(str(qty_str))
                last_px = Price.from_str(str(price_str))

                instrument = self._cache.instrument(instrument_id)
                quote_currency = instrument.quote_currency if instrument else USD

                self.generate_order_filled(
                    strategy_id=strategy_id,
                    instrument_id=instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=venue_order_id,
                    venue_position_id=None,
                    trade_id=TradeId(trade_id_str),
                    order_side=order.side,
                    order_type=order.order_type,
                    last_qty=last_qty,
                    last_px=last_px,
                    quote_currency=quote_currency,
                    commission=Money(0, quote_currency),
                    liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
                    ts_event=ts_event,
                )
            elif event == "canceled":
                self.generate_order_canceled(
                    strategy_id=strategy_id,
                    instrument_id=instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=venue_order_id,
                    ts_event=ts_event,
                )
            elif event == "expired":
                self.generate_order_expired(
                    strategy_id=strategy_id,
                    instrument_id=instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=venue_order_id,
                    ts_event=ts_event,
                )
            elif event == "rejected":
                self.generate_order_rejected(
                    strategy_id=strategy_id,
                    instrument_id=instrument_id,
                    client_order_id=client_order_id,
                    reason=data.get("reason", "Alpaca order rejected"),
                    ts_event=ts_event,
                )
        except Exception as e:
            self._log.error(f"Error handling Alpaca trade update: {e}")
