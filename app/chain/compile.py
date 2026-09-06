"""Provide the registry contract's ABI + bytecode.

Resolution order, cheapest first:

1. **Committed artifact** ``contracts/build/VerificationRegistry.json`` -- used
   when its ``source_sha256`` matches the current contract source. This is what
   production/Render installs use: no Solidity toolchain, no download, no disk
   writes at runtime.
2. **Local solc cache** under ``build/`` (gitignored), keyed by source digest.
3. **Fresh solc compile** via ``py-solc-x`` (a dev-only dependency). Only reached
   when neither cached form is available or the source changed.

Because the committed artifact is keyed by the source digest, an edited contract
can never silently deploy a stale artifact -- a mismatch falls through to solc.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import CONTRACT_PATH, PROJECT_ROOT
from ..errors import ContractError
from ..hashing import sha256_hex

SOLC_VERSION = "0.8.28"
CONTRACT_NAME = "VerificationRegistry"
#: Gitignored solc output cache (dev machines only).
_BUILD_DIR = PROJECT_ROOT / "build"
#: Committed, precompiled artifact shipped in the repo (tracked in git).
_COMMITTED_ARTIFACT = PROJECT_ROOT / "contracts" / "build" / f"{CONTRACT_NAME}.json"
#: Matches the pragma in contracts/VerificationRegistry.sol.
_OPTIMIZER_RUNS = 200


@dataclass(frozen=True)
class CompiledContract:
    name: str
    abi: list[dict[str, Any]]
    bytecode: str
    source_sha256: str
    solc_version: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "abi": self.abi,
            "bytecode": self.bytecode,
            "source_sha256": self.source_sha256,
            "solc_version": self.solc_version,
        }


def _load_artifact_file(path: Path) -> CompiledContract | None:
    """Read a compiled-contract JSON file, or None if missing/corrupt."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CompiledContract(
            name=data["name"],
            abi=data["abi"],
            bytecode=data["bytecode"],
            source_sha256=data["source_sha256"],
            solc_version=data["solc_version"],
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def compile_registry(*, on_progress=None) -> CompiledContract:
    """Return the compiled contract, preferring committed/cached artifacts."""
    if not CONTRACT_PATH.exists():
        raise ContractError(f"Contract source not found: {CONTRACT_PATH}")

    source = CONTRACT_PATH.read_text(encoding="utf-8")
    source_hash = sha256_hex(source.encode("utf-8"))

    # 1. Committed artifact: the runtime/Render path (no toolchain required).
    if _COMMITTED_ARTIFACT.exists():
        committed = _load_artifact_file(_COMMITTED_ARTIFACT)
        if committed and committed.source_sha256 == source_hash:
            if on_progress:
                on_progress(f"using precompiled {CONTRACT_NAME} artifact")
            return committed
        # Present but stale or corrupt -> fall through and recompile.

    # 2. Local solc cache keyed by the source digest.
    cache_path = _BUILD_DIR / f"{CONTRACT_NAME}.{source_hash[:12]}.json"
    if cache_path.exists():
        cached = _load_artifact_file(cache_path)
        if cached:
            return cached
        cache_path.unlink(missing_ok=True)  # corrupt cache: recompile

    # 3. Compile with solc (dev/build-time only).
    compiled = _compile_with_solc(source, source_hash, on_progress)

    _BUILD_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(compiled.to_json(), indent=2), encoding="utf-8")
    return compiled


def precompile(*, on_progress=None) -> Path:
    """(Re)generate the committed artifact from the current contract source.

    Dev/build helper -- forces a solc compile and writes
    ``contracts/build/VerificationRegistry.json`` for committing. Not used at
    runtime.
    """
    if not CONTRACT_PATH.exists():
        raise ContractError(f"Contract source not found: {CONTRACT_PATH}")
    source = CONTRACT_PATH.read_text(encoding="utf-8")
    source_hash = sha256_hex(source.encode("utf-8"))
    compiled = _compile_with_solc(source, source_hash, on_progress)
    _COMMITTED_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    _COMMITTED_ARTIFACT.write_text(
        json.dumps(compiled.to_json(), indent=2) + "\n", encoding="utf-8"
    )
    return _COMMITTED_ARTIFACT


def _compile_with_solc(source: str, source_hash: str, on_progress) -> CompiledContract:
    try:
        import solcx
        from solcx.exceptions import SolcError
    except ImportError as exc:
        raise ContractError(
            "The Solidity compiler (py-solc-x) is not installed and no committed "
            f"artifact matched the current contract.\nExpected: {_COMMITTED_ARTIFACT}",
            hint=(
                "Runtime installs never need solc -- commit an up-to-date "
                "contracts/build/VerificationRegistry.json instead. To (re)generate "
                "it, install the dev tools and run precompile:\n"
                "    pip install -r requirements-dev.txt\n"
                "    python -m app precompile"
            ),
        ) from exc

    _ensure_solc(solcx, on_progress)
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
    except SolcError as exc:
        raise ContractError(f"Solidity compilation failed:\n{exc}") from exc

    key = next((k for k in output if k.endswith(f":{CONTRACT_NAME}")), None)
    if key is None:
        raise ContractError(
            f"solc output does not contain {CONTRACT_NAME}. Found: {list(output)}"
        )

    return CompiledContract(
        name=CONTRACT_NAME,
        abi=output[key]["abi"],
        bytecode=output[key]["bin"],
        source_sha256=source_hash,
        solc_version=SOLC_VERSION,
    )


def _ensure_solc(solcx, on_progress=None) -> None:
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
