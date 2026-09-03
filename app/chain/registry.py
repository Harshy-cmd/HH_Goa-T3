"""Deploy the registry, write records, and read them back.

Transactions are built, signed locally, and sent as raw transactions. The
private key never leaves the process and is never logged.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError, TimeExhausted, Web3Exception

from ..errors import (
    ChainError,
    ContractError,
    InsufficientFundsError,
    TransactionError,
)
from ..hashing import to_bytes32
from ..models import ChainReceipt, OnChainRecord
from .client import NetworkInfo, connect
from .compile import compile_registry

#: How long to wait for inclusion. Sepolia blocks are ~12s; 5 minutes covers a
#: congested testnet without hanging a demo indefinitely.
_RECEIPT_TIMEOUT = 300
#: Headroom over the node's gas estimate, for the estimate being slightly low.
_GAS_BUFFER = 1.25


@dataclass
class Registry:
    """A connected, deployed VerificationRegistry."""

    web3: Web3
    network: NetworkInfo
    address: str
    contract: object

    # -- reads --------------------------------------------------------------

    def is_registered(self, record_hash: str) -> bool:
        try:
            return bool(
                self.contract.functions.isRegistered(to_bytes32(record_hash)).call()
            )
        except Web3Exception as exc:
            raise ContractError(
                f"isRegistered() call failed: {type(exc).__name__}: {exc}",
                hint=_wrong_contract_hint(self.address),
            ) from exc

    def get_record(self, record_hash: str) -> OnChainRecord | None:
        """Read a record back. Returns None when the hash was never registered."""
        try:
            raw = self.contract.functions.getRecord(to_bytes32(record_hash)).call()
        except (ContractCustomError, ContractLogicError):
            # RecordNotFound is the expected revert for an unregistered hash --
            # which is exactly what a tampered record produces.
            return None
        except Web3Exception as exc:
            raise ContractError(
                f"getRecord() call failed: {type(exc).__name__}: {exc}",
                hint=_wrong_contract_hint(self.address),
            ) from exc

        stored_hash, block_timestamp, submitter, source, candidate_url = raw
        return OnChainRecord(
            record_hash=stored_hash.hex(),
            block_timestamp=int(block_timestamp),
            submitter=submitter,
            source=source,
            candidate_url=candidate_url,
        )

    def record_count(self) -> int:
        return int(self.contract.functions.recordCount().call())

    # -- writes -------------------------------------------------------------

    def register(
        self,
        record_hash: str,
        *,
        source: str,
        candidate_url: str,
        private_key: str,
        on_progress=None,
    ) -> ChainReceipt:
        """Commit a record hash on-chain and wait for the receipt."""
        account = Account.from_key(private_key)
        fn = self.contract.functions.registerVerification(
            to_bytes32(record_hash), source, candidate_url
        )

        try:
            gas_estimate = fn.estimate_gas({"from": account.address})
        except (ContractCustomError, ContractLogicError) as exc:
            # The contract rejects a duplicate digest, so surface that clearly
            # rather than as a raw revert.
            raise TransactionError(
                f"The contract rejected this registration: {exc}",
                hint=(
                    "This record hash may already be registered. Verify it instead:\n"
                    "    python -m app verify"
                ),
            ) from exc
        except Web3Exception as exc:
            raise TransactionError(
                f"Gas estimation failed: {type(exc).__name__}: {exc}"
            ) from exc

        tx = fn.build_transaction(
            {
                "from": account.address,
                "nonce": self.web3.eth.get_transaction_count(account.address),
                "gas": int(gas_estimate * _GAS_BUFFER),
                "chainId": self.network.chain_id,
            }
        )
        _ensure_funded(self.web3, account.address, tx)

        if on_progress:
            on_progress(f"signing transaction as {account.address}")
        signed = account.sign_transaction(tx)

        try:
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        except Web3Exception as exc:
            raise TransactionError(_explain_send_failure(exc)) from exc

        hex_hash = tx_hash.hex()
        if not hex_hash.startswith("0x"):
            hex_hash = f"0x{hex_hash}"
        if on_progress:
            on_progress(f"submitted {hex_hash}, waiting for inclusion")

        try:
            receipt = self.web3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=_RECEIPT_TIMEOUT
            )
        except TimeExhausted as exc:
            raise TransactionError(
                f"Transaction {hex_hash} was not included within {_RECEIPT_TIMEOUT}s.",
                hint=(
                    "It may still confirm later. Check the explorer, then re-run "
                    "`python -m app verify` once it lands."
                ),
            ) from exc

        if receipt["status"] != 1:
            raise TransactionError(
                f"Transaction {hex_hash} was mined but reverted (status 0).",
                hint=self.network.tx_url(hex_hash) or None,
            )

        return ChainReceipt(
            network=self.network.name,
            chain_id=self.network.chain_id,
            contract_address=self.address,
            transaction_hash=hex_hash,
            block_number=int(receipt["blockNumber"]),
            gas_used=int(receipt["gasUsed"]),
            submitter=account.address,
            explorer_tx_url=self.network.tx_url(hex_hash),
            explorer_address_url=self.network.address_url(self.address),
        )


# --- construction ------------------------------------------------------------


def load_registry(rpc_url: str, contract_address: str) -> Registry:
    """Attach to an already-deployed registry."""
    web3, network = connect(rpc_url)
    compiled = compile_registry()

    if not Web3.is_address(contract_address):
        raise ContractError(
            f"CONTRACT_ADDRESS is not a valid Ethereum address: {contract_address!r}",
            hint="Copy the address printed by `python -m app deploy`.",
        )
    checksummed = Web3.to_checksum_address(contract_address)

    code = web3.eth.get_code(checksummed)
    if not code or code == b"":
        raise ContractError(
            f"No contract code at {checksummed} on {network.name} "
            f"(chain id {network.chain_id}).",
            hint=(
                "The address may belong to a different network, or the local chain "
                "may have been restarted. Redeploy:\n    python -m app deploy"
            ),
        )

    return Registry(
        web3=web3,
        network=network,
        address=checksummed,
        contract=web3.eth.contract(address=checksummed, abi=compiled.abi),
    )


def deploy_registry(rpc_url: str, private_key: str, *, on_progress=None) -> tuple[Registry, ChainReceipt]:
    """Compile and deploy a fresh registry."""
    web3, network = connect(rpc_url)
    compiled = compile_registry(on_progress=on_progress)
    account = Account.from_key(private_key)

    factory = web3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
    constructor = factory.constructor()

    try:
        gas_estimate = constructor.estimate_gas({"from": account.address})
    except Web3Exception as exc:
        raise TransactionError(
            f"Gas estimation for deployment failed: {type(exc).__name__}: {exc}"
        ) from exc

    tx = constructor.build_transaction(
        {
            "from": account.address,
            "nonce": web3.eth.get_transaction_count(account.address),
            "gas": int(gas_estimate * _GAS_BUFFER),
            "chainId": network.chain_id,
        }
    )
    _ensure_funded(web3, account.address, tx)

    if on_progress:
        on_progress(f"deploying from {account.address}")
    signed = account.sign_transaction(tx)

    try:
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    except Web3Exception as exc:
        raise TransactionError(_explain_send_failure(exc)) from exc

    hex_hash = tx_hash.hex()
    if not hex_hash.startswith("0x"):
        hex_hash = f"0x{hex_hash}"
    if on_progress:
        on_progress(f"submitted {hex_hash}, waiting for inclusion")

    try:
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=_RECEIPT_TIMEOUT)
    except TimeExhausted as exc:
        raise TransactionError(
            f"Deployment {hex_hash} was not included within {_RECEIPT_TIMEOUT}s."
        ) from exc

    if receipt["status"] != 1:
        raise TransactionError(f"Deployment {hex_hash} reverted.")

    address = Web3.to_checksum_address(receipt["contractAddress"])
    registry = Registry(
        web3=web3,
        network=network,
        address=address,
        contract=web3.eth.contract(address=address, abi=compiled.abi),
    )
    chain_receipt = ChainReceipt(
        network=network.name,
        chain_id=network.chain_id,
        contract_address=address,
        transaction_hash=hex_hash,
        block_number=int(receipt["blockNumber"]),
        gas_used=int(receipt["gasUsed"]),
        submitter=account.address,
        explorer_tx_url=network.tx_url(hex_hash),
        explorer_address_url=network.address_url(address),
    )
    return registry, chain_receipt


# --- helpers -----------------------------------------------------------------


def _ensure_funded(web3: Web3, address: str, tx: dict) -> None:
    """Fail with a useful message before broadcasting an unaffordable tx."""
    balance = web3.eth.get_balance(address)
    gas = int(tx.get("gas", 0))
    # Post-1559 nodes return maxFeePerGas; legacy chains return gasPrice.
    price = int(tx.get("maxFeePerGas") or tx.get("gasPrice") or 0)
    needed = gas * price

    if balance == 0:
        raise InsufficientFundsError(
            f"Account {address} has a zero balance and cannot pay for gas.",
            hint=(
                "Fund this THROWAWAY testnet account from a Sepolia faucet:\n"
                "    https://cloud.google.com/application/web3/faucet/ethereum/sepolia\n"
                "    https://www.alchemy.com/faucets/ethereum-sepolia"
            ),
        )
    if needed and balance < needed:
        raise InsufficientFundsError(
            f"Account {address} holds {Web3.from_wei(balance, 'ether'):.6f} ETH but this "
            f"transaction needs up to {Web3.from_wei(needed, 'ether'):.6f} ETH in gas.",
            hint="Top the account up from a Sepolia faucet and retry.",
        )


def _explain_send_failure(exc: Exception) -> str:
    text = str(exc).lower()
    if "insufficient funds" in text:
        return (
            "The node rejected the transaction for insufficient funds. "
            "Fund the account from a Sepolia faucet and retry."
        )
    if "nonce" in text:
        return (
            f"The node rejected the transaction over a nonce conflict: {exc}\n"
            "Another transaction from this account may still be pending; wait and retry."
        )
    if "underpriced" in text or "fee" in text:
        return (
            f"The node rejected the transaction as underpriced: {exc}\n"
            "Retry; gas prices on public testnets move quickly."
        )
    return f"Sending the transaction failed: {type(exc).__name__}: {exc}"


def _wrong_contract_hint(address: str) -> str:
    return (
        f"{address} may not be a VerificationRegistry, or may live on a different "
        "network than RPC_URL points to. Redeploy with `python -m app deploy`."
    )
