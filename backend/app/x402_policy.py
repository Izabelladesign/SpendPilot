
from decimal import Decimal

from app.vendor_verifier import verify_vendor


def create_x402_policy(
    vendor_name: str,
    approved_amount_usd: Decimal,
):
    """
    Return an SDK policy that accepts only payment
    requirements matching an approved SpendPilot payment.

    Base Sepolia USDC uses 6 decimal places.
    """

    if (
        not approved_amount_usd.is_finite()
        or approved_amount_usd <= 0
    ):
        raise ValueError("Approved amount must be positive")

    amount_units = approved_amount_usd * Decimal(1_000_000)

    if amount_units != amount_units.to_integral_value():
        raise ValueError("Amount cannot be represented in USDC units")

    expected_units = int(amount_units)

    def policy(version, requirements):
        if version != 2:
            return []

        allowed = []

        for requirement in requirements:
            if getattr(requirement, "scheme", None) != "exact":
                continue

            recipient = getattr(requirement, "pay_to", None)
            network = getattr(requirement, "network", None)
            asset = getattr(requirement, "asset", None)
            amount = getattr(requirement, "amount", None)

            if not all(
                isinstance(value, str)
                for value in (recipient, network, asset, amount)
            ):
                continue

            if not verify_vendor(
                vendor_name,
                recipient,
                network,
                asset,
            ):
                continue

            if not amount.isascii() or not amount.isdecimal():
                continue

            if str(int(amount)) != amount:
                continue

            if int(amount) != expected_units:
                continue

            allowed.append(requirement)

        return allowed

    return policy
