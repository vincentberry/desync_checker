#!/usr/bin/env python3
"""
Generateur de video de test pour Desync Checker.
"""

from desync_core import create_test_video, get_default_output_path


def main() -> None:
    print("=== Generateur de video de test Desync Checker ===\n")

    output_file = get_default_output_path("test_desync_video.mp4")
    flash_time = 2.0
    bip_time = 2.1

    result = create_test_video(
        output_path=output_file,
        duration=5.0,
        flash_time=flash_time,
        bip_time=bip_time,
        logger=print,
    )

    print(f"\nFichier genere : {result.output_path}")
    print(f"Ecart attendu : {result.expected_offset_ms:+.0f} ms")
    print(f"Audio integre : {'oui' if result.audio_embedded else 'non'}")


if __name__ == "__main__":
    main()
