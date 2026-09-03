"""Web3 connection and network identification.

The network name is derived from the chain ID reported by the node, never from
configuration. That is deliberate: it makes it impossible for the CLI to print
"Sepolia" while actually talking to a local node, which would be the single most
misleading thing this project could do.
"""

from __future__ import annotations

from dataclasses import dataclass

from web3 import Web3
from web3.exceptions import Web3Exception

from ..errors import ChainConnectionError

_TIMEOUT = 60


@dataclass(frozen=True)
class NetworkInfo:
    chain_id: int
    name: str
    #: True only for well-known public networks with a block explorer.
    is_public: bool
    explorer_base: str | None = None

    def tx_url(self, tx_hash: str) -> str | None:
        return f"{self.explorer_base}/tx/{tx_hash}" if self.explorer_base else None

    def address_url(self, address: str) -> str | None:
        return f"{self.explorer_base}/address/{address}" if self.explorer_base else None


#: Chain IDs we can name with confidence.
_KNOWN: dict[int, NetworkInfo] = {
    1: NetworkInfo(1, "ethereum-mainnet", True, "https://etherscan.io"),
    11155111: NetworkInfo(11155111, "sepolia", True, "https://sepolia.etherscan.io"),
    17000: NetworkInfo(17000, "holesky", True, "https://holesky.etherscan.io"),
    560048: NetworkInfo(560048, "hoodi", True, "https://hoodi.etherscan.io"),
    8453: NetworkInfo(8453, "base-mainnet", True, "https://basescan.org"),
    84532: NetworkInfo(84532, "base-sepolia", True, "https://sepolia.basescan.org"),
    # Anvil and Hardhat defaults. Named as local so output cannot be mistaken
    # for a public testnet.
    31337: NetworkInfo(31337, "local-evm (anvil/hardhat)", False),
    1337: NetworkInfo(1337, "local-evm", False),
}


def describe_network(chain_id: int) -> NetworkInfo:
    known = _KNOWN.get(chain_id)
    if known:
        return known
    return NetworkInfo(chain_id, f"unknown-chain-{chain_id}", False)


def connect(rpc_url: str) -> tuple[Web3, NetworkInfo]:
    """Connect to an Ethereum JSON-RPC endpoint and identify the network."""
    try:
        web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": _TIMEOUT}))
        chain_id = web3.eth.chain_id
    except (Web3Exception, OSError, ValueError) as exc:
        raise ChainConnectionError(
            f"Could not reach the RPC endpoint at {rpc_url}\n{type(exc).__name__}: {exc}",
            hint=(
                "Check RPC_URL in .env. The keyless public Sepolia endpoint is:\n"
                "    RPC_URL=https://ethereum-sepolia-rpc.publicnode.com"
            ),
        ) from exc

    return web3, describe_network(int(chain_id))
