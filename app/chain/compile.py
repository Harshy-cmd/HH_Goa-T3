"""Compile the registry contract with solc.

solc is downloaded once by py-solc-x and cached, so no Node toolchain, Hardhat,
or Foundry install is required. The compiled ABI and bytecode are cached under
``build/`` keyed by the contract source digest, so an unchanged contract is not
recompiled on every run -- and an edited contract cannot silently reuse a stale
artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import solcx

from ..config import CONTRACT_PATH, PROJECT_ROOT
from ..errors import ContractError
from ..hashing import sha256_hex

SOLC_VERSION = "0.8.28"
CONTRACT_NAME = "VerificationRegistry"
_BUILD_DIR = PROJECT_ROOT / "build"
#: Matches the pragma in contracts/VerificationRegistry.sol.
_OPTIMIZER_RUNS = 200


@dataclass(frozen=True)
class CompiledContract:
    name: str
    abi: list[dict[str, Any]]
    bytecode: str
    source_sha256: str
    solc_version: str


def _ensure_solc(on_progress=None) -> None:
    installed = {str(v) for v in solcx.get_installed_solc_versions()}
    if SOLC_VERSION in installed:
        return
    if on_progress:
        on_progress(f"downloading solc {SOLC_VERSION} (one time)")
    try:
        solcx.install_solc(SOLC_VERSION)
    except Exception as exc:  # solcx raises a range of download/OS errors
        raise ContractError(
            f"Could not install solc {SOLC_VERSION}: {type(exc).__name__}: {exc}",
            hint="Check internet access to binaries.soliditylang.org.",
        ) from exc


def compile_registry(*, on_progress=None) -> CompiledContract:
    """Compile the contract, using the cached artifact when the source matches."""
    if not CONTRACT_PATH.exists():
        raise ContractError(f"Contract source not found: {CONTRACT_PATH}")

    source = CONTRACT_PATH.read_text(encoding="utf-8")
    source_hash = sha256_hex(source.encode("utf-8"))
    cache_path = _BUILD_DIR / f"{CONTRACT_NAME}.{source_hash[:12]}.json"

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return CompiledContract(
                name=cached["name"],
                abi=cached["abi"],
                bytecode=cached["bytecode"],
                source_sha256=cached["source_sha256"],
                solc_version=cached["solc_version"],
            )
        except (json.JSONDecodeError, KeyError):
            cache_path.unlink(missing_ok=True)  # corrupt cache: recompile

    _ensure_solc(on_progress)
    if on_progress:
        on_progress(f"compiling {CONTRACT_PATH.name} with solc {SOLC_VERSION}")

    try:
        output = solcx.compile_source(
            source,
            output_values=["abi", "bin"],
            solc_version=SOLC_VERSION,
            optimize=True,
            optimize_runs=_OPTIMIZER_RUNS,
        )
    except solcx.exceptions.SolcError as exc:
        raise ContractError(f"Solidity compilation failed:\n{exc}") from exc

    key = next((k for k in output if k.endswith(f":{CONTRACT_NAME}")), None)
    if key is None:
        raise ContractError(
            f"solc output does not contain {CONTRACT_NAME}. Found: {list(output)}"
        )

    compiled = CompiledContract(
        name=CONTRACT_NAME,
        abi=output[key]["abi"],
        bytecode=output[key]["bin"],
        source_sha256=source_hash,
        solc_version=SOLC_VERSION,
    )

    _BUILD_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "name": compiled.name,
                "abi": compiled.abi,
                "bytecode": compiled.bytecode,
                "source_sha256": compiled.source_sha256,
                "solc_version": compiled.solc_version,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return compiled
