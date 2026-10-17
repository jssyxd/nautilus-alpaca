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
Alpaca option contract schema definitions.
"""

from __future__ import annotations

from typing import Any

import msgspec


class AlpacaOptionContract(msgspec.Struct, frozen=True, kw_only=True):
    """
    Alpaca option contract information from the /v2/options/contracts endpoint.

    See: https://docs.alpaca.markets/docs/options-trading

    """

    id: str
    symbol: str
    name: str
    status: str
    tradable: bool
    expiration_date: str
    root_symbol: str
    underlying_symbol: str
    underlying_asset_id: str
    type: str  # "call" or "put"
    style: str  # "american" or "european"
    strike_price: str
    size: str  # Contract multiplier (typically "100")
    open_interest: str | None = None
    open_interest_date: str | None = None
    close_price: str | None = None
    close_price_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary representation.
        """
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "status": self.status,
            "tradable": self.tradable,
            "expiration_date": self.expiration_date,
            "root_symbol": self.root_symbol,
            "underlying_symbol": self.underlying_symbol,
            "underlying_asset_id": self.underlying_asset_id,
            "type": self.type,
            "style": self.style,
            "strike_price": self.strike_price,
            "size": self.size,
            "open_interest": self.open_interest,
            "open_interest_date": self.open_interest_date,
            "close_price": self.close_price,
            "close_price_date": self.close_price_date,
        }


class AlpacaOptionContractsResponse(msgspec.Struct, frozen=True, kw_only=True):
    """
    Alpaca paginated response for option contracts.
    """

    option_contracts: list[AlpacaOptionContract]
    next_page_token: str | None = None