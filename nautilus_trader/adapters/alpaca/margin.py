# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2025 Andrew Crum. All rights reserved.
#  Licensed under the MIT License. You may obtain a copy of the License at
#  https://opensource.org/licenses/MIT
# -------------------------------------------------------------------------------------------------
"""
Alpaca options margin calculation using the Universal Spread Rule.

This module provides margin calculations for options positions and multi-leg
orders following Alpaca's Universal Spread Rule methodology.

The Universal Spread Rule calculates maintenance margin by:
1. Modeling each option position as a piecewise linear payoff function
2. Evaluating the portfolio payoff at all strike prices (inflection points)
3. Finding the theoretical maximum loss across all evaluation points
4. Using that maximum loss as the maintenance margin requirement

This approach correctly handles complex spreads and offsetting positions that
traditional per-leg margin calculations would over-estimate.

Usage:
    from nautilus_trader.adapters.alpaca.margin import AlpacaOptionsMarginCalculator

    calculator = AlpacaOptionsMarginCalculator()

    # For existing positions
    margin = calculator.calculate_maintenance_margin(positions)

    # For multi-leg order cost basis
    cost = calculator.calculate_order_cost_basis(legs, leg_premiums)

"""

from decimal import Decimal
from typing import Any


class AlpacaOptionsMarginCalculator:
    """
    Calculator for Alpaca options margin using the Universal Spread Rule.

    The Universal Spread Rule evaluates option positions using piecewise linear
    payoff functions to find the theoretical maximum loss, which becomes the
    maintenance margin requirement.

    This calculator can be used for:
    - Pre-trade margin validation in the execution client
    - Real-time risk monitoring of option positions
    - Multi-leg order cost basis calculation

    Parameters
    ----------
    default_contract_multiplier : int, default 100
        The default contract multiplier for options (100 shares per contract).

    """

    def __init__(self, default_contract_multiplier: int = 100) -> None:
        self.default_contract_multiplier = default_contract_multiplier

    @staticmethod
    def calculate_payoff(
        strike: Decimal,
        is_call: bool,
        is_long: bool,
        quantity: int,
        underlying_price: Decimal,
    ) -> Decimal:
        """
        Calculate the payoff of an option position at a given underlying price.

        Uses piecewise linear payoff functions:
        - Long Call:  max(0, P - strike)
        - Short Call: -max(0, P - strike)
        - Long Put:   max(0, strike - P)
        - Short Put:  -max(0, strike - P)

        Parameters
        ----------
        strike : Decimal
            The option strike price.
        is_call : bool
            True for call options, False for put options.
        is_long : bool
            True for long positions, False for short positions.
        quantity : int
            Number of contracts (always positive).
        underlying_price : Decimal
            The underlying price at which to evaluate the payoff.

        Returns
        -------
        Decimal
            The payoff value (positive = profit, negative = loss).

        """
        if is_call:
            intrinsic = max(Decimal(0), underlying_price - strike)
        else:
            intrinsic = max(Decimal(0), strike - underlying_price)

        if is_long:
            return intrinsic * quantity
        else:
            return -intrinsic * quantity

    def calculate_maintenance_margin(
        self,
        positions: list[dict[str, Any]],
        contract_multiplier: int | None = None,
    ) -> Decimal:
        """
        Calculate maintenance margin for a portfolio of option positions.

        Uses the Universal Spread Rule: evaluate the portfolio payoff at all
        strike prices (inflection points) to find the theoretical maximum loss.

        Parameters
        ----------
        positions : list[dict]
            List of position dictionaries, each containing:
            - strike: Decimal - Strike price
            - is_call: bool - True for call, False for put
            - is_long: bool - True for long, False for short
            - quantity: int - Number of contracts
            - expiration: datetime (optional) - Expiration date for grouping
        contract_multiplier : int, optional
            The contract multiplier (default: 100).

        Returns
        -------
        Decimal
            The maintenance margin requirement (always non-negative).

        Examples
        --------
        >>> calculator = AlpacaOptionsMarginCalculator()
        >>> positions = [
        ...     {"strike": Decimal("100"), "is_call": True, "is_long": True, "quantity": 1},
        ...     {"strike": Decimal("110"), "is_call": True, "is_long": False, "quantity": 1},
        ... ]
        >>> margin = calculator.calculate_maintenance_margin(positions)

        """
        if not positions:
            return Decimal(0)

        multiplier = contract_multiplier or self.default_contract_multiplier

        # Group positions by expiration if available
        expiry_groups: dict[Any, list[dict]] = {}
        for pos in positions:
            expiry = pos.get("expiration", "default")
            if expiry not in expiry_groups:
                expiry_groups[expiry] = []
            expiry_groups[expiry].append(pos)

        # Calculate margin for each expiry group and sum
        total_margin = Decimal(0)
        for group_positions in expiry_groups.values():
            group_margin = self._calculate_margin_for_group(group_positions, multiplier)
            total_margin += group_margin

        return total_margin

    def _calculate_margin_for_group(
        self,
        positions: list[dict[str, Any]],
        contract_multiplier: int,
    ) -> Decimal:
        """
        Calculate margin for a group of positions with the same expiration.

        Parameters
        ----------
        positions : list[dict]
            Positions in this expiration group.
        contract_multiplier : int
            The contract multiplier.

        Returns
        -------
        Decimal
            The margin requirement for this group.

        """
        if not positions:
            return Decimal(0)

        # Collect all strike prices as evaluation points (inflection points)
        strikes: set[Decimal] = set()
        for pos in positions:
            strikes.add(pos["strike"])

        if not strikes:
            return Decimal(0)

        # Add boundary evaluation points
        max_strike = max(strikes)
        evaluation_points = sorted(strikes)

        # Add point below minimum strike (where puts have maximum value)
        evaluation_points.insert(0, Decimal(0))

        # Add point above maximum strike (where calls continue linearly)
        evaluation_points.append(max_strike + Decimal(100))

        # Evaluate portfolio payoff at each point
        min_payoff = Decimal(0)
        for price in evaluation_points:
            total_payoff = Decimal(0)
            for pos in positions:
                payoff = self.calculate_payoff(
                    strike=pos["strike"],
                    is_call=pos["is_call"],
                    is_long=pos["is_long"],
                    quantity=pos["quantity"],
                    underlying_price=price,
                )
                total_payoff += payoff

            if total_payoff < min_payoff:
                min_payoff = total_payoff

        # Margin is the absolute value of the maximum loss, multiplied by contract size
        return abs(min_payoff) * contract_multiplier

    def calculate_order_cost_basis(
        self,
        legs: list[dict[str, Any]],
        leg_premiums: list[Decimal],
        contract_multiplier: int | None = None,
    ) -> dict[str, Decimal]:
        """
        Calculate the cost basis for a multi-leg options order.

        Cost Basis = Maintenance Margin + Net Premium

        Where Net Premium is:
        - Positive for net debit (you pay to open)
        - Negative for net credit (you receive to open)

        Parameters
        ----------
        legs : list[dict]
            List of order legs, each containing:
            - strike: Decimal - Strike price
            - is_call: bool - True for call, False for put
            - side: str - "buy" or "sell"
            - ratio_qty: int - Quantity ratio for this leg
        leg_premiums : list[Decimal]
            Premium for each leg (positive values).
        contract_multiplier : int, optional
            The contract multiplier (default: 100).

        Returns
        -------
        dict
            Dictionary containing:
            - maintenance_margin: Decimal - Margin requirement
            - net_premium: Decimal - Net premium (positive=debit, negative=credit)
            - cost_basis: Decimal - Total cost basis

        """
        if not legs:
            return {
                "maintenance_margin": Decimal(0),
                "net_premium": Decimal(0),
                "cost_basis": Decimal(0),
            }

        if len(legs) != len(leg_premiums):
            raise ValueError(
                f"Number of legs ({len(legs)}) must match number of premiums ({len(leg_premiums)})",
            )

        multiplier = contract_multiplier or self.default_contract_multiplier

        # Convert legs to position format for margin calculation
        positions = []
        net_premium = Decimal(0)

        for leg, premium in zip(legs, leg_premiums, strict=True):
            is_long = leg.get("side", "").lower() == "buy"
            qty = leg.get("ratio_qty", 1)

            positions.append(
                {
                    "strike": leg["strike"],
                    "is_call": leg["is_call"],
                    "is_long": is_long,
                    "quantity": qty,
                },
            )

            # Calculate net premium
            premium_amount = premium * qty * multiplier
            if is_long:
                net_premium += premium_amount  # Buying = paying premium
            else:
                net_premium -= premium_amount  # Selling = receiving premium

        # Calculate maintenance margin using universal spread rule
        maintenance_margin = self.calculate_maintenance_margin(
            positions,
            contract_multiplier=multiplier,
        )

        # Cost basis is margin plus net premium (if debit)
        cost_basis = maintenance_margin + max(Decimal(0), net_premium)

        return {
            "maintenance_margin": maintenance_margin,
            "net_premium": net_premium,
            "cost_basis": cost_basis,
        }

    def validate_position_margin(
        self,
        current_positions: list[dict[str, Any]],
        new_position: dict[str, Any],
        available_margin: Decimal,
        contract_multiplier: int | None = None,
    ) -> tuple[bool, Decimal, str]:
        """
        Validate if adding a new position would exceed available margin.

        Parameters
        ----------
        current_positions : list[dict]
            Current option positions.
        new_position : dict
            The new position to add.
        available_margin : Decimal
            Available margin in the account.
        contract_multiplier : int, optional
            The contract multiplier.

        Returns
        -------
        tuple[bool, Decimal, str]
            - is_valid: Whether the new position is within margin limits
            - new_margin: The total margin with the new position
            - message: Description of the validation result

        """
        # Calculate current margin
        current_margin = self.calculate_maintenance_margin(
            current_positions,
            contract_multiplier=contract_multiplier,
        )

        # Calculate margin with new position
        all_positions = [*current_positions, new_position]
        new_margin = self.calculate_maintenance_margin(
            all_positions,
            contract_multiplier=contract_multiplier,
        )

        # Check if within limits
        margin_delta = new_margin - current_margin
        is_valid = new_margin <= available_margin

        if is_valid:
            if margin_delta <= 0:
                message = (
                    f"Position reduces margin requirement by ${abs(margin_delta):.2f} "
                    f"(new total: ${new_margin:.2f})"
                )
            else:
                message = (
                    f"Position increases margin by ${margin_delta:.2f} "
                    f"(new total: ${new_margin:.2f}, available: ${available_margin:.2f})"
                )
        else:
            message = (
                f"Insufficient margin: need ${new_margin:.2f}, "
                f"available ${available_margin:.2f} "
                f"(shortfall: ${new_margin - available_margin:.2f})"
            )

        return is_valid, new_margin, message