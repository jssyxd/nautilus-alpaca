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
Alpaca instrument provider implementation.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import msgspec
import pandas as pd

from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE
from nautilus_trader.adapters.alpaca.common.enums import AlpacaAssetClass
from nautilus_trader.adapters.alpaca.schemas.asset import AlpacaAsset
from nautilus_trader.adapters.alpaca.schemas.option import AlpacaOptionContract
from nautilus_trader.adapters.alpaca.schemas.option import AlpacaOptionContractsResponse
try:
    from nautilus_trader.common.providers import InstrumentProvider
except ImportError:
    from nautilus_trader.live import InstrumentProvider

try:
    from nautilus_trader.config import InstrumentProviderConfig
except ImportError:
    try:
        from nautilus_trader.live import InstrumentProviderConfig
    except ImportError:
        InstrumentProviderConfig = object
from nautilus_trader.core.correctness import PyCondition
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Currency
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity


if TYPE_CHECKING:
    from nautilus_trader.adapters.alpaca.http.client import AlpacaHttpClient
    from nautilus_trader.common.component import LiveClock


class AlpacaInstrumentProvider(InstrumentProvider):
    """
    Provides instruments from Alpaca Markets.

    Supports:
    - US equities (stocks and ETFs)
    - Cryptocurrencies (BTC/USD, ETH/USD, etc.)
    - Options (equity options)

    Parameters
    ----------
    client : AlpacaHttpClient
        The Alpaca HTTP client.
    clock : LiveClock
        The clock for the provider.
    config : InstrumentProviderConfig, optional
        The configuration for the provider.
    asset_classes : frozenset[AlpacaAssetClass], optional
        The asset classes to load instruments for. Defaults to US_EQUITY only.

    """

    def __init__(
        self,
        client: AlpacaHttpClient,
        clock: LiveClock,
        config: InstrumentProviderConfig | None = None,
        asset_classes: frozenset[AlpacaAssetClass] | None = None,
    ) -> None:
        super().__init__(config=config or InstrumentProviderConfig())
        PyCondition.not_none(client, "client")
        PyCondition.not_none(clock, "clock")

        self._client = client
        self._clock = clock

        # Read asset_classes from config or parameter, defaulting to US_EQUITY
        config_asset_classes = getattr(config, "asset_classes", None) if config else None
        self._asset_classes = (
            asset_classes or config_asset_classes or frozenset({AlpacaAssetClass.US_EQUITY})
        )

        # Read option_underlying_symbols from config
        self._option_underlying_symbols = (
            getattr(config, "option_underlying_symbols", None) if config else None
        )

        # Decoders for different asset types
        self._asset_decoder = msgspec.json.Decoder(list[AlpacaAsset])
        self._option_decoder = msgspec.json.Decoder(AlpacaOptionContractsResponse)
        self._log_warnings = config.log_warnings if config else True

    async def load_all_async(self, filters: dict | None = None) -> None:
        """
        Load all tradable instruments from Alpaca.

        Parameters
        ----------
        filters : dict, optional
            Optional filters to apply when loading instruments.

        """
        filters_str = "..." if not filters else f" with filters {filters}..."
        self._log.info(f"Loading all Alpaca instruments{filters_str}")

        for asset_class in self._asset_classes:
            await self._load_asset_class(asset_class, filters)

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        """
        Load instruments by their IDs.

        Parameters
        ----------
        instrument_ids : list[InstrumentId]
            The instrument IDs to load.
        filters : dict, optional
            Optional filters to apply.

        """
        if not instrument_ids:
            self._log.info("No instrument IDs given for loading.")
            return

        # Validate all IDs are for Alpaca
        for instrument_id in instrument_ids:
            PyCondition.equal(
                instrument_id.venue,
                ALPACA_VENUE,
                "instrument_id.venue",
                "ALPACA",
            )

        # Load individual instruments
        for instrument_id in instrument_ids:
            await self.load_async(instrument_id, filters)

    async def load_async(
        self,
        instrument_id: InstrumentId,
        filters: dict | None = None,
    ) -> None:
        """
        Load a single instrument by ID.

        Parameters
        ----------
        instrument_id : InstrumentId
            The instrument ID to load.
        filters : dict, optional
            Optional filters to apply.

        """
        PyCondition.not_none(instrument_id, "instrument_id")
        PyCondition.equal(
            instrument_id.venue,
            ALPACA_VENUE,
            "instrument_id.venue",
            "ALPACA",
        )

        filters_str = "..." if not filters else f" with filters {filters}..."
        self._log.debug(f"Loading instrument {instrument_id}{filters_str}")

        symbol = instrument_id.symbol.value

        try:
            response = await self._client.get(f"/v2/assets/{symbol}")
            asset = msgspec.json.decode(response, type=AlpacaAsset)
            self._parse_equity_instrument(asset)
        except Exception as e:
            self._log.error(f"Failed to load instrument {instrument_id}: {e}")

    async def _load_asset_class(
        self,
        asset_class: AlpacaAssetClass,
        filters: dict | None,
    ) -> None:
        """
        Load instruments for a specific asset class.
        """
        self._log.info(f"Loading {asset_class.value} instruments...")

        if asset_class == AlpacaAssetClass.OPTION:
            # Options use a different endpoint
            await self._load_options(filters)
            return

        params = {
            "status": "active",
            "asset_class": asset_class.value,
        }

        try:
            response = await self._client.get("/v2/assets", params=params)
            assets = self._asset_decoder.decode(response)

            loaded_count = 0
            for asset in assets:
                if not asset.tradable:
                    continue

                # Apply filters if provided
                if filters and not self._passes_filters(asset, filters):
                    continue

                if asset_class == AlpacaAssetClass.US_EQUITY:
                    self._parse_equity_instrument(asset)
                    loaded_count += 1
                elif asset_class == AlpacaAssetClass.CRYPTO:
                    self._parse_crypto_instrument(asset)
                    loaded_count += 1

            self._log.info(f"Loaded {loaded_count} {asset_class.value} instruments")

        except Exception as e:
            self._log.error(f"Failed to load {asset_class.value} instruments: {e}")

    def _passes_filters(self, asset: AlpacaAsset, filters: dict) -> bool:
        """
        Check if an asset passes the given filters.
        """
        # Filter by exchange
        if "exchanges" in filters:
            exchanges = filters["exchanges"]
            if isinstance(exchanges, str):
                exchanges = [exchanges]
            if asset.exchange not in exchanges:
                return False

        # Filter by symbol prefix/pattern
        if "symbol_prefix" in filters and not asset.symbol.startswith(
            filters["symbol_prefix"],
        ):
            return False

        # Filter by tradable status (default is True from API params)
        if "tradable" in filters and asset.tradable != filters["tradable"]:
            return False

        # Filter by shortable
        if "shortable" in filters and asset.shortable != filters["shortable"]:
            return False

        # Filter by fractionable
        return not ("fractionable" in filters and asset.fractionable != filters["fractionable"])

    def _parse_equity_instrument(self, asset: AlpacaAsset) -> None:
        """
        Parse an Alpaca asset into a Nautilus Equity instrument.
        """
        ts_init = self._clock.timestamp_ns()

        try:
            raw_symbol = Symbol(asset.symbol)
            instrument_id = InstrumentId(symbol=raw_symbol, venue=ALPACA_VENUE)

            # Determine price precision and increment
            # Alpaca stocks trade in penny increments ($0.01)
            # Some high-priced stocks may trade in $0.0001 increments
            if asset.price_increment:
                price_increment_str = asset.price_increment
                price_increment_dec = Decimal(price_increment_str)
                exponent = price_increment_dec.as_tuple().exponent
                price_precision = abs(exponent) if isinstance(exponent, int) else 0
            else:
                # Default to penny increments for US equities
                price_increment_str = "0.01"
                price_precision = 2

            price_increment = Price.from_str(price_increment_str)

            # Determine lot size
            # Most US equities trade in 1-share lots
            # Some may have fractional trading available
            if asset.min_trade_increment:
                lot_size = Quantity.from_str(asset.min_trade_increment)
            else:
                lot_size = Quantity.from_int(1)

            # Create the Equity instrument
            instrument = Equity(
                instrument_id=instrument_id,
                raw_symbol=raw_symbol,
                currency=USD,
                price_precision=price_precision,
                price_increment=price_increment,
                lot_size=lot_size,
                ts_event=ts_init,
                ts_init=ts_init,
                isin=None,  # Alpaca doesn't provide ISIN in asset endpoint
                info=asset.to_dict(),
            )

            self.add(instrument=instrument)
            self._log.debug(f"Added instrument {instrument.id}")

        except ValueError as e:
            if self._log_warnings:
                self._log.warning(f"Unable to parse instrument {asset.symbol}: {e}")

    def _parse_crypto_instrument(self, asset: AlpacaAsset) -> None:
        """
        Parse an Alpaca crypto asset into a Nautilus CurrencyPair instrument.
        """
        ts_init = self._clock.timestamp_ns()

        try:
            # Alpaca crypto symbols are like "BTC/USD" or "BTCUSD"
            symbol_str = asset.symbol
            if "/" not in symbol_str:
                # Convert BTCUSD -> BTC/USD format
                # Most crypto pairs end in USD, USDT, USDC, or BTC
                for quote in ["USDT", "USDC", "USD", "BTC"]:
                    if symbol_str.endswith(quote):
                        base = symbol_str[: -len(quote)]
                        symbol_str = f"{base}/{quote}"
                        break

            raw_symbol = Symbol(symbol_str)
            instrument_id = InstrumentId(symbol=raw_symbol, venue=ALPACA_VENUE)

            # Parse base and quote currencies
            if "/" in symbol_str:
                base_str, quote_str = symbol_str.split("/")
            else:
                # Fallback - assume USD quote
                base_str = symbol_str
                quote_str = "USD"

            base_currency = Currency.from_str(base_str)
            quote_currency = Currency.from_str(quote_str)

            # Determine price precision and increment
            if asset.price_increment:
                price_increment_str = asset.price_increment
                price_increment_dec = Decimal(price_increment_str)
                exponent = price_increment_dec.as_tuple().exponent
                price_precision = abs(exponent) if isinstance(exponent, int) else 0
            else:
                # Default for crypto
                price_increment_str = "0.01"
                price_precision = 2

            price_increment = Price.from_str(price_increment_str)

            # Determine size precision
            if asset.min_trade_increment:
                size_increment_str = asset.min_trade_increment
                size_increment_dec = Decimal(size_increment_str)
                exponent = size_increment_dec.as_tuple().exponent
                size_precision = abs(exponent) if isinstance(exponent, int) else 0
            else:
                # Default 8 decimals for crypto
                size_increment_str = "0.00000001"
                size_precision = 8

            size_increment = Quantity.from_str(size_increment_str)

            # Min quantity
            min_quantity = None
            if asset.min_order_size:
                min_quantity = Quantity.from_str(asset.min_order_size)

            # Create the CurrencyPair instrument
            instrument = CurrencyPair(
                instrument_id=instrument_id,
                raw_symbol=raw_symbol,
                base_currency=base_currency,
                quote_currency=quote_currency,
                price_precision=price_precision,
                size_precision=size_precision,
                price_increment=price_increment,
                size_increment=size_increment,
                lot_size=None,  # Crypto is fractionable
                max_quantity=None,
                min_quantity=min_quantity,
                max_notional=None,
                min_notional=None,
                max_price=None,
                min_price=None,
                margin_init=Decimal(0),
                margin_maint=Decimal(0),
                maker_fee=Decimal(0),
                taker_fee=Decimal(0),
                ts_event=ts_init,
                ts_init=ts_init,
                info=asset.to_dict(),
            )

            self.add(instrument=instrument)
            self._log.debug(f"Added crypto instrument {instrument.id}")

        except ValueError as e:
            if self._log_warnings:
                self._log.warning(f"Unable to parse crypto instrument {asset.symbol}: {e}")

    async def _load_options(self, filters: dict | None) -> None:
        """
        Load option contracts from Alpaca.
        """
        # Options require specifying underlying symbols
        # Check filters first, then config
        underlying_symbols = None
        if filters and "underlying_symbols" in filters:
            underlying_symbols = filters["underlying_symbols"]
        elif self._option_underlying_symbols:
            underlying_symbols = list(self._option_underlying_symbols)

        if not underlying_symbols:
            self._log.warning(
                "No underlying_symbols specified for options loading. "
                "Use filters={'underlying_symbols': ['AAPL', 'MSFT']} or "
                "config.option_underlying_symbols to load options.",
            )
            return

        if isinstance(underlying_symbols, str):
            underlying_symbols = [underlying_symbols]

        loaded_count = 0
        for underlying in underlying_symbols:
            try:
                loaded_count += await self._load_options_for_underlying(underlying, filters)
            except Exception as e:
                self._log.error(f"Failed to load options for {underlying}: {e}")

        self._log.info(f"Loaded {loaded_count} option instruments")

    def _apply_option_filters(self, params: dict, filters: dict | None) -> None:
        """
        Apply option filters to request parameters.
        """
        if not filters:
            return

        filter_mappings = {
            "expiration_date_gte": "expiration_date_gte",
            "expiration_date_lte": "expiration_date_lte",
            "strike_price_gte": "strike_price_gte",
            "strike_price_lte": "strike_price_lte",
            "type": "type",
        }

        for filter_key, param_key in filter_mappings.items():
            if filter_key in filters:
                params[param_key] = filters[filter_key]

    async def _load_options_for_underlying(
        self,
        underlying: str,
        filters: dict | None,
    ) -> int:
        """
        Load option contracts for a specific underlying symbol.
        """
        params = {
            "underlying_symbols": underlying,
            "status": "active",
        }

        # Apply filters
        self._apply_option_filters(params, filters)

        loaded_count = 0
        page_token = None

        while True:
            if page_token:
                params["page_token"] = page_token

            response = await self._client.get("/v2/options/contracts", params=params)
            data = self._option_decoder.decode(response)

            for contract in data.option_contracts:
                if not contract.tradable:
                    continue
                self._parse_option_instrument(contract)
                loaded_count += 1

            # Check for more pages
            if data.next_page_token:
                page_token = data.next_page_token
            else:
                break

        return loaded_count

    def _parse_option_instrument(self, contract: AlpacaOptionContract) -> None:
        """
        Parse an Alpaca option contract into a Nautilus OptionContract instrument.
        """
        ts_init = self._clock.timestamp_ns()

        try:
            raw_symbol = Symbol(contract.symbol)
            instrument_id = InstrumentId(symbol=raw_symbol, venue=ALPACA_VENUE)

            # Parse option kind
            option_kind = OptionKind.CALL if contract.type == "call" else OptionKind.PUT

            # Parse strike price (Alpaca returns as string)
            strike_price_dec = Decimal(contract.strike_price)
            # Use 2 decimal places for strike prices
            strike_precision = 2
            strike_price = Price(strike_price_dec, strike_precision)

            # Parse expiration date -> nanoseconds
            expiration_dt = datetime.strptime(
                contract.expiration_date,
                "%Y-%m-%d",
            ).replace(hour=16, minute=0, tzinfo=UTC)  # 4 PM ET close
            expiration_ns = int(expiration_dt.timestamp() * 1_000_000_000)

            # Activation is typically when the contract was listed
            # Use 90 days before expiration as estimate
            activation_dt = expiration_dt - pd.Timedelta(days=90)
            activation_ns = int(activation_dt.timestamp() * 1_000_000_000)

            # Contract multiplier (typically 100 for equity options)
            multiplier_str = contract.size if contract.size else "100"
            multiplier = Quantity.from_str(multiplier_str)

            # Price precision for options (typically $0.01)
            price_precision = 2
            price_increment = Price.from_str("0.01")

            # Create the OptionContract instrument
            instrument = OptionContract(
                instrument_id=instrument_id,
                raw_symbol=raw_symbol,
                asset_class=AssetClass.EQUITY,  # Alpaca options are on equities
                currency=USD,
                price_precision=price_precision,
                price_increment=price_increment,
                multiplier=multiplier,
                lot_size=multiplier,  # For options, lot size = multiplier
                underlying=contract.underlying_symbol,
                option_kind=option_kind,
                strike_price=strike_price,
                activation_ns=activation_ns,
                expiration_ns=expiration_ns,
                ts_event=ts_init,
                ts_init=ts_init,
                info=contract.to_dict(),
            )

            self.add(instrument=instrument)
            self._log.debug(f"Added option instrument {instrument.id}")

        except ValueError as e:
            if self._log_warnings:
                self._log.warning(f"Unable to parse option instrument {contract.symbol}: {e}")