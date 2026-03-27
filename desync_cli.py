#!/usr/bin/env python3
"""
CLI pour industrialiser le workflow de Desync Checker.
"""

from __future__ import annotations

import argparse
import sys

from desync_metadata import APP_CREATOR, APP_GITHUB_URL, APP_LICENSE_NAME, APP_NAME, APP_VERSION
from desync_core import (
    analyze_video,
    check_environment,
    create_test_video,
    format_environment_report,
    get_default_output_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} CLI v{APP_VERSION} - Cree par {APP_CREATOR} - {APP_GITHUB_URL}"
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} CLI v{APP_VERSION} ({APP_LICENSE_NAME})")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Verifier l'environnement local")
    doctor_parser.set_defaults(handler=run_doctor)

    analyze_parser = subparsers.add_parser("analyze", help="Analyser un fichier video")
    analyze_parser.add_argument("video", help="Chemin vers la video a analyser")
    analyze_parser.set_defaults(handler=run_analyze)

    generate_parser = subparsers.add_parser("generate", help="Generer une video de test")
    generate_parser.add_argument(
        "--output",
        default=get_default_output_path("test_desync_video.mp4"),
        help="Chemin du MP4 de sortie",
    )
    generate_parser.add_argument("--duration", type=float, default=5.0, help="Duree en secondes")
    generate_parser.add_argument("--flash-time", type=float, default=2.0, help="Moment du flash")
    generate_parser.add_argument("--offset-ms", type=float, default=100.0, help="Ecart bip-flash en ms")
    generate_parser.set_defaults(handler=run_generate)

    return parser


def run_doctor(_args: argparse.Namespace) -> int:
    report = check_environment()
    for line in format_environment_report(report):
        print(line)
    return 0 if report.ffmpeg_available else 1


def run_analyze(args: argparse.Namespace) -> int:
    result = analyze_video(args.video, logger=print)
    print("\n=== Resume ===")
    print(result.message)
    if result.flash_time is not None:
        print(f"Flash : {result.flash_time:.3f}s")
    if result.bip_time is not None:
        print(f"Bip : {result.bip_time:.3f}s")
    if result.offset_ms is not None:
        print(f"Ecart : {result.offset_ms:+.1f} ms")
    return 0 if result.offset_ms is not None else 2


def run_generate(args: argparse.Namespace) -> int:
    bip_time = args.flash_time + (args.offset_ms / 1000.0)
    result = create_test_video(
        output_path=args.output,
        duration=args.duration,
        flash_time=args.flash_time,
        bip_time=bip_time,
        logger=print,
    )

    print("\n=== Resume ===")
    print(result.message)
    print(f"Sortie : {result.output_path}")
    print(f"Ecart attendu : {result.expected_offset_ms:+.1f} ms")
    return 0 if result.audio_embedded else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
