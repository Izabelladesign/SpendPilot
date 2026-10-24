
import os
import json
import base64
import httpx
from dotenv import load_dotenv

load_dotenv(".env")

url = os.environ["X402_RESOURCE_URL"]

response = httpx.get(url)

print("HTTP Status:", response.status_code)

header = response.headers.get("PAYMENT-REQUIRED")

if header:
    decoded = base64.urlsafe_b64decode(
        header + "=" * (-len(header) % 4)
    )
    data = json.loads(decoded)

    print("\nPayment challenge:")
    print(json.dumps(data, indent=2))

    payment = data["accepts"][0]

    print("\nNetwork:", payment["network"])
    print("Asset:", payment["asset"])
    print("Amount (USDC):", int(payment["amount"]) / 1_000_000)
    print("Recipient:", payment["payTo"])
else:
    print("No payment challenge returned")
