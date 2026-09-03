"""Provider selection."""

from __future__ import annotations

from ..config import Config
from ..errors import ConfigError
from .base import ReverseImageSearchProvider
from .google_vision import GoogleVisionWebDetectionProvider
from .serpapi import SerpApiGoogleLensProvider


def build_provider(config: Config) -> ReverseImageSearchProvider:
    """Instantiate the configured provider, after checking its credentials exist."""
    config.require_search()
    if config.search_provider == "serpapi":
        return SerpApiGoogleLensProvider(config.serpapi_api_key)
    if config.search_provider == "google_vision":
        return GoogleVisionWebDetectionProvider(config.google_vision_api_key)
    raise ConfigError(f"Unknown SEARCH_PROVIDER: {config.search_provider!r}")
