
from dataclasses import dataclass

BASE_SEPOLIA = "eip155:84532"

BASE_SEPOLIA_USDC = (
    "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
)


@dataclass(frozen=True)
class TrustedVendor:
    name: str
    recipient: str
    network: str
    asset: str


TRUSTED_VENDORS = {
    "spendpilot-demo": TrustedVendor(
        name="spendpilot-demo",
        recipient="0x3f9e3d67B9D4d6638aec192B13C6dB6F0710f033",
        network=BASE_SEPOLIA,
        asset=BASE_SEPOLIA_USDC,
    )
}


def verify_vendor(
    vendor_name: str,
    recipient: str,
    network: str,
    asset: str,
) -> bool:

    vendor = TRUSTED_VENDORS.get(vendor_name)

    if vendor is None:
        return False

    return (
        vendor.recipient.lower() == recipient.lower()
        and vendor.network == network
        and vendor.asset.lower() == asset.lower()
    )
