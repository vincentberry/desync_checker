#!/usr/bin/env python3
"""
Genere rapidement des videos de reference synchronisee et desynchronisee.
"""

from desync_core import create_test_video, get_default_output_path


def main() -> None:
    print("=== Creation des videos de reference ===\n")

    sync_result = create_test_video(
        output_path=get_default_output_path("test_sync_video.mp4"),
        duration=5.0,
        flash_time=2.0,
        bip_time=2.0,
        logger=print,
    )
    print(f"\nVideo synchro : {sync_result.output_path} ({sync_result.expected_offset_ms:+.0f} ms)")

    desync_result = create_test_video(
        output_path=get_default_output_path("test_slight_desync_video.mp4"),
        duration=5.0,
        flash_time=2.0,
        bip_time=2.02,
        logger=print,
    )
    print(f"Video legere desync : {desync_result.output_path} ({desync_result.expected_offset_ms:+.0f} ms)")


if __name__ == "__main__":
    main()
