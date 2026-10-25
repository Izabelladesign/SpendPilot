import base64
import json

import pytest

from app.x402_settlement import extract_transaction_hash


def encode(data):
    return base64.urlsafe_b64encode(
        json.dumps(data).encode()
    ).decode()


def test_valid_settlement():
    tx = "0x" + "a" * 64
    response = encode({
        "success": True,
        "transaction": tx,
        "network": "eip155:84532",
    })
    assert extract_transaction_hash(response) == tx


def test_failed_settlement():
    response = encode({
        "success": False,
        "transaction": "0x" + "a" * 64,
    })
    with pytest.raises(ValueError):
        extract_transaction_hash(response)


def test_missing_transaction():
    with pytest.raises(ValueError):
        extract_transaction_hash(encode({"success": True}))


def test_invalid_response():
    with pytest.raises(ValueError):
        extract_transaction_hash("invalid")
