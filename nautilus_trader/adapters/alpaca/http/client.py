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
Alpaca HTTP client for Python.

Uses httpx for async HTTP requests with Alpaca API authentication.

"""

from __future__ import annotations

from typing import Any

import msgspec


class AlpacaHttpClient:
    """
    Alpaca HTTP client for REST API access.

    Parameters
    ----------
    api_key : str
        Alpaca API key.
    api_secret : str
        Alpaca API secret.
    paper_trading : bool, default True
        If True, use paper trading endpoints. If False, use live trading.
    timeout_secs : int, optional
        Request timeout in seconds.

    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper_trading: bool = True,
        timeout_secs: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._paper_trading = paper_trading
        self._timeout_secs = timeout_secs or 30

        # Set base URLs based on environment
        if paper_trading:
            self._trading_base_url = "https://paper-api.alpaca.markets"
        else:
            self._trading_base_url = "https://api.alpaca.markets"
        self._data_base_url = "https://data.alpaca.markets"

        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        self._client: Any = None
        self._decoder = msgspec.json.Decoder()
        self._encoder = msgspec.json.Encoder()

    @property
    def api_key(self) -> str:
        """
        Return the API key.
        """
        return self._api_key

    @property
    def trading_base_url(self) -> str:
        """
        Return the trading API base URL.
        """
        return self._trading_base_url

    @property
    def data_base_url(self) -> str:
        """
        Return the market data API base URL.
        """
        return self._data_base_url

    @property
    def is_paper_trading(self) -> bool:
        """
        Return whether this client is for paper trading.
        """
        return self._paper_trading

    async def _get_client(self) -> Any:
        """
        Get or create the httpx AsyncClient.
        """
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                timeout=self._timeout_secs,
                headers=self._headers,
            )
        return self._client

    async def close(self) -> None:
        """
        Close the HTTP client.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        use_data_api: bool = False,
    ) -> bytes:
        """
        Perform a GET request.

        Parameters
        ----------
        path : str
            The API path (e.g., '/v2/assets').
        params : dict, optional
            Query parameters.
        use_data_api : bool, default False
            If True, use the data API base URL instead of trading API.

        Returns
        -------
        bytes
            The raw response body.

        """
        client = await self._get_client()
        base_url = self._data_base_url if use_data_api else self._trading_base_url
        url = f"{base_url}{path}"

        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.content

    async def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """
        Perform a POST request.

        Parameters
        ----------
        path : str
            The API path.
        data : dict, optional
            Request body data.
        params : dict, optional
            Query parameters.

        Returns
        -------
        bytes
            The raw response body.

        """
        client = await self._get_client()
        url = f"{self._trading_base_url}{path}"

        body = None
        if data is not None:
            body = self._encoder.encode(data)

        response = await client.post(url, content=body, params=params)
        response.raise_for_status()
        return response.content

    async def delete(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """
        Perform a DELETE request.

        Parameters
        ----------
        path : str
            The API path.
        params : dict, optional
            Query parameters.

        Returns
        -------
        bytes
            The raw response body.

        """
        client = await self._get_client()
        url = f"{self._trading_base_url}{path}"

        response = await client.delete(url, params=params)
        response.raise_for_status()
        return response.content

    async def patch(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """
        Perform a PATCH request.

        Parameters
        ----------
        path : str
            The API path.
        data : dict, optional
            Request body data.
        params : dict, optional
            Query parameters.

        Returns
        -------
        bytes
            The raw response body.

        """
        client = await self._get_client()
        url = f"{self._trading_base_url}{path}"

        body = None
        if data is not None:
            body = self._encoder.encode(data)

        response = await client.patch(url, content=body, params=params)
        response.raise_for_status()
        return response.content