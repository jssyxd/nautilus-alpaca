import os
import sys
sys.path.insert(0, os.path.abspath('.'))
import nautilus_trader.adapters
nautilus_trader.adapters.__path__.append(os.path.abspath('nautilus_trader/adapters'))
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

import pytest

from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE
from nautilus_trader.adapters.alpaca.http.client import AlpacaHttpClient
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import Logger
from nautilus_trader.model.identifiers import Venue


@pytest.fixture(scope="session")
def live_clock():
    return LiveClock()


@pytest.fixture(scope="session")
def live_logger():
    return Logger("TEST_LOGGER")


@pytest.fixture(scope="session")
def alpaca_http_client():
    client = AlpacaHttpClient(
        api_key="SOME_ALPACA_API_KEY",
        api_secret="SOME_ALPACA_API_SECRET",
        paper_trading=True,
    )
    return client


@pytest.fixture
def venue() -> Venue:
    return ALPACA_VENUE


@pytest.fixture
def instrument():
    # Simple config tests don't need a real instrument
    return None


@pytest.fixture
def instrument_provider():
    return None


@pytest.fixture
def data_client():
    return None


@pytest.fixture
def exec_client():
    return None


@pytest.fixture
def account_state():
    return None