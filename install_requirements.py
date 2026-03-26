#!/usr/bin/env python3
"""
Script d'installation des dependances pour Desync Checker.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIREMENTS_FILE = ROOT / "requirements.txt"


def install_package(package: str) -> bool:
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"[OK] {package} installe")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[ERREUR] impossible d'installer {package}: {exc}")
        return False


def load_requirements() -> list[str]:
    if not REQUIREMENTS_FILE.exists():
        return ["PyQt6", "opencv-python", "librosa", "audioread", "scipy", "numpy"]

    requirements: list[str] = []
    for raw_line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirements.append(line)
    return requirements


def check_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def suggest_ffmpeg_installation() -> None:
    system = platform.system().lower()
    print("\nFFmpeg n'est pas detecte.")
    print("Installation recommandee :")
    if system == "windows":
        print("- winget install Gyan.FFmpeg")
        print("- ou choco install ffmpeg")
    elif system == "darwin":
        print("- brew install ffmpeg")
    elif system == "linux":
        print("- sudo apt install ffmpeg")
    else:
        print("- installe FFmpeg manuellement et ajoute-le au PATH")


def main() -> None:
    print("=== Installation des dependances Desync Checker ===\n")
    print(f"Systeme : {platform.system()} {platform.release()}")
    print(f"Python : {sys.version.split()[0]}")

    requirements = load_requirements()
    print(f"\nPackages a installer : {', '.join(requirements)}\n")

    installed = 0
    for package in requirements:
        if install_package(package):
            installed += 1

    ffmpeg_path = check_ffmpeg()

    print("\n=== Resume ===")
    print(f"Packages Python : {installed}/{len(requirements)}")
    if ffmpeg_path:
        print(f"FFmpeg : OK ({ffmpeg_path})")
    else:
        print("FFmpeg : non detecte")
        suggest_ffmpeg_installation()

    if installed == len(requirements):
        print("\nEtapes suivantes :")
        print("- python test_dependencies.py")
        print("- python desync_cli.py doctor")
        print("- python desync_checker_app.py")
    else:
        print("\nCertaines dependances ne sont pas installees. Corrige les erreurs ci-dessus avant de continuer.")


if __name__ == "__main__":
    main()
