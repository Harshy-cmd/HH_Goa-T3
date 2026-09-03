"""Typed error hierarchy.

Every failure mode in the pipeline maps to one of these so the CLI can print a
human-readable cause instead of a traceback -- and so that no failure can ever
be silently swallowed and replaced with placeholder data.
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base class for every expected (i.e. reportable) failure."""

    #: Short label shown in the CLI error banner.
    kind = "ERROR"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


# --- configuration -----------------------------------------------------------


class ConfigError(PipelineError):
    kind = "CONFIGURATION ERROR"


# --- input image / face ------------------------------------------------------


class ImageError(PipelineError):
    kind = "IMAGE ERROR"


class NoFaceDetectedError(PipelineError):
    kind = "NO FACE DETECTED"


class AmbiguousFaceError(PipelineError):
    """Multiple faces found and no unambiguous target was selected."""

    kind = "MULTIPLE FACES"


class ModelError(PipelineError):
    kind = "MODEL ERROR"


# --- reverse image search ----------------------------------------------------


class SearchError(PipelineError):
    kind = "SEARCH ERROR"


class SearchAuthError(SearchError):
    kind = "SEARCH AUTHENTICATION FAILED"


class SearchQuotaError(SearchError):
    kind = "SEARCH QUOTA EXHAUSTED"


class NoSearchResultsError(SearchError):
    kind = "NO SEARCH RESULTS"


# --- candidate retrieval / verification --------------------------------------


class CandidateFetchError(PipelineError):
    kind = "CANDIDATE UNAVAILABLE"


class NoVerifiableCandidateError(PipelineError):
    """Search returned results, but none could be face-verified."""

    kind = "NO VERIFIABLE CANDIDATE"


# --- blockchain --------------------------------------------------------------


class ChainError(PipelineError):
    kind = "BLOCKCHAIN ERROR"


class ChainConnectionError(ChainError):
    kind = "BLOCKCHAIN UNREACHABLE"


class InsufficientFundsError(ChainError):
    kind = "INSUFFICIENT TESTNET FUNDS"


class ContractError(ChainError):
    kind = "CONTRACT ERROR"


class TransactionError(ChainError):
    kind = "TRANSACTION FAILED"


# --- artifacts ---------------------------------------------------------------


class ArtifactError(PipelineError):
    kind = "ARTIFACT ERROR"
