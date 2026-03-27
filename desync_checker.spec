# -*- mode: python ; coding: utf-8 -*-
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
    normalized = str(candidate).replace("/", "\\").lower()
    return "\\chocolatey\\bin\\" in normalized


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
