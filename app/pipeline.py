"""End-to-end pipeline orchestration.

Wires the face, search, candidate-verification, and blockchain stages into a
single ``run()`` call. Each stage is logged through the ``ui`` module so the
terminal shows exactly what happened and the screen recording is self-evident.

This module contains zero CLI logic -- argument parsing lives in ``__main__``.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import cv2
import numpy as np

from . import artifacts, ui
from .chain.registry import Registry, load_registry
from .config import Config
from .errors import (
    CandidateFetchError,
    NoFaceDetectedError,
    NoVerifiableCandidateError,
    PipelineError,
)
from .face.detector import FaceDetector, load_image, select_target_face
from .face.encoder import FaceEncoder
from .face.matcher import best_match
from .hashing import record_hash, sha256_hex
from .imaging import prepare_search_copy
from .models import (
    Artifact,
    CandidateVerification,
    FaceComparison,
    SearchResponse,
    VerificationRecord,
)
from .net.fetch import fetch_image
from .search.base import SearchQuery
from .search.registry import build_provider

TOTAL_STEPS = 7


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


def _load_and_detect(
    image_path: str,
    config: Config,
    *,
    face_index: int | None = None,
    on_progress=None,
):
    """Stages 1-3: load image, detect face, encode it."""
    # Step 1 ---------------------------------------------------------------
    ui.step(1, TOTAL_STEPS, "Loading image")
    bgr, meta = load_image(image_path)
    ui.ok(f"Image loaded: {meta.filename}")
    ui.kv("Dimensions", f"{meta.width}x{meta.height}")
    ui.kv("SHA-256", meta.sha256[:16] + "...")
    ui.kv("Size", f"{meta.bytes_len / 1024:.0f} KB")

    # Step 2 ---------------------------------------------------------------
    ui.step(2, TOTAL_STEPS, "Detecting faces")
    detector = FaceDetector(config.detect_confidence, on_progress=on_progress)
    faces = detector.detect(bgr)
    ui.ok(f"{len(faces)} face(s) detected")
    for i, f in enumerate(faces):
        ui.kv(f"  face {i}", f.box.describe())

    target = select_target_face(faces, index=face_index)
    if len(faces) > 1 and face_index is None:
        ui.info(f"Using largest face (face 0, {target.box.width}x{target.box.height} px)")

    # Step 3 ---------------------------------------------------------------
    ui.step(3, TOTAL_STEPS, "Encoding face")
    encoder = FaceEncoder(on_progress=on_progress)
    encoding = encoder.encode(bgr, target)
    ui.ok("Face encoded (128-D SFace embedding)")

    original_bytes = Path(image_path).read_bytes()
    return bgr, meta, original_bytes, encoding, detector, encoder


def _search(
    image_path: str,
    original_bytes: bytes,
    config: Config,
    *,
    on_progress=None,
) -> SearchResponse:
    """Stage 4: reverse image search."""
    ui.step(4, TOTAL_STEPS, "Performing reverse image search")
    provider = build_provider(config)
    ui.info(f"Provider: {provider.description}")

    query = SearchQuery(image_path=Path(image_path), image_bytes=original_bytes)
    response = provider.search(query, on_progress=_ui_progress)

    ui.ok(f"{response.count} candidate(s) discovered")
    social_count = len(response.social_results)
    if social_count:
        ui.ok(f"{social_count} social-media result(s)")
    for r in response.results[:5]:
        tag = f" [{r.platform}]" if r.platform else ""
        ui.kv(f"  #{r.rank}{tag}", _truncate(r.page_url, 80))

    return response


def _verify_candidates(
    response: SearchResponse,
    input_encoding,
    config: Config,
    detector: FaceDetector,
    encoder: FaceEncoder,
) -> CandidateVerification:
    """Stage 5: download candidate images and face-verify them."""
    ui.step(5, TOTAL_STEPS, "Verifying discovered candidates")

    from .search.social import prioritise

    ordered = prioritise(response.results)
    verified: CandidateVerification | None = None
    attempts: list[dict] = []

    for result in ordered:
        # Try image_url first (full publisher image), then thumbnail
        urls_to_try = []
        if result.image_url:
            urls_to_try.append(("publisher", result.image_url))
        if result.thumbnail_url:
            urls_to_try.append(("provider_thumbnail", result.thumbnail_url))

        if not urls_to_try:
            ui.info(f"  #{result.rank}: no image URL available, skipping")
            attempts.append({"rank": result.rank, "url": result.page_url, "status": "no_image_url"})
            continue

        for origin, url in urls_to_try:
            try:
                ui.info(f"  #{result.rank}: fetching {_truncate(url, 70)}")
                fetched = fetch_image(url)
            except CandidateFetchError as exc:
                ui.info(f"  #{result.rank}: {exc.message}")
                attempts.append({"rank": result.rank, "url": url, "status": f"fetch_failed: {exc.message}"})
                continue

            # Decode and detect faces
            arr = cv2.imdecode(
                np.frombuffer(fetched.data, dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if arr is None:
                ui.info(f"  #{result.rank}: could not decode image")
                attempts.append({"rank": result.rank, "url": url, "status": "decode_failed"})
                continue

            cand_faces = detector.detect(arr)
            if not cand_faces:
                ui.info(f"  #{result.rank}: no faces in candidate image")
                attempts.append({"rank": result.rank, "url": url, "status": "no_faces"})
                continue

            cand_encodings = encoder.encode_all(arr, cand_faces)
            if not cand_encodings:
                ui.info(f"  #{result.rank}: faces detected but none could be encoded")
                attempts.append({"rank": result.rank, "url": url, "status": "encode_failed"})
                continue

            best, all_comparisons = best_match(
                encoder,
                input_encoding,
                cand_encodings,
                match_threshold=config.match_threshold,
                review_threshold=config.review_threshold,
            )

            verdict_str = best.verdict
            ui.kv(f"  #{result.rank}", f"faces={len(cand_faces)} best_sim={best.similarity:.3f} -> {verdict_str}")

            cv = CandidateVerification(
                result=result,
                image_sha256=fetched.sha256,
                image_origin=origin,
                image_url_used=url,
                image_bytes_len=fetched.size,
                faces_detected=len(cand_faces),
                best=best,
            )

            attempts.append({
                "rank": result.rank,
                "url": url,
                "origin": origin,
                "faces": len(cand_faces),
                "similarity": best.similarity,
                "verdict": verdict_str,
            })

            if best.is_match:
                verified = cv
                break  # found a match, stop trying URLs for this result

        if verified:
            break  # found a match, stop trying more results

    if not verified:
        raise NoVerifiableCandidateError(
            f"Checked {len(attempts)} candidate(s), but none contained a matching face "
            f"(threshold {config.match_threshold}).",
            hint=(
                "Lower FACE_MATCH_THRESHOLD in .env for a weaker threshold, or try a "
                "different input image that is widely posted online."
            ),
        )

    ui.ok("Verified candidate found!")
    tag = f" [{verified.result.platform}]" if verified.result.platform else ""
    ui.kv("Source", f"{verified.result.source or 'web'}{tag}")
    ui.kv("URL", _truncate(verified.result.page_url, 80))
    ui.kv("Image SHA-256", verified.image_sha256[:16] + "...")
    ui.kv("Faces detected", verified.faces_detected)
    ui.kv("Best similarity", f"{verified.best.similarity:.4f}")
    ui.kv("Threshold", f"{verified.best.threshold}")
    ui.kv("Verdict", verified.best.verdict)

    return verified


def _blockchain_register(
    record: dict,
    rec_hash: str,
    candidate: CandidateVerification,
    config: Config,
) -> dict:
    """Stage 6: write the record hash to the blockchain."""
    ui.step(6, TOTAL_STEPS, "Writing to blockchain")

    registry = load_registry(config.rpc_url, config.contract_address)
    ui.info(f"Network: {registry.network.name} (chain {registry.network.chain_id})")
    ui.info(f"Contract: {registry.address}")

    receipt = registry.register(
        rec_hash,
        source=candidate.result.platform or candidate.result.source or "web",
        candidate_url=candidate.result.page_url,
        private_key=config.private_key,
        on_progress=_ui_progress,
    )

    ui.ok("Transaction confirmed!")
    ui.kv("Tx hash", receipt.transaction_hash)
    ui.kv("Block", receipt.block_number)
    ui.kv("Gas used", receipt.gas_used)
    if receipt.explorer_tx_url:
        ui.kv("Explorer", receipt.explorer_tx_url)

    return receipt.to_json()


def _blockchain_verify(rec_hash: str, config: Config) -> dict | None:
    """Stage 7: read the record back from the chain and compare hashes."""
    ui.step(7, TOTAL_STEPS, "Re-verifying blockchain record")

    registry = load_registry(config.rpc_url, config.contract_address)
    on_chain = registry.get_record(rec_hash)

    return on_chain


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def run(
    image_path: str,
    config: Config,
    *,
    face_index: int | None = None,
) -> None:
    """Execute the full pipeline: detect -> search -> verify -> chain -> check."""
    config.require_search()
    config.require_signer()
    config.require_contract()

    ui.banner("FACE ID + BLOCKCHAIN VERIFICATION")

    # Stages 1-3
    bgr, meta, original_bytes, encoding, detector, encoder = _load_and_detect(
        image_path, config, face_index=face_index, on_progress=_ui_progress
    )

    # Update meta with search copy info
    copy = prepare_search_copy(
        Path(image_path),
        original_bytes,
        max_bytes=500 * 1024,
    )
    meta.search_copy_sha256 = copy.sha256
    meta.search_copy_bytes_len = copy.size

    # Stage 4
    response = _search(image_path, original_bytes, config, on_progress=_ui_progress)

    # Stage 5
    candidate = _verify_candidates(response, encoding, config, detector, encoder)

    # Build the verification record
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    vr = VerificationRecord(
        input_image=meta,
        search=response,
        candidate=candidate,
        detector_model=detector.model_name,
        encoder_model=encoder.model_name,
        metric="cosine",
        threshold=config.match_threshold,
        review_threshold=config.review_threshold,
        created_at=now,
    )
    record = vr.to_record()
    rec_hash = record_hash(record)

    ui.section("RECORD HASH")
    ui.kv("SHA-256", rec_hash)

    # Stage 6
    chain_data = _blockchain_register(record, rec_hash, candidate, config)

    # Stage 7
    on_chain = _blockchain_verify(rec_hash, config)

    # Save artifacts
    artifact = Artifact(record=record, record_hash=rec_hash, blockchain=chain_data)
    art_path = artifacts.write_verification(artifact.to_json())
    ui.info(f"Artifact saved: {art_path}")

    cand_data = {
        "search_provider": response.provider,
        "result_count": response.count,
        "social_count": len(response.social_results),
        "results": [r.to_json() for r in response.results],
    }
    artifacts.write_candidates(cand_data)

    if on_chain:
        chain_record_data = {
            "record_hash": on_chain.record_hash,
            "block_timestamp": on_chain.block_timestamp,
            "submitter": on_chain.submitter,
            "source": on_chain.source,
            "candidate_url": on_chain.candidate_url,
        }
        artifacts.write_blockchain_record(chain_record_data)

    # Final verdict
    ui.section("INTEGRITY VERIFICATION")
    if on_chain:
        ui.kv("Local SHA-256", rec_hash[:32] + "...")
        ui.kv("On-chain SHA-256", on_chain.record_hash[:32] + "...")
        match = rec_hash == on_chain.record_hash
        ui.verdict("INTEGRITY CHECK", match)
    else:
        ui.warn("Could not read back from chain (may need a block)")
        ui.verdict("INTEGRITY CHECK", False)

    ui.section("PIPELINE COMPLETE")
    ui.ok("All stages completed successfully.")
    ui.info(f"To re-verify: python -m app verify")
    ui.info(f"To tamper-test: edit artifacts/latest_verification.json, then re-verify")


def verify(artifact_path: str | None, config: Config) -> None:
    """Re-verify a stored artifact against the blockchain record."""
    config.require_rpc()
    config.require_contract()

    ui.banner("BLOCKCHAIN VERIFICATION")

    payload, path = artifacts.load_verification(artifact_path)
    record = payload["record"]
    stored_hash = payload["record_hash"]

    ui.section("ARTIFACT")
    ui.kv("File", str(path))
    ui.kv("Stored hash", stored_hash[:32] + "...")

    # Recompute the hash from the record
    from .hashing import record_hash as compute_hash

    recomputed = compute_hash(record)
    ui.kv("Recomputed hash", recomputed[:32] + "...")

    local_match = stored_hash == recomputed
    if local_match:
        ui.ok("Stored hash matches recomputed hash (artifact is internally consistent)")
    else:
        ui.warn("Stored hash != recomputed hash -- the artifact file itself was modified")

    # Read from blockchain
    ui.section("BLOCKCHAIN")
    registry = load_registry(config.rpc_url, config.contract_address)
    ui.kv("Network", f"{registry.network.name} (chain {registry.network.chain_id})")
    ui.kv("Contract", registry.address)

    # Try both hashes against the chain
    on_chain_stored = registry.get_record(stored_hash)
    on_chain_recomputed = registry.get_record(recomputed) if recomputed != stored_hash else on_chain_stored

    ui.section("INTEGRITY VERIFICATION")

    if on_chain_recomputed:
        ui.kv("Local SHA-256", recomputed[:32] + "...")
        ui.kv("On-chain SHA-256", on_chain_recomputed.record_hash[:32] + "...")
        chain_match = recomputed == on_chain_recomputed.record_hash
        ui.ok(f"Submitted by: {on_chain_recomputed.submitter}")
        ui.kv("Block timestamp", on_chain_recomputed.block_timestamp)
        ui.kv("Source", on_chain_recomputed.source)
        ui.kv("Candidate URL", _truncate(on_chain_recomputed.candidate_url, 80))
        ui.verdict("VERIFICATION", chain_match)
    elif on_chain_stored and not local_match:
        # The stored hash exists on chain but the recomputed one doesn't --
        # meaning the artifact was tampered with after blockchain registration.
        ui.kv("Recomputed hash", recomputed[:32] + "...")
        ui.kv("On-chain hash", on_chain_stored.record_hash[:32] + "...")
        ui.fail("The record in the artifact has been MODIFIED since it was registered.")
        ui.fail("The recomputed hash does NOT match the blockchain record.")
        ui.verdict("TAMPER DETECTED", False)
    else:
        ui.kv("Recomputed hash", recomputed[:32] + "...")
        ui.fail("No record found on-chain for this hash.")
        ui.fail("Either the record was never registered, or it has been tampered with.")
        ui.verdict("VERIFICATION", False)


def deploy(config: Config) -> None:
    """Deploy a fresh VerificationRegistry contract."""
    from .chain.registry import deploy_registry

    config.require_signer()

    ui.banner("DEPLOY VERIFICATION REGISTRY")

    registry, receipt = deploy_registry(
        config.rpc_url, config.private_key, on_progress=_ui_progress
    )

    ui.ok("Contract deployed!")
    ui.kv("Network", f"{registry.network.name} (chain {registry.network.chain_id})")
    ui.kv("Address", registry.address)
    ui.kv("Tx hash", receipt.transaction_hash)
    ui.kv("Block", receipt.block_number)
    ui.kv("Gas used", receipt.gas_used)
    if receipt.explorer_tx_url:
        ui.kv("Explorer", receipt.explorer_tx_url)

    print()
    ui.ok("Add this to your .env file:")
    print(f"    CONTRACT_ADDRESS={registry.address}")


def doctor(config: Config) -> None:
    """Pre-flight check: verify credentials and connectivity."""
    ui.banner("DOCTOR -- PRE-FLIGHT CHECKS")

    # 1. Search provider
    ui.section("SEARCH PROVIDER")
    ui.kv("Provider", config.search_provider)
    try:
        config.require_search()
        provider = build_provider(config)
        status = provider.check_credentials()
        ui.ok(f"Credentials valid: {status}")
    except PipelineError as exc:
        ui.fail(exc.message)

    # 2. Face models
    ui.section("FACE MODELS")
    from .face.models_store import ensure_all

    try:
        paths = ensure_all(on_progress=_ui_progress)
        for name, path in paths.items():
            ui.ok(f"{name}: {path.name}")
    except PipelineError as exc:
        ui.fail(exc.message)

    # 3. Blockchain
    ui.section("BLOCKCHAIN")
    ui.kv("RPC URL", config.rpc_url or "(not set)")
    try:
        config.require_rpc()
        from .chain.client import connect

        web3, network = connect(config.rpc_url)
        ui.ok(f"Connected: {network.name} (chain {network.chain_id})")
    except PipelineError as exc:
        ui.fail(exc.message)

    if config.private_key:
        try:
            from eth_account import Account

            acct = Account.from_key(config.private_key)
            balance = web3.eth.get_balance(acct.address)
            from web3 import Web3

            ui.kv("Account", acct.address)
            ui.kv("Balance", f"{Web3.from_wei(balance, 'ether'):.6f} ETH")
        except Exception as exc:
            ui.fail(f"Private key issue: {exc}")
    else:
        ui.warn("PRIVATE_KEY not set -- cannot deploy or register")

    if config.contract_address:
        try:
            config.require_contract()
            registry = load_registry(config.rpc_url, config.contract_address)
            count = registry.record_count()
            ui.ok(f"Contract at {registry.address}: {count} record(s)")
        except PipelineError as exc:
            ui.fail(exc.message)
    else:
        ui.warn("CONTRACT_ADDRESS not set -- deploy first with: python -m app deploy")

    print()
    ui.ok("Pre-flight checks complete.")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _ui_progress(message: str) -> None:
    ui.info(message)


def _truncate(s: str, limit: int = 80) -> str:
    return s if len(s) <= limit else s[: limit - 3] + "..."
