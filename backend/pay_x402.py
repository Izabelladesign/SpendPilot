
import asyncio
import os

from dotenv import load_dotenv
from eth_account import Account

from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact import ExactEvmScheme

load_dotenv(".env")

NETWORK = "eip155:84532"
RESOURCE_URL = os.environ["X402_RESOURCE_URL"]


async def main():
    account = Account.from_key(
        os.environ["PAYMENT_PRIVATE_KEY"]
    )

    print("Payer:", account.address)
    print("Resource:", RESOURCE_URL)

    signer = EthAccountSigner(account)

    client = x402Client()
    client.register(
        NETWORK,
        ExactEvmScheme(signer=signer),
    )

    async with x402HttpxClient(client) as http:
        response = await http.get(RESOURCE_URL)

        print("HTTP Status:", response.status_code)
        print("Response:", response.text)
        print(
            "Payment response:",
            response.headers.get("PAYMENT-RESPONSE"),
        )


if __name__ == "__main__":
    asyncio.run(main())
