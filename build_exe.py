#!/usr/bin/env python3
"""
Build script for the Desync Checker Windows executable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from desync_metadata import APP_CREATOR, APP_GITHUB_URL, APP_LICENSE_NAME, APP_NAME, APP_VERSION


ROOT = Path(__file__).resolve().parent
APP_FILE = ROOT / "desync_checker_app.py"
SPEC_FILE = ROOT / "desync_checker.spec"
DEFAULT_DIST_DIR = ROOT / "dist"
DEFAULT_BUILD_DIR = ROOT / "build"
ICON_FILE = ROOT / "assets" / "desync_checker.ico"


SPEC_CONTENT = """# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import subprocess
import shutil


PROJECT_ROOT = Path.cwd()
ASSETS_DIR = PROJECT_ROOT / "assets"


def _find_tool_on_path(tool_name):
    candidates = []
    try:
        result = subprocess.run(["where", tool_name], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for raw_line in result.stdout.splitlines():
                candidate = raw_line.strip()
                if candidate:
                    candidates.append(candidate)
    except Exception:
        pass

    which_candidate = shutil.which(tool_name)
    if which_candidate:
        candidates.append(which_candidate)

    unique = []
    seen = set()
    for candidate in candidates:
        key = str(Path(candidate)).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _is_chocolatey_shim(candidate):
    normalized = str(candidate).replace("/", "\\\\").lower()
    return "\\\\chocolatey\\\\bin\\\\" in normalized


def _resolve_tool_binary(tool_name):
    real_candidates = [
        Path("C:/ProgramData/chocolatey/lib/ffmpeg/tools/ffmpeg/bin") / f"{tool_name}.exe",
        Path("C:/ProgramData/chocolatey/lib/ffmpeg/tools/bin") / f"{tool_name}.exe",
    ]
    for candidate in real_candidates:
        if candidate.exists():
            return str(candidate)

    for candidate in _find_tool_on_path(tool_name):
        if _is_chocolatey_shim(candidate):
            continue
        if Path(candidate).exists():
            return str(candidate)

    for candidate in _find_tool_on_path(tool_name):
        if Path(candidate).exists():
            return str(candidate)

    return None


def _collect_runtime_binaries():
    binaries = []
    seen = set()

    ffmpeg_path = _resolve_tool_binary("ffmpeg")
    ffprobe_path = _resolve_tool_binary("ffprobe")
    if not ffprobe_path and ffmpeg_path:
        ffprobe_candidate = Path(ffmpeg_path).with_name("ffprobe.exe")
        if ffprobe_candidate.exists():
            ffprobe_path = str(ffprobe_candidate)

    for tool_path in (ffmpeg_path, ffprobe_path):
        if not tool_path:
            continue
        resolved = str(Path(tool_path).resolve())
        key = resolved.lower()
        if key in seen:
            continue
        seen.add(key)
        binaries.append((resolved, "."))

    return binaries


block_cipher = None
bundled_binaries = _collect_runtime_binaries()
datas = []

for asset_name in ("desync_checker_logo.png", "desync_checker.ico"):
    asset_path = ASSETS_DIR / asset_name
    if asset_path.exists():
        datas.append((str(asset_path), "assets"))

for document_name in ("LICENSE", "README.md"):
    document_path = PROJECT_ROOT / document_name
    if document_path.exists():
        datas.append((str(document_path), "."))


a = Analysis(
    ["desync_checker_app.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=bundled_binaries,
    datas=datas,
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtWidgets",
        "PyQt6.QtGui",
        "PyQt6.QtMultimedia",
        "librosa",
        "librosa.core",
        "librosa.core.audio",
        "scipy",
        "scipy.signal",
        "scipy.io.wavfile",
        "cv2",
        "numpy",
        "tempfile",
        "subprocess",
        "audioread",
        "audioread.ffdec",
        "numba",
        "numba.core",
        "numba.typed",
        "sklearn",
        "sklearn.utils._cython_blas",
        "sklearn.neighbors.typedefs",
        "sklearn.neighbors.quad_tree",
        "sklearn.tree._utils",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "pandas",
        "jupyter",
        "notebook",
        "IPython",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
icon_path = ASSETS_DIR / "desync_checker.ico"

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DesyncChecker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)
"""


def install_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401

        print("[OK] PyInstaller deja installe")
        return True
    except ImportError:
        print("[INFO] Installation de PyInstaller...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            print("[OK] PyInstaller installe")
            return True
        except subprocess.CalledProcessError as exc:
            print(f"[ERREUR] impossible d'installer PyInstaller : {exc}")
            return False


def write_spec_file() -> None:
    SPEC_FILE.write_text(SPEC_CONTENT, encoding="utf-8")
    print(f"[OK] Spec PyInstaller mise a jour : {SPEC_FILE.name}")


def _is_desync_checker_running() -> bool:
    if sys.platform != "win32":
        return False

    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq DesyncChecker.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False

    output = (result.stdout or "").strip()
    return "DesyncChecker.exe" in output


def _clean_directory(directory: Path) -> tuple[bool, str | None]:
    if not directory.exists():
        return True, None

    try:
        shutil.rmtree(directory)
        print(f"[OK] Nettoyage : {directory.name}/")
        return True, None
    except PermissionError as exc:
        return False, str(exc)


def _create_fallback_directories() -> tuple[Path, Path] | None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fallback_dist_dir = ROOT / f"dist_{timestamp}"
    fallback_build_dir = ROOT / f"build_{timestamp}"

    fallback_build_ok, fallback_build_error = _clean_directory(fallback_build_dir)
    if not fallback_build_ok:
        print(f"[ERREUR] impossible de preparer {fallback_build_dir.name}/ : {fallback_build_error}")
        return None

    fallback_dist_ok, fallback_dist_error = _clean_directory(fallback_dist_dir)
    if not fallback_dist_ok:
        print(f"[ERREUR] impossible de preparer {fallback_dist_dir.name}/ : {fallback_dist_error}")
        return None

    print(f"[INFO] Build redirigee vers {fallback_dist_dir.name}/")
    return fallback_dist_dir, fallback_build_dir


def prepare_build_directories() -> tuple[Path, Path] | None:
    build_ok, build_error = _clean_directory(DEFAULT_BUILD_DIR)
    if not build_ok:
        print(f"[ERREUR] impossible de nettoyer {DEFAULT_BUILD_DIR.name}/ : {build_error}")
        return None

    if _is_desync_checker_running():
        print("[ATTENTION] DesyncChecker.exe est en cours d'execution.")
        return _create_fallback_directories()

    dist_ok, dist_error = _clean_directory(DEFAULT_DIST_DIR)
    if dist_ok:
        return DEFAULT_DIST_DIR, DEFAULT_BUILD_DIR

    print(
        "[ATTENTION] impossible de nettoyer dist/. "
        "DesyncChecker.exe est probablement encore ouvert ou verrouille par Windows."
    )
    print(f"[INFO] Detail : {dist_error}")

    return _create_fallback_directories()


def _looks_like_locked_output_error(output: str) -> bool:
    lowered = output.lower()
    return "permissionerror" in lowered and "desyncchecker.exe" in lowered and "winerror 5" in lowered


def compile_exe(dist_dir: Path, build_dir: Path) -> tuple[bool, str]:
    print("[INFO] Compilation de l'executable en cours...")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--clean",
                "--noconfirm",
                "--distpath",
                str(dist_dir),
                "--workpath",
                str(build_dir),
                str(SPEC_FILE),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        print("[ERREUR] timeout pendant la compilation (>15 minutes)")
        return False, "timeout"
    except Exception as exc:
        print(f"[ERREUR] lancement PyInstaller impossible : {exc}")
        return False, str(exc)

    if result.returncode != 0:
        combined_output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        return False, combined_output

    exe_path = dist_dir / "DesyncChecker.exe"
    if not exe_path.exists():
        print("[ERREUR] compilation terminee mais executable introuvable.")
        return False, "executable introuvable"

    exe_size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"[OK] Executable cree : {exe_path}")
    print(f"[OK] Taille : {exe_size_mb:.1f} MB")
    return True, ""


def create_readme(dist_dir: Path) -> None:
    ffmpeg_embed_status = "integre a l'executable si present au moment de la build"
    icon_status = "logo et icone integres"
    readme_content = f"""{APP_NAME} - Version portable

Lancement
- Double-clique sur DesyncChecker.exe

Projet
- version : {APP_VERSION}
- createur : {APP_CREATOR}
- licence : {APP_LICENSE_NAME}
- github : {APP_GITHUB_URL}

Fonctions disponibles
- analyse auto audio/video
- timeline manuelle avec frame par frame
- raccourcis clavier et infos media

Packaging
- {ffmpeg_embed_status}
- {icon_status}

Notes
- si FFmpeg n'etait pas detecte pendant la build, certaines fonctions audio ou de generation peuvent etre degradees
- build generee le {datetime.now().strftime("%Y-%m-%d %H:%M")}
"""
    (dist_dir / "README.txt").write_text(readme_content, encoding="utf-8")
    print("[OK] README de distribution cree")


def copy_license(dist_dir: Path) -> None:
    license_file = ROOT / "LICENSE"
    if not license_file.exists():
        return
    shutil.copy2(license_file, dist_dir / "LICENSE.txt")
    print("[OK] Licence de distribution copiee")


def validate_inputs() -> bool:
    if not APP_FILE.exists():
        print(f"[ERREUR] fichier introuvable : {APP_FILE.name}")
        return False

    if not ICON_FILE.exists():
        print(f"[INFO] icone absente pour le moment : {ICON_FILE}")

    return True


def main() -> bool:
    print(f"=== Build {APP_NAME} v{APP_VERSION} ===\n")

    if not validate_inputs():
        return False

    if not install_pyinstaller():
        return False

    write_spec_file()
    directories = prepare_build_directories()
    if directories is None:
        return False
    dist_dir, build_dir = directories

    compiled, compile_output = compile_exe(dist_dir, build_dir)
    if not compiled and dist_dir == DEFAULT_DIST_DIR and _looks_like_locked_output_error(compile_output):
        print("[ATTENTION] Le fichier de sortie a ete verrouille pendant la compilation.")
        retry_directories = _create_fallback_directories()
        if retry_directories is None:
            print("[ERREUR] impossible de preparer un dossier de repli pour la nouvelle tentative.")
            print(compile_output)
            return False
        dist_dir, build_dir = retry_directories
        compiled, compile_output = compile_exe(dist_dir, build_dir)

    if not compiled:
        print("[ERREUR] la compilation a echoue.")
        if compile_output.strip():
            print(compile_output)
        return False

    create_readme(dist_dir)
    copy_license(dist_dir)

    print("\nBuild terminee.")
    print(f"Sortie : {dist_dir / 'DesyncChecker.exe'}")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
