
from decimal import Decimal

from web3 import Web3

from app.vendor_verifier import (
    BASE_SEPOLIA_USDC,
    TRUSTED_VENDORS,
)

BASE_SEPOLIA_CHAIN_ID = 84532

TRANSFER_EVENT = Web3.to_hex(
    Web3.keccak(text="Transfer(address,address,uint256)")
)


class OnchainVerificationError(Exception):
    pass


def verify_usdc_settlement(
    transaction_hash: str,
    vendor_name: str,
    expected_amount_usd: Decimal,
    rpc_url: str,
    expected_payer: str,
) -> dict:
    """
    Verify a confirmed Base Sepolia USDC transfer.

    This performs read-only blockchain queries.
    It never signs or sends a transaction.
    """

    web3 = Web3(Web3.HTTPProvider(
        rpc_url,
        request_kwargs={"timeout": 15},
    ))

    if not web3.is_connected():
        raise OnchainVerificationError(
            "Cannot connect to Base Sepolia RPC"
        )

    if web3.eth.chain_id != BASE_SEPOLIA_CHAIN_ID:
        raise OnchainVerificationError(
            "Incorrect blockchain network"
        )

    vendor = TRUSTED_VENDORS.get(vendor_name)

    if vendor is None:
        raise OnchainVerificationError(
            "Unknown vendor"
        )

    amount_units = expected_amount_usd * Decimal(1_000_000)

    if (
        not amount_units.is_finite()
        or amount_units <= 0
        or amount_units != amount_units.to_integral_value()
    ):
        raise OnchainVerificationError(
            "Invalid USDC amount"
        )

    try:
        tx_hash = Web3.to_hex(
            hexstr=transaction_hash
        )

        if len(bytes.fromhex(tx_hash[2:])) != 32:
            raise ValueError("Invalid hash length")

        receipt = web3.eth.get_transaction_receipt(tx_hash)

    except (ValueError, TypeError) as error:
        raise OnchainVerificationError(
            "Invalid transaction hash or receipt"
        ) from error

    if receipt.status != 1:
        raise OnchainVerificationError(
            "Transaction reverted"
        )

    if receipt.blockNumber is None:
        raise OnchainVerificationError(
            "Transaction not confirmed"
        )

    expected_token = Web3.to_checksum_address(
        BASE_SEPOLIA_USDC
    )

    expected_recipient = Web3.to_checksum_address(
        vendor.recipient
    )

    expected_sender = Web3.to_checksum_address(
        expected_payer
    )

    matching_transfers = []

    for log in receipt.logs:
        if Web3.to_checksum_address(log.address) != expected_token:
            continue

        if len(log.topics) != 3:
            continue

        if Web3.to_hex(log.topics[0]) != TRANSFER_EVENT:
            continue

        sender = Web3.to_checksum_address(
            "0x" + Web3.to_hex(log.topics[1])[-40:]
        )

        recipient = Web3.to_checksum_address(
            "0x" + Web3.to_hex(log.topics[2])[-40:]
        )

        amount = int.from_bytes(bytes(log.data), "big")

        if (
            sender == expected_sender
            and recipient == expected_recipient
            and amount == int(amount_units)
        ):
            matching_transfers.append(log)

    if len(matching_transfers) != 1:
        raise OnchainVerificationError(
            "Expected USDC transfer not found uniquely"
        )

    return {
        "verified": True,
        "transaction_hash": tx_hash,
        "block_number": receipt.blockNumber,
        "vendor": vendor_name,
        "recipient": expected_recipient,
        "payer": expected_sender,
        "amount_usd": str(expected_amount_usd),
        "network": "eip155:84532",
    }
