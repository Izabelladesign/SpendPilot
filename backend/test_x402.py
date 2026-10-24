
import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

RESOURCE_URL = os.getenv("X402_RESOURCE_URL")


async def main():
    if not RESOURCE_URL:
        raise ValueError("Set X402_RESOURCE_URL in .env")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(RESOURCE_URL)

        print("Status:", response.status_code)
        print("Payment required:", response.status_code == 402)

        if response.status_code == 402:
            print("\nPayment requirements:")
            print(response.headers.get("PAYMENT-REQUIRED", "Not in header"))
            print("\nResponse body:")
            print(response.text[:2000])
        else:
            print("Response:", response.text[:500])


if __name__ == "__main__":
    asyncio.run(main())
