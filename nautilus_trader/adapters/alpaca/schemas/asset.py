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
Alpaca asset schema definitions.
"""

from __future__ import annotations

from typing import Any

import msgspec


class AlpacaAsset(msgspec.Struct, frozen=True, kw_only=True):
    """
    Alpaca asset information from the /v2/assets endpoint.

    See: https://docs.alpaca.markets/reference/get-v2-assets

    """

    id: str
    class_: str = msgspec.field(name="class")
    exchange: str
    symbol: str
    name: str
    status: str
    tradable: bool
    marginable: bool
    shortable: bool
    easy_to_borrow: bool
    fractionable: bool
    maintenance_margin_requirement: float | None = None
    min_order_size: str | None = None
    min_trade_increment: str | None = None
    price_increment: str | None = None
    attributes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary representation.
        """
        return {
            "id": self.id,
            "class": self.class_,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "name": self.name,
            "status": self.status,
            "tradable": self.tradable,
            "marginable": self.marginable,
            "shortable": self.shortable,
            "easy_to_borrow": self.easy_to_borrow,
            "fractionable": self.fractionable,
            "maintenance_margin_requirement": self.maintenance_margin_requirement,
            "min_order_size": self.min_order_size,
            "min_trade_increment": self.min_trade_increment,
            "price_increment": self.price_increment,
            "attributes": self.attributes,
        }