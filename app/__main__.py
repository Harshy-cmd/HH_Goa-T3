"""CLI entry point: ``python -m app <command>``.

Argument parsing and top-level error handling live here. Pipeline logic lives
in :mod:`app.pipeline` so that the orchestration is testable without argv.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import PipelineError
from .ui import error_banner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Face ID + Blockchain Verification pipeline.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- run ---------------------------------------------------------------
    run_p = sub.add_parser(
        "run",
        help="Run the full pipeline: detect -> search -> verify -> chain.",
    )
    run_p.add_argument(
        "--image",
        required=True,
        help="Path to the input face image.",
    )
    run_p.add_argument(
        "--face",
        type=int,
        default=None,
        metavar="INDEX",
        help="If multiple faces, select by 0-based index (default: largest).",
    )
    run_p.add_argument(
        "--demo",
        "--judge-mode",
        action="store_true",
        dest="demo",
        help="Run in evaluator demonstration mode with structured dashboard and scorecard.",
    )
    run_p.add_argument(
        "--plain",
        "--raw",
        action="store_true",
        dest="plain",
        help="Run in plain linear log mode instead of the structured evaluator dashboard.",
    )

    # --- demo --------------------------------------------------------------
    demo_p = sub.add_parser(
        "demo",
        help="Run the evaluator demonstration mode with structured dashboard and scorecard.",
    )
    demo_p.add_argument(
        "--image",
        default="samples/images.jpeg",
        help="Path to the input face image (default: samples/images.jpeg).",
    )
    demo_p.add_argument(
        "--face",
        type=int,
        default=None,
        metavar="INDEX",
        help="If multiple faces, select by 0-based index (default: largest).",
    )
    demo_p.add_argument(
        "--judge-mode",
        action="store_true",
        dest="judge_mode",
        help="Alias for full evaluation scoring dashboard.",
    )

    # --- verify ------------------------------------------------------------
    verify_p = sub.add_parser(
        "verify",
        help="Re-verify a stored artifact against the blockchain record.",
    )
    verify_p.add_argument(
        "--record",
        default=None,
        metavar="PATH",
        help="Path to the verification artifact (default: artifacts/latest_verification.json).",
    )

    # --- deploy ------------------------------------------------------------
    sub.add_parser(
        "deploy",
        help="Deploy a fresh VerificationRegistry contract.",
    )

    # --- doctor ------------------------------------------------------------
    sub.add_parser(
        "doctor",
        help="Pre-flight checks: verify credentials and connectivity.",
    )

    # --- download-models ---------------------------------------------------
    sub.add_parser(
        "download-models",
        help="Download face model weights (use in a deploy build step).",
    )

    # --- precompile --------------------------------------------------------
    sub.add_parser(
        "precompile",
        help="Regenerate the committed contract artifact from source (dev; needs py-solc-x).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        from .config import Config

        config = Config.load()

        if args.command == "demo" or (args.command == "run" and not getattr(args, "plain", False)):
            from .demo import run_demo

            return run_demo(args.image, config, face_index=args.face)

        elif args.command == "run":
            from .pipeline import run

            run(args.image, config, face_index=args.face)

        elif args.command == "verify":
            from .pipeline import verify

            verify(args.record, config)

        elif args.command == "deploy":
            from .pipeline import deploy

            deploy(config)

        elif args.command == "doctor":
            from .pipeline import doctor

            doctor(config)

        elif args.command == "download-models":
            from .pipeline import download_models

            download_models()

        elif args.command == "precompile":
            from .pipeline import precompile_contract

            precompile_contract()

        return 0

    except PipelineError as exc:
        error_banner(exc.kind, exc.message, exc.hint)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
