#!/usr/bin/env bash
# Exit on error
set -euo pipefail

# Upgrade pip and install production dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Pre-download face detection (YuNet) and recognition (SFace) model weights (~39 MB)
# This ensures cold starts don't hit model download latency during user requests
python -m app download-models
