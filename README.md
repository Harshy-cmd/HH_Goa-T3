# Face ID + Blockchain Verification

A compact, end-to-end pipeline that detects a face in an input image, performs a **genuine** reverse-image search to discover where that face appears publicly on the web, verifies the discovered image contains the same face, fingerprints the verification data, and commits it to an Ethereum-compatible blockchain -- then proves the record has not been tampered with.

Built for **Hacker House Goa 2026 -- Shortlisting Task #3**.

## What It Does

```
INPUT FACE IMAGE
      |
  Face Detection (YuNet)
      |
  Face Encoding (SFace, 128-D)
      |
  Reverse Image Search (SerpAPI Google Lens / Google Vision)
      |
  Candidate Discovery (real web/social results)
      |
  Face Verification (cosine similarity, threshold 0.363)
      |
  SHA-256 Fingerprint (canonical JSON)
      |
  Blockchain Registry (Ethereum Sepolia / local Anvil)
      |
  On-chain Integrity Verification
```

Every step is genuine. No results are hardcoded, no searches are faked, and no blockchain transactions are pre-baked.

## Features

- **Face detection** with OpenCV YuNet (millisecond-level, no cmake/dlib needed)
- **Face encoding** with SFace (128-D embeddings, cosine similarity)
- **Genuine reverse-image search** via SerpAPI Google Lens (primary) or Google Vision WEB_DETECTION (fallback)
- **Social media prioritisation** -- results from X, Reddit, Instagram, etc. are tried first
- **Candidate face verification** -- downloaded images are independently face-verified
- **SHA-256 fingerprinting** with deterministic canonical JSON serialisation
- **Blockchain registration** on Ethereum Sepolia (or local Anvil for testing)
- **Tamper detection** -- modify any field and the hash changes
- **Clean CLI** with step-by-step output suitable for unedited screen recording
- **66 unit tests** covering hashing, matching, serialization, config validation

## Tech Stack

| Component | Library | Why |
|-----------|---------|-----|
| Face detection | OpenCV YuNet (`cv2.FaceDetectorYN`) | Ships in the pip wheel, no cmake/MSVC needed |
| Face encoding | OpenCV SFace (`cv2.FaceRecognizerSF`) | 128-D embeddings with published threshold |
| Reverse search (primary) | SerpAPI Google Lens | Local file upload, no public hosting needed |
| Reverse search (fallback) | Google Cloud Vision WEB_DETECTION | Different index, inline base64 |
| Blockchain | web3.py + Ethereum Sepolia | Public testnet, no API key for RPC |
| Contract compilation | py-solc-x | Downloads solc, no Node/Hardhat/Foundry needed |
| Hashing | hashlib (stdlib) | SHA-256, deterministic canonical JSON |
| Config | python-dotenv | `.env` file loading |
| Testing | pytest | 66 tests, no network required |

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd HH-Goa-T3

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
SERPAPI_API_KEY=your_key_here
RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
PRIVATE_KEY=0xyour_throwaway_testnet_private_key
```

### 3. Get testnet ETH

Fund your **throwaway** testnet wallet from a Sepolia faucet:
- https://cloud.google.com/application/web3/faucet/ethereum/sepolia
- https://www.alchemy.com/faucets/ethereum-sepolia

You need about 0.005 ETH (far less than a faucet drip).

### 4. Deploy the contract

```bash
python -m app deploy
```

Copy the printed `CONTRACT_ADDRESS` into your `.env`.

### 5. Get a SerpAPI key

Sign up at https://serpapi.com/users/sign_up (free tier: 100 searches/month).

Copy your API key to `SERPAPI_API_KEY` in `.env`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SEARCH_PROVIDER` | No | `serpapi` (default) or `google_vision` |
| `SERPAPI_API_KEY` | Yes* | SerpAPI key for Google Lens search |
| `GOOGLE_VISION_API_KEY` | Yes* | Google Cloud Vision API key (if using fallback) |
| `RPC_URL` | Yes | Ethereum JSON-RPC endpoint |
| `PRIVATE_KEY` | Yes | Throwaway testnet wallet private key |
| `CONTRACT_ADDRESS` | Yes | Deployed VerificationRegistry address |
| `FACE_MATCH_THRESHOLD` | No | SFace cosine threshold (default: 0.363) |
| `FACE_REVIEW_THRESHOLD` | No | "Possible match" lower bound (default: 0.300) |
| `FACE_DETECT_CONFIDENCE` | No | YuNet detection confidence (default: 0.850) |

*Only the key for your selected provider is required.

## Blockchain

- **Network**: Ethereum Sepolia testnet (public, keyless RPC)
- **Contract**: `VerificationRegistry.sol` -- a minimal Solidity 0.8.28 contract
- **What is stored on-chain**: SHA-256 hash of the canonical verification record, platform label, candidate URL, timestamp, submitter address
- **What is deliberately NOT stored**: face images, face embeddings, biometric data, personal information, API keys
- **Why**: the blockchain proves that the recorded data has not changed since commitment. It does not prove the underlying claim was true

The contract rejects duplicate registrations (same hash cannot be overwritten) and stores an immutable timestamp.

## Reverse Image Search

### Primary: SerpAPI Google Lens

The pipeline uploads the input image to SerpAPI's Image API (the image is never publicly hosted), then queries Google Lens for visual matches. Results include the publisher's image URL, page URL, and platform label.

### Fallback: Google Vision WEB_DETECTION

If SerpAPI quota runs out, set `SEARCH_PROVIDER=google_vision`. Vision accepts inline base64 images and returns pages hosting matching images.

**Both providers are genuine reverse-image-search engines.** No results are hardcoded, cached, or pre-seeded.

## Face Matching

- **Model**: SFace (`face_recognition_sface_2021dec.onnx`)
- **Embedding**: 128 dimensions
- **Distance metric**: Cosine similarity (higher = more similar)
- **Match threshold**: 0.363 (published by OpenCV for this model)
- **Possible match band**: 0.300 - 0.363 (our conservative convention)
- **L2 distance**: also reported for transparency

A **MATCH** means the model scores two face crops as the same identity. It is **not** proof of real-world identity.

## Running

### Full pipeline

```bash
python -m app run --image samples/input.jpg
```

### Verify a stored record

```bash
python -m app verify
```

### Tamper demonstration

1. Run the pipeline: `python -m app run --image samples/input.jpg`
2. Open `artifacts/latest_verification.json`
3. Change any value (e.g., change `"similarity"` from `0.45` to `0.99`)
4. Run: `python -m app verify`
5. The output shows `TAMPER DETECTED` because the recomputed hash no longer matches the blockchain

### Pre-flight check

```bash
python -m app doctor
```

### Deploy a new contract

```bash
python -m app deploy
```

## Project Structure

```
app/
    __init__.py          # Package, version
    __main__.py          # CLI entry point (argparse)
    pipeline.py          # End-to-end orchestration
    config.py            # Environment loading + validation
    errors.py            # Typed error hierarchy
    hashing.py           # Canonical JSON + SHA-256
    models.py            # Dataclasses for all pipeline stages
    imaging.py           # Search copy preparation (size limits)
    artifacts.py         # Read/write JSON artifacts
    ui.py                # Terminal output helpers
    face/
        detector.py      # YuNet face detection
        encoder.py       # SFace 128-D encoding
        matcher.py       # Cosine comparison + 3-way verdict
        models_store.py  # Model download + SHA-256 verification
    search/
        base.py          # ReverseImageSearchProvider interface
        serpapi.py       # SerpAPI Google Lens (primary)
        google_vision.py # Google Vision WEB_DETECTION (fallback)
        registry.py      # Provider factory
        social.py        # Social platform detection + ranking
    chain/
        client.py        # Web3 connection + network identification
        compile.py       # Solidity compilation (py-solc-x)
        registry.py      # Deploy, register, read-back
    net/
        fetch.py         # Candidate image download (SSRF-safe)
contracts/
    VerificationRegistry.sol  # The smart contract
tests/
    test_hashing.py      # Canonical hashing tests
    test_matching.py     # Face comparison logic tests
    test_serialization.py # Record round-trip tests
    test_config.py       # Configuration validation tests
    test_social.py       # Social platform detection tests
artifacts/               # Pipeline output (gitignored)
models/                  # ONNX weights (gitignored, fetched on first run)
samples/                 # Input images (gitignored, biometric data)
```

## Tests

```bash
python -m pytest tests/ -v
```

66 tests covering hashing, matching, serialization, config, and social detection. No network or API keys required.

## Limitations

This section is intentionally thorough. Honest documentation makes the project more credible, not less.

- **Face similarity is not proof of identity.** Cosine similarity tells you two face crops scored above a threshold. It does not establish who a person is in the real world.
- **Reverse-image search depends on provider indexing.** If an image has never been indexed by Google, the search will return no results. This is a property of the search engine, not a bug.
- **Social platforms may block automated access.** CDNs routinely block hotlinking. The pipeline tries multiple URLs per candidate and reports which ones fail.
- **False positives and false negatives exist.** No face recognition model is perfect. SFace's published threshold was chosen by the model authors, not by us.
- **Blockchain proves integrity, not truth.** The chain proves the recorded data has not changed. It does not prove the underlying face match was correct or that the search result was meaningful.
- **Public testnets are not production infrastructure.** Sepolia may reorganise, be deprecated, or experience downtime. The pipeline supports any EVM-compatible chain.
- **The 500 KB SerpAPI upload limit** means large images are re-encoded for search. The input fingerprint always refers to the original file; the search copy's digest is recorded separately.

## Privacy / Responsible Use

This system is intended for controlled verification of publicly available visual content. It:

- Does **not** collect personal information
- Does **not** persist face embeddings (they exist in memory only during execution)
- Does **not** upload biometric data to the blockchain
- Does **not** bypass authentication, CAPTCHAs, or access controls
- Does **not** access private profiles or paywalled content
- Does **not** claim to identify real-world individuals

Face similarity is a mathematical score. Whether it has any meaningful relationship to real-world identity depends on context that this system does not possess and does not claim to provide.

## License

MIT
