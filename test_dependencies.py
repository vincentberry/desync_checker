#!/usr/bin/env python3
"""
Diagnostic simple des dependances et de l'environnement.
"""

from desync_core import format_environment_report, check_environment


def test_imports() -> bool:
    print("=== Test des imports ===\n")

    imports_to_test = [
        ("cv2", "OpenCV"),
        ("numpy", "NumPy"),
        ("librosa", "Librosa"),
        ("audioread.ffdec", "Audioread FFmpeg"),
        ("scipy.signal", "SciPy Signal"),
        ("scipy.io.wavfile", "SciPy WAV"),
        ("PyQt6.QtWidgets", "PyQt6 Widgets"),
        ("PyQt6.QtGui", "PyQt6 GUI"),
        ("PyQt6.QtCore", "PyQt6 Core"),
        ("PyQt6.QtMultimedia", "PyQt6 Multimedia"),
        ("desync_core", "Coeur metier"),
    ]

    success_count = 0
    for module_name, description in imports_to_test:
        try:
            __import__(module_name)
            print(f"[OK] {description} ({module_name})")
            success_count += 1
        except Exception as exc:
            print(f"[ERREUR] {description} ({module_name}) -> {exc}")

    print(f"\nResultat imports : {success_count}/{len(imports_to_test)}")
    return success_count == len(imports_to_test)


def test_basic_functionality() -> bool:
    print("\n=== Test fonctionnel minimal ===\n")
    try:
        import cv2
        import numpy as np
        from scipy.io.wavfile import read as wav_read
        from scipy.io.wavfile import write as wav_write
        from tempfile import NamedTemporaryFile

        image = np.zeros((100, 100, 3), dtype=np.uint8)
        _ = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        print("[OK] Conversion OpenCV")

        samples = np.zeros(400, dtype=np.int16)
        samples[100:160] = 12000
        with NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            wav_write(temp_path, 44100, samples)
            sample_rate, loaded_samples = wav_read(temp_path)
            if sample_rate != 44100 or len(loaded_samples) != len(samples):
                raise ValueError("roundtrip WAV invalide")
            print("[OK] Lecture/ecriture WAV")
        finally:
            import os

            if os.path.exists(temp_path):
                os.unlink(temp_path)

        return True
    except Exception as exc:
        print(f"[ERREUR] test fonctionnel -> {exc}")
        return False


def print_environment() -> None:
    print("\n=== Environnement ===\n")
    for line in format_environment_report(check_environment()):
        print(f"- {line}")


if __name__ == "__main__":
    imports_ok = test_imports()
    functionality_ok = test_basic_functionality() if imports_ok else False
    print_environment()

    if imports_ok and functionality_ok:
        print("\nEnvironnement pret pour Desync Checker.")
    else:
        print("\nL'environnement n'est pas encore totalement pret.")
