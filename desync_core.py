from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable
import json
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import librosa
import numpy as np
from scipy.io.wavfile import read as wav_read
from scipy.io.wavfile import write as wav_write
from scipy.signal import find_peaks


Logger = Callable[[str], None]

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}


@dataclass(frozen=True)
class DetectionConfig:
    target_freq: int = 1000
    fallback_target_frequencies: tuple[int, ...] = (800, 1200, 1500, 2000)
    freq_tolerance: int = 150
    sync_tolerance_ms: float = 40.0
    min_analysis_start_s: float = 0.5
    baseline_frames: int = 30

    def all_target_frequencies(self) -> list[int]:
        ordered = [self.target_freq, *self.fallback_target_frequencies]
        seen: set[int] = set()
        result: list[int] = []
        for freq in ordered:
            if freq not in seen:
                seen.add(freq)
                result.append(freq)
        return result


@dataclass
class AnalysisResult:
    video_path: str
    flash_time: float | None
    bip_time: float | None
    offset_ms: float | None
    status: str
    message: str
    details: list[str] = field(default_factory=list)
    used_ffmpeg: bool = False


@dataclass(frozen=True)
class TestVideoResult:
    output_path: str
    expected_offset_ms: float
    audio_embedded: bool
    ffmpeg_path: str | None
    message: str


@dataclass(frozen=True)
class EnvironmentReport:
    python_executable: str
    python_version: str
    working_directory: str
    ffmpeg_path: str | None

    @property
    def ffmpeg_available(self) -> bool:
        return self.ffmpeg_path is not None


@dataclass(frozen=True)
class AudioTrackInfo:
    stream_index: int | None
    audio_stream_order: int | None
    label: str
    codec_name: str | None
    channels: int | None
    sample_rate: int | None
    duration_s: float
    waveform: list[float]
    loaded: bool
    waveform_min: list[float] = field(default_factory=list)
    waveform_max: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class MediaInfoSection:
    title: str
    lines: list[str]


@dataclass(frozen=True)
class TimelineData:
    video_path: str
    duration_s: float
    fps: float
    frame_count: int
    video_duration_s: float
    audio_tracks: list[AudioTrackInfo]
    primary_audio_track_index: int | None
    used_ffmpeg: bool
    media_info_sections: list[MediaInfoSection]

    @property
    def has_audio(self) -> bool:
        return any(track.loaded for track in self.audio_tracks)

    @property
    def audio_duration_s(self) -> float:
        if not self.audio_tracks:
            return self.video_duration_s
        return max(track.duration_s for track in self.audio_tracks)


def _log(logger: Logger | None, message: str) -> None:
    if logger:
        logger(message)


def _backtrack_onset(signal: np.ndarray, peak_index: int, threshold: float) -> int:
    onset_index = peak_index
    while onset_index > 0 and float(signal[onset_index - 1]) >= threshold:
        onset_index -= 1
    return onset_index


def _runtime_search_roots() -> list[Path]:
    roots: list[Path] = []

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        roots.append(Path(bundled_root))

    roots.extend(
        [
            Path.cwd(),
            Path(__file__).resolve().parent,
            Path(sys.executable).resolve().parent,
            Path.home() / "ffmpeg" / "bin",
            Path("C:/ffmpeg/bin"),
            Path("C:/Program Files/ffmpeg/bin"),
            Path("C:/Program Files (x86)/ffmpeg/bin"),
        ]
    )

    unique_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        unique_roots.append(root)

    return unique_roots


def _find_tool_on_path(tool_name: str) -> list[str]:
    candidates: list[str] = []

    try:
        result = subprocess.run(
            ["where", tool_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
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

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(Path(candidate)).lower()
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)

    return unique_candidates


def _is_chocolatey_shim(candidate: str | Path) -> bool:
    normalized = str(candidate).replace("/", "\\").lower()
    return "\\chocolatey\\bin\\" in normalized


def _resolve_chocolatey_binary(tool_name: str) -> str | None:
    candidates = [
        Path("C:/ProgramData/chocolatey/lib/ffmpeg/tools/ffmpeg/bin") / f"{tool_name}.exe",
        Path("C:/ProgramData/chocolatey/lib/ffmpeg/tools/bin") / f"{tool_name}.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def _find_external_tool(tool_name: str) -> str | None:
    for root in _runtime_search_roots():
        for filename in (f"{tool_name}.exe", tool_name):
            candidate = root / filename
            if candidate.exists():
                return str(candidate)

    path_candidates = _find_tool_on_path(tool_name)
    if not path_candidates:
        return None

    preferred_candidates: list[str] = []
    shim_candidates: list[str] = []
    for candidate in path_candidates:
        if _is_chocolatey_shim(candidate):
            resolved_candidate = _resolve_chocolatey_binary(tool_name)
            if resolved_candidate:
                preferred_candidates.append(resolved_candidate)
            shim_candidates.append(candidate)
        else:
            preferred_candidates.append(candidate)

    for candidate in [*preferred_candidates, *shim_candidates]:
        if Path(candidate).exists():
            return str(candidate)

    return None


def is_supported_video_file(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def get_default_output_path(filename: str) -> str:
    downloads_dir = Path.home() / "Downloads"
    base_dir = downloads_dir if downloads_dir.exists() else Path.cwd()
    return str(base_dir / filename)


def find_ffmpeg() -> str | None:
    return _find_external_tool("ffmpeg")


def find_ffprobe() -> str | None:
    ffprobe_path = _find_external_tool("ffprobe")
    if ffprobe_path:
        return ffprobe_path

    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        sibling = Path(ffmpeg_path).with_name("ffprobe.exe")
        if sibling.exists():
            return str(sibling)
        sibling = Path(ffmpeg_path).with_name("ffprobe")
        if sibling.exists():
            return str(sibling)

    return None


def _normalize_audio_samples(samples: np.ndarray) -> np.ndarray:
    audio = np.asarray(samples)

    if audio.ndim > 1:
        audio = audio.astype(np.float32, copy=False).mean(axis=1)

    if np.issubdtype(audio.dtype, np.integer):
        info = np.iinfo(audio.dtype)
        scale = float(max(abs(info.min), info.max))
        if scale > 0:
            return audio.astype(np.float32) / scale
        return audio.astype(np.float32)

    if np.issubdtype(audio.dtype, np.floating):
        return audio.astype(np.float32, copy=False)

    return audio.astype(np.float32)


def _load_wav_samples(wav_file: str, logger: Logger | None = None) -> tuple[np.ndarray | None, int | None]:
    try:
        sample_rate, raw_samples = wav_read(wav_file)
        normalized_samples = _normalize_audio_samples(raw_samples)
        if len(normalized_samples) == 0:
            _log(logger, f"WAV extrait vide : {wav_file}")
            return None, None
        return normalized_samples, int(sample_rate)
    except Exception as exc:
        _log(logger, f"Lecture WAV SciPy en echec ({wav_file}) : {exc}")

    try:
        fallback_samples, fallback_rate = librosa.load(wav_file, sr=None, mono=True)
        if len(fallback_samples) == 0:
            _log(logger, f"WAV extrait vide apres fallback Librosa : {wav_file}")
            return None, None
        return fallback_samples.astype(np.float32, copy=False), fallback_rate
    except Exception as exc:
        _log(logger, f"Lecture WAV Librosa en echec ({wav_file}) : {exc}")
        return None, None


def _parse_ffprobe_float(value: object) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_frame_rate(value: object) -> float | None:
    if value in (None, "", "0/0", "N/A"):
        return None
    try:
        return float(Fraction(str(value)))
    except (ZeroDivisionError, ValueError):
        return None


def _parse_optional_int(value: object) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_file_size(size_bytes: int | None) -> str:
    if size_bytes is None or size_bytes < 0:
        return "inconnu"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    unit_index = 0
    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"


def _format_bitrate(bit_rate: object) -> str | None:
    value = _parse_ffprobe_float(bit_rate)
    if value is None or value <= 0:
        return None
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} Mb/s"
    if value >= 1_000:
        return f"{value / 1_000:.0f} kb/s"
    return f"{value:.0f} b/s"


def _format_resolution(stream: dict[str, object]) -> str | None:
    width = _parse_optional_int(stream.get("width"))
    height = _parse_optional_int(stream.get("height"))
    if width is None or height is None:
        return None
    resolution = f"{width}x{height}"
    sample_aspect = str(stream.get("sample_aspect_ratio", "")).strip()
    display_aspect = str(stream.get("display_aspect_ratio", "")).strip()
    extras: list[str] = []
    if display_aspect and display_aspect != "N/A":
        extras.append(f"DAR {display_aspect}")
    if sample_aspect and sample_aspect != "N/A":
        extras.append(f"SAR {sample_aspect}")
    if extras:
        return f"{resolution} ({', '.join(extras)})"
    return resolution


def _format_disposition(stream: dict[str, object]) -> str | None:
    disposition = stream.get("disposition", {})
    if not isinstance(disposition, dict):
        return None

    active_flags = [key for key, value in disposition.items() if str(value) == "1"]
    if not active_flags:
        return None

    return ", ".join(active_flags)


def probe_media_streams(video_file: str, logger: Logger | None = None) -> dict[str, object] | None:
    ffprobe_path = find_ffprobe()
    if not ffprobe_path:
        _log(logger, "FFprobe introuvable, metadata avancees indisponibles.")
        return None
    _log(logger, f"FFprobe utilise : {ffprobe_path}")

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        video_file,
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            _log(logger, f"FFprobe a echoue : {result.stderr.strip()}")
            return None

        return json.loads(result.stdout)
    except Exception as exc:
        _log(logger, f"Erreur FFprobe : {exc}")
        return None


def _build_audio_track_label(stream: dict[str, object], order_index: int) -> str:
    tags = stream.get("tags", {}) if isinstance(stream.get("tags"), dict) else {}
    title = str(tags.get("title", "")).strip()
    language = str(tags.get("language", "")).strip()
    if language.lower() == "und":
        language = ""
    codec_name = str(stream.get("codec_name", "")).strip()
    channels = stream.get("channels")

    parts = [f"Piste {order_index + 1}"]
    if title:
        parts.append(title)
    if language:
        parts.append(language)
    if codec_name:
        parts.append(codec_name)
    if channels not in (None, "", "N/A"):
        parts.append(f"{channels}ch")
    return " | ".join(parts)


def _collect_audio_streams(video_file: str, logger: Logger | None = None) -> list[dict[str, object]]:
    probe_data = probe_media_streams(video_file, logger=logger)
    if not probe_data:
        return []

    streams = probe_data.get("streams", [])
    if not isinstance(streams, list):
        return []

    audio_streams: list[dict[str, object]] = []
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "audio":
            audio_streams.append(stream)

    return sorted(audio_streams, key=lambda item: int(item.get("index", 0)))


def build_media_info_sections(
    video_file: str,
    probe_data: dict[str, object] | None,
    fps: float,
    frame_count: int,
    video_duration_s: float,
) -> list[MediaInfoSection]:
    path = Path(video_file)
    sections: list[MediaInfoSection] = []

    file_size = path.stat().st_size if path.exists() else None
    general_lines = [
        f"Nom : {path.name}",
        f"Chemin : {path}",
        f"Taille : {_format_file_size(file_size)}",
        f"Duree : {video_duration_s:.3f}s ({video_duration_s * 1000.0:.1f} ms)",
        f"Frame rate : {fps:.3f} fps",
        f"Nombre de frames : {frame_count}",
    ]

    if probe_data and isinstance(probe_data.get("format"), dict):
        format_data = probe_data["format"]
        format_name = str(format_data.get("format_name", "")).strip()
        format_long_name = str(format_data.get("format_long_name", "")).strip()
        bit_rate = _format_bitrate(format_data.get("bit_rate"))
        start_time = _parse_ffprobe_float(format_data.get("start_time"))
        probe_score = format_data.get("probe_score")

        if format_name:
            label = format_long_name or format_name
            general_lines.append(f"Conteneur : {label}")
        if bit_rate:
            general_lines.append(f"Bitrate global : {bit_rate}")
        if start_time is not None:
            general_lines.append(f"Start time : {start_time:.3f}s")
        if probe_score not in (None, "", "N/A"):
            general_lines.append(f"Probe score : {probe_score}")

        tags = format_data.get("tags", {})
        if isinstance(tags, dict):
            for tag_key in ("title", "encoder", "creation_time", "date"):
                tag_value = str(tags.get(tag_key, "")).strip()
                if tag_value:
                    general_lines.append(f"{tag_key} : {tag_value}")

    sections.append(MediaInfoSection(title="General", lines=general_lines))

    streams = probe_data.get("streams", []) if probe_data and isinstance(probe_data.get("streams"), list) else []
    video_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    for order_index, stream in enumerate(video_streams):
        lines = [f"Stream index : {stream.get('index', order_index)}"]
        codec_name = str(stream.get("codec_name", "")).strip()
        codec_long_name = str(stream.get("codec_long_name", "")).strip()
        if codec_name or codec_long_name:
            lines.append(f"Codec : {codec_long_name or codec_name}")

        profile = str(stream.get("profile", "")).strip()
        if profile:
            lines.append(f"Profile : {profile}")

        resolution = _format_resolution(stream)
        if resolution:
            lines.append(f"Resolution : {resolution}")

        pixel_format = str(stream.get("pix_fmt", "")).strip()
        if pixel_format:
            lines.append(f"Pixel format : {pixel_format}")

        field_order = str(stream.get("field_order", "")).strip()
        if field_order and field_order != "unknown":
            lines.append(f"Field order : {field_order}")

        stream_fps = _parse_frame_rate(stream.get("avg_frame_rate")) or _parse_frame_rate(stream.get("r_frame_rate"))
        if stream_fps:
            lines.append(f"Frame rate : {stream_fps:.3f} fps")

        nb_frames = _parse_optional_int(stream.get("nb_frames"))
        if nb_frames is not None:
            lines.append(f"Frames : {nb_frames}")

        stream_duration = _parse_ffprobe_float(stream.get("duration"))
        if stream_duration is not None:
            lines.append(f"Duree : {stream_duration:.3f}s")

        bit_rate = _format_bitrate(stream.get("bit_rate"))
        if bit_rate:
            lines.append(f"Bitrate : {bit_rate}")

        for key, label in (
            ("color_range", "Color range"),
            ("color_space", "Color space"),
            ("color_transfer", "Color transfer"),
            ("color_primaries", "Color primaries"),
        ):
            value = str(stream.get(key, "")).strip()
            if value and value != "unknown":
                lines.append(f"{label} : {value}")

        disposition = _format_disposition(stream)
        if disposition:
            lines.append(f"Disposition : {disposition}")

        sections.append(MediaInfoSection(title=f"Video {order_index + 1}", lines=lines))

    audio_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    for order_index, stream in enumerate(audio_streams):
        lines = [f"Stream index : {stream.get('index', order_index)}"]
        label = _build_audio_track_label(stream, order_index)
        lines.append(f"Nom logique : {label}")

        codec_name = str(stream.get("codec_name", "")).strip()
        codec_long_name = str(stream.get("codec_long_name", "")).strip()
        if codec_name or codec_long_name:
            lines.append(f"Codec : {codec_long_name or codec_name}")

        profile = str(stream.get("profile", "")).strip()
        if profile:
            lines.append(f"Profile : {profile}")

        sample_rate = _parse_optional_int(stream.get("sample_rate"))
        if sample_rate is not None:
            lines.append(f"Sample rate : {sample_rate} Hz")

        channels = _parse_optional_int(stream.get("channels"))
        if channels is not None:
            lines.append(f"Canaux : {channels}")

        channel_layout = str(stream.get("channel_layout", "")).strip()
        if channel_layout:
            lines.append(f"Layout : {channel_layout}")

        stream_duration = _parse_ffprobe_float(stream.get("duration"))
        if stream_duration is not None:
            lines.append(f"Duree : {stream_duration:.3f}s")

        bit_rate = _format_bitrate(stream.get("bit_rate"))
        if bit_rate:
            lines.append(f"Bitrate : {bit_rate}")

        disposition = _format_disposition(stream)
        if disposition:
            lines.append(f"Disposition : {disposition}")

        tags = stream.get("tags", {})
        if isinstance(tags, dict):
            for tag_key in ("title", "language", "handler_name"):
                tag_value = str(tags.get(tag_key, "")).strip()
                if tag_value:
                    lines.append(f"{tag_key} : {tag_value}")

        sections.append(MediaInfoSection(title=f"Audio {order_index + 1}", lines=lines))

    if not video_streams and not audio_streams:
        sections.append(MediaInfoSection(title="Streams", lines=["Aucune metadata stream detaillee disponible."]))

    return sections


def check_environment() -> EnvironmentReport:
    return EnvironmentReport(
        python_executable=sys.executable,
        python_version=sys.version.split()[0],
        working_directory=os.getcwd(),
        ffmpeg_path=find_ffmpeg(),
    )


def format_environment_report(report: EnvironmentReport) -> list[str]:
    ffmpeg_message = report.ffmpeg_path if report.ffmpeg_path else "non trouve (mode degrade)"
    return [
        f"Python : {report.python_version}",
        f"Executable : {report.python_executable}",
        f"Repertoire courant : {report.working_directory}",
        f"FFmpeg : {ffmpeg_message}",
    ]


def load_audio_samples(
    video_file: str,
    stream_index: int | None = None,
    audio_stream_order: int | None = None,
    logger: Logger | None = None,
    ffmpeg_audio_filter: str | None = None,
    allow_generic_fallback: bool = True,
) -> tuple[np.ndarray | None, int | None, bool]:
    ffmpeg_path = find_ffmpeg()

    if ffmpeg_path:
        _log(logger, f"FFmpeg utilise : {ffmpeg_path}")
        extraction_strategies: list[tuple[str, list[str]]] = []
        if audio_stream_order is not None:
            extraction_strategies.append((f"piste audio #{audio_stream_order + 1}", ["-map", f"0:a:{audio_stream_order}"]))
        if stream_index is not None:
            extraction_strategies.append((f"stream global #{stream_index}", ["-map", f"0:{stream_index}"]))
        if allow_generic_fallback:
            extraction_strategies.append(("premiere piste audio detectee", ["-map", "0:a:0?"]))
            extraction_strategies.append(("selection audio par defaut", []))

        seen_signatures: set[tuple[str, ...]] = set()
        for strategy_label, map_args in extraction_strategies:
            signature = tuple(map_args)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            temp_audio_file: str | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_audio_file = temp_file.name

                command = [
                    ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    video_file,
                    "-vn",
                    *map_args,
                    "-ac",
                    "1",
                    "-ar",
                    "44100",
                ]
                if ffmpeg_audio_filter:
                    command.extend(["-af", ffmpeg_audio_filter])
                command.extend(["-y", temp_audio_file])

                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode == 0:
                    y, sr = _load_wav_samples(temp_audio_file, logger=logger)
                    if y is not None and sr is not None and len(y) > 0:
                        _log(logger, f"Audio charge via FFmpeg ({strategy_label}).")
                        return y, sr, True
                    _log(logger, f"Audio extrait via FFmpeg mais vide ou illisible ({strategy_label}).")
                else:
                    error_message = result.stderr.strip() or "erreur FFmpeg non detaillee"
                    _log(logger, f"Extraction audio FFmpeg en echec ({strategy_label}) : {error_message}")
            except Exception as exc:
                _log(logger, f"Erreur d'extraction audio FFmpeg ({strategy_label}) : {exc}")
            finally:
                if temp_audio_file and os.path.exists(temp_audio_file):
                    try:
                        os.unlink(temp_audio_file)
                    except OSError:
                        pass

    try:
        y, sr = librosa.load(video_file, sr=None, mono=True)
        if len(y) > 0:
            return y, sr, False
        _log(logger, "Librosa a charge un signal audio vide.")
    except Exception as exc:
        _log(logger, f"Chargement audio direct en echec : {exc}")

    return None, None, bool(ffmpeg_path)


def create_waveform_envelope(samples: np.ndarray, points: int = 6000) -> tuple[list[float], list[float], list[float]]:
    if len(samples) == 0 or points <= 0:
        return [], [], []

    if len(samples) == 1:
        sample_value = float(np.clip(samples[0], -1.0, 1.0))
        waveform_min = [min(sample_value, 0.0) for _ in range(points)]
        waveform_max = [max(sample_value, 0.0) for _ in range(points)]
        waveform_peak = [max(abs(sample_value), 0.0) for _ in range(points)]
        return waveform_min, waveform_max, waveform_peak

    boundaries = np.linspace(0, len(samples), points + 1, dtype=int)
    waveform_min_raw: list[float] = []
    waveform_max_raw: list[float] = []

    for index in range(points):
        start = boundaries[index]
        end = boundaries[index + 1]
        if end <= start:
            end = min(len(samples), start + 1)
        segment = samples[start:end]
        if len(segment) > 0:
            waveform_min_raw.append(float(np.min(segment)))
            waveform_max_raw.append(float(np.max(segment)))
        else:
            waveform_min_raw.append(0.0)
            waveform_max_raw.append(0.0)

    max_abs_value = max(
        max((abs(value) for value in waveform_min_raw), default=0.0),
        max((abs(value) for value in waveform_max_raw), default=0.0),
    )
    if max_abs_value <= 0:
        zeros = [0.0 for _ in waveform_min_raw]
        return zeros, zeros.copy(), zeros.copy()

    waveform_min = [value / max_abs_value for value in waveform_min_raw]
    waveform_max = [value / max_abs_value for value in waveform_max_raw]
    waveform_peak = [max(abs(low), abs(high)) for low, high in zip(waveform_min, waveform_max)]
    return waveform_min, waveform_max, waveform_peak


def create_waveform_preview(samples: np.ndarray, points: int = 6000) -> list[float]:
    _, _, waveform_peak = create_waveform_envelope(samples, points=points)
    return waveform_peak


def build_timeline_data(
    video_file: str,
    waveform_points: int = 6000,
    logger: Logger | None = None,
) -> TimelineData:
    normalized_path = str(Path(video_file))
    if not os.path.exists(normalized_path):
        raise FileNotFoundError(f"Fichier introuvable : {normalized_path}")

    cap = cv2.VideoCapture(normalized_path)
    if not cap.isOpened():
        raise ValueError(f"Impossible d'ouvrir la video : {normalized_path}")

    capture_fps = float(cap.get(cv2.CAP_PROP_FPS))
    capture_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    probe_data = probe_media_streams(normalized_path, logger=logger)
    video_stream = None
    format_duration_s = None
    if probe_data:
        streams = probe_data.get("streams", [])
        if isinstance(streams, list):
            for stream in streams:
                if isinstance(stream, dict) and stream.get("codec_type") == "video":
                    video_stream = stream
                    break

        format_data = probe_data.get("format", {})
        if isinstance(format_data, dict):
            format_duration_s = _parse_ffprobe_float(format_data.get("duration"))

    fps = None
    frame_count = None
    video_duration_s = None

    if isinstance(video_stream, dict):
        fps = _parse_frame_rate(video_stream.get("avg_frame_rate")) or _parse_frame_rate(video_stream.get("r_frame_rate"))
        frame_count_value = video_stream.get("nb_frames")
        if frame_count_value not in (None, "", "N/A"):
            try:
                frame_count = int(frame_count_value)
            except (TypeError, ValueError):
                frame_count = None
        video_duration_s = _parse_ffprobe_float(video_stream.get("duration"))

    if fps is None or fps <= 0:
        fps = capture_fps if capture_fps > 0 else 30.0
    if frame_count is None or frame_count <= 0:
        frame_count = capture_frame_count if capture_frame_count > 0 else 0
    if video_duration_s is None or video_duration_s <= 0:
        if frame_count > 0 and fps > 0:
            video_duration_s = frame_count / fps
        elif format_duration_s is not None and format_duration_s > 0:
            video_duration_s = format_duration_s
        else:
            video_duration_s = 0.0

    duration_s = video_duration_s
    _log(logger, f"Timeline video : {frame_count} frames a {fps:.3f} fps")

    audio_tracks: list[AudioTrackInfo] = []
    used_ffmpeg = False
    audio_streams = _collect_audio_streams(normalized_path, logger=logger)
    if audio_streams:
        _log(logger, f"{len(audio_streams)} piste(s) audio detectee(s).")
        for order_index, stream in enumerate(audio_streams):
            stream_index = int(stream.get("index", order_index))
            audio_samples, sample_rate, stream_used_ffmpeg = load_audio_samples(
                normalized_path,
                stream_index=stream_index,
                audio_stream_order=order_index,
                logger=logger,
            )
            used_ffmpeg = used_ffmpeg or stream_used_ffmpeg

            metadata_duration = _parse_ffprobe_float(stream.get("duration")) or 0.0
            if audio_samples is not None and sample_rate:
                waveform_min, waveform_max, waveform = create_waveform_envelope(audio_samples, points=waveform_points)
                duration_track_s = len(audio_samples) / sample_rate
                duration_s = max(duration_s, duration_track_s)
                audio_tracks.append(
                    AudioTrackInfo(
                        stream_index=stream_index,
                        audio_stream_order=order_index,
                        label=_build_audio_track_label(stream, order_index),
                        codec_name=str(stream.get("codec_name", "")).strip() or None,
                        channels=int(stream.get("channels")) if stream.get("channels") not in (None, "", "N/A") else None,
                        sample_rate=sample_rate,
                        duration_s=max(duration_track_s, metadata_duration),
                        waveform=waveform,
                        waveform_min=waveform_min,
                        waveform_max=waveform_max,
                        loaded=True,
                    )
                )
                _log(logger, f"Piste audio {order_index + 1} chargee ({duration_track_s:.3f}s)")
            else:
                audio_tracks.append(
                    AudioTrackInfo(
                        stream_index=stream_index,
                        audio_stream_order=order_index,
                        label=_build_audio_track_label(stream, order_index),
                        codec_name=str(stream.get("codec_name", "")).strip() or None,
                        channels=int(stream.get("channels")) if stream.get("channels") not in (None, "", "N/A") else None,
                        sample_rate=None,
                        duration_s=max(metadata_duration, duration_s),
                        waveform=[0.0 for _ in range(waveform_points)],
                        waveform_min=[0.0 for _ in range(waveform_points)],
                        waveform_max=[0.0 for _ in range(waveform_points)],
                        loaded=False,
                    )
                )
                _log(logger, f"Piste audio {order_index + 1} detectee mais non chargee.")
    else:
        audio_samples, sample_rate, used_ffmpeg = load_audio_samples(normalized_path, logger=logger)
        if audio_samples is not None and sample_rate:
            waveform_min, waveform_max, waveform = create_waveform_envelope(audio_samples, points=waveform_points)
            audio_duration_s = len(audio_samples) / sample_rate
            duration_s = max(duration_s, audio_duration_s)
            audio_tracks.append(
                AudioTrackInfo(
                    stream_index=None,
                    audio_stream_order=0,
                    label="Piste audio principale",
                    codec_name=None,
                    channels=1,
                    sample_rate=sample_rate,
                    duration_s=audio_duration_s,
                    waveform=waveform,
                    waveform_min=waveform_min,
                    waveform_max=waveform_max,
                    loaded=True,
                )
            )
            _log(logger, f"Timeline audio fallback : {audio_duration_s:.3f}s chargees")
        else:
            _log(logger, "FFprobe n'a detecte aucune piste audio, tentative de fallback progressif.")
            fallback_success = False
            max_fallback_tracks = 8
            for order_index in range(max_fallback_tracks):
                audio_samples, sample_rate, stream_used_ffmpeg = load_audio_samples(
                    normalized_path,
                    audio_stream_order=order_index,
                    logger=logger,
                    allow_generic_fallback=False,
                )
                used_ffmpeg = used_ffmpeg or stream_used_ffmpeg
                if audio_samples is None or sample_rate is None:
                    if fallback_success:
                        break
                    continue

                fallback_success = True
                waveform_min, waveform_max, waveform = create_waveform_envelope(audio_samples, points=waveform_points)
                audio_duration_s = len(audio_samples) / sample_rate
                duration_s = max(duration_s, audio_duration_s)
                audio_tracks.append(
                    AudioTrackInfo(
                        stream_index=None,
                        audio_stream_order=order_index,
                        label=f"Piste audio {order_index + 1} (fallback FFmpeg)",
                        codec_name=None,
                        channels=1,
                        sample_rate=sample_rate,
                        duration_s=audio_duration_s,
                        waveform=waveform,
                        waveform_min=waveform_min,
                        waveform_max=waveform_max,
                        loaded=True,
                    )
                )
                _log(logger, f"Piste audio fallback {order_index + 1} chargee ({audio_duration_s:.3f}s)")

            if not fallback_success:
                audio_samples, sample_rate, stream_used_ffmpeg = load_audio_samples(
                    normalized_path,
                    logger=logger,
                    allow_generic_fallback=True,
                )
                used_ffmpeg = used_ffmpeg or stream_used_ffmpeg
                if audio_samples is not None and sample_rate:
                    waveform_min, waveform_max, waveform = create_waveform_envelope(audio_samples, points=waveform_points)
                    audio_duration_s = len(audio_samples) / sample_rate
                    duration_s = max(duration_s, audio_duration_s)
                    audio_tracks.append(
                        AudioTrackInfo(
                            stream_index=None,
                            audio_stream_order=0,
                            label="Piste audio principale (fallback)",
                            codec_name=None,
                            channels=1,
                            sample_rate=sample_rate,
                            duration_s=audio_duration_s,
                            waveform=waveform,
                            waveform_min=waveform_min,
                            waveform_max=waveform_max,
                            loaded=True,
                        )
                    )
                    _log(logger, f"Timeline audio fallback generic : {audio_duration_s:.3f}s chargees")
                else:
                    _log(logger, "Aucune piste audio exploitable pour la timeline.")

    primary_audio_track_index = None
    for index, track in enumerate(audio_tracks):
        if track.loaded:
            primary_audio_track_index = index
            break

    media_info_sections = build_media_info_sections(
        normalized_path,
        probe_data,
        fps=fps,
        frame_count=frame_count,
        video_duration_s=video_duration_s,
    )

    return TimelineData(
        video_path=normalized_path,
        duration_s=duration_s,
        fps=fps,
        frame_count=frame_count,
        video_duration_s=video_duration_s,
        audio_tracks=audio_tracks,
        primary_audio_track_index=primary_audio_track_index,
        used_ffmpeg=used_ffmpeg,
        media_info_sections=media_info_sections,
    )


def detect_flash(video_file: str, config: DetectionConfig | None = None, logger: Logger | None = None) -> float | None:
    config = config or DetectionConfig()
    cap = cv2.VideoCapture(video_file)
    if not cap.isOpened():
        _log(logger, "Impossible d'ouvrir la video pour la detection du flash.")
        return None

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 30.0

    baseline_capture = cv2.VideoCapture(video_file)
    baseline_frames: list[dict[str, float]] = []
    for _ in range(config.baseline_frames):
        ret, frame = baseline_capture.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        center_region = gray[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4]

        baseline_frames.append(
            {
                "full": float(gray.mean()),
                "center": float(center_region.mean()),
                "max": float(gray.max()),
            }
        )
    baseline_capture.release()

    if not baseline_frames:
        cap.release()
        _log(logger, "Aucune frame exploitable pour calculer la luminosite de base.")
        return None

    baseline_full = float(np.mean([frame["full"] for frame in baseline_frames]))
    baseline_center = float(np.mean([frame["center"] for frame in baseline_frames]))
    baseline_max = float(np.mean([frame["max"] for frame in baseline_frames]))
    baseline_std = float(np.std([frame["full"] for frame in baseline_frames]))

    adaptive_threshold_full = baseline_full + max(20.0, baseline_std * 2.0)
    adaptive_threshold_center = baseline_center + max(25.0, baseline_std * 2.5)
    min_increase_factor = 1.3
    min_flash_score = max(0.3, min(2.0, baseline_std / 50.0))

    _log(
        logger,
        (
            "Baseline flash : "
            f"full={baseline_full:.1f}, center={baseline_center:.1f}, "
            f"max={baseline_max:.1f}, std={baseline_std:.1f}"
        ),
    )

    frame_index = 0
    min_frame_index = int(round(config.min_analysis_start_s * fps))
    best_flash_time: float | None = None
    best_flash_score = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        center_region = gray[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4]

        full_brightness = float(gray.mean())
        center_brightness = float(center_region.mean())
        max_brightness = float(gray.max())

        if frame_index < min_frame_index:
            frame_index += 1
            continue

        flash_score = 0.0

        if full_brightness > adaptive_threshold_full and full_brightness > baseline_full * min_increase_factor:
            denominator = baseline_full if baseline_full > 0 else 1.0
            flash_score += (full_brightness - baseline_full) / denominator

        if center_brightness > adaptive_threshold_center and center_brightness > baseline_center * min_increase_factor:
            denominator = baseline_center if baseline_center > 0 else 1.0
            flash_score += 2.0 * (center_brightness - baseline_center) / denominator

        if max_brightness > baseline_max * 1.2:
            flash_score += (max_brightness - baseline_max) / 255.0

        if flash_score > min_flash_score and flash_score > best_flash_score:
            best_flash_time = frame_index / fps
            best_flash_score = flash_score
            _log(logger, f"Flash candidat a {best_flash_time:.3f}s (score={flash_score:.2f})")

        frame_index += 1

    cap.release()

    if best_flash_time is not None:
        _log(logger, f"Flash selectionne a {best_flash_time:.3f}s (score={best_flash_score:.2f})")
    else:
        _log(logger, "Aucun flash fiable detecte.")

    return best_flash_time


def _detect_bip_in_samples(
    samples: np.ndarray,
    sample_rate: int,
    config: DetectionConfig,
    logger: Logger | None = None,
    stream_label: str | None = None,
) -> tuple[float | None, float]:
    if len(samples) == 0:
        return None, 0.0

    hop_length = 256
    frame_length = 2048
    stft = librosa.stft(samples, hop_length=hop_length, n_fft=frame_length)
    magnitude = np.abs(stft)
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=frame_length)

    best_bip_time: float | None = None
    best_score = 0.0
    prefix = f"{stream_label} - " if stream_label else ""

    for test_freq in config.all_target_frequencies():
        freq_mask = (freqs >= test_freq - config.freq_tolerance) & (freqs <= test_freq + config.freq_tolerance)
        if not np.any(freq_mask):
            continue

        target_energy = np.sum(magnitude[freq_mask, :], axis=0)
        if len(target_energy) == 0:
            continue

        window_size = max(1, int((sample_rate / hop_length) * 0.05))
        if window_size > 1 and len(target_energy) > window_size:
            kernel = np.ones(window_size, dtype=np.float32) / window_size
            target_energy_smooth = np.convolve(target_energy, kernel, mode="same")
        else:
            target_energy_smooth = target_energy

        energy_median = float(np.median(target_energy_smooth))
        energy_std = float(np.std(target_energy_smooth))
        adaptive_threshold = max(
            energy_median + 2.0 * energy_std,
            float(np.max(target_energy_smooth)) * 0.25,
            energy_median * 3.0,
        )

        peaks, _ = find_peaks(
            target_energy_smooth,
            height=adaptive_threshold,
            distance=max(10, int((sample_rate / hop_length) * 0.2)),
            width=3,
            prominence=max(energy_std * 0.5, energy_median * 0.2),
        )

        for peak_frame in peaks:
            peak_height = float(target_energy_smooth[peak_frame])
            onset_threshold = max(energy_median * 2.0, peak_height * 0.2)
            onset_frame = _backtrack_onset(target_energy_smooth, int(peak_frame), onset_threshold)
            candidate_time = float(librosa.frames_to_time(onset_frame, sr=sample_rate, hop_length=hop_length))
            peak_time = float(librosa.frames_to_time(peak_frame, sr=sample_rate, hop_length=hop_length))

            if candidate_time < config.min_analysis_start_s:
                continue

            peak_score = peak_height / (energy_median + 1e-6)
            peak_score = min(peak_score, 1000.0)

            if peak_score > best_score and peak_score > 5.0:
                best_score = peak_score
                best_bip_time = candidate_time
                _log(
                    logger,
                    (
                        f"{prefix}Bip candidat a {test_freq}Hz : debut~{best_bip_time:.3f}s, "
                        f"pic~{peak_time:.3f}s (score={peak_score:.2f})"
                    ),
                )

    return best_bip_time, best_score


def detect_bip_with_ffmpeg(
    video_file: str,
    config: DetectionConfig | None = None,
    logger: Logger | None = None,
) -> tuple[float | None, bool]:
    config = config or DetectionConfig()
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        _log(logger, "FFmpeg non trouve, bascule vers la methode audio simplifiee.")
        return None, False

    best_bip_time: float | None = None
    best_score = 0.0
    audio_streams = _collect_audio_streams(video_file, logger=logger)

    if not audio_streams:
        audio_samples, sample_rate, used_ffmpeg = load_audio_samples(
            video_file,
            logger=logger,
            ffmpeg_audio_filter="highpass=f=200,lowpass=f=8000",
        )
        if audio_samples is None or sample_rate is None:
            _log(logger, "Aucun audio exploitable pour la detection via FFmpeg.")
            return None, used_ffmpeg

        best_bip_time, best_score = _detect_bip_in_samples(audio_samples, sample_rate, config, logger=logger)
    else:
        for order_index, stream in enumerate(audio_streams):
            stream_index = int(stream.get("index", order_index))
            stream_label = _build_audio_track_label(stream, order_index)
            audio_samples, sample_rate, _ = load_audio_samples(
                video_file,
                stream_index=stream_index,
                audio_stream_order=order_index,
                logger=logger,
                ffmpeg_audio_filter="highpass=f=200,lowpass=f=8000",
            )
            if audio_samples is None or sample_rate is None:
                continue

            candidate_time, candidate_score = _detect_bip_in_samples(
                audio_samples,
                sample_rate,
                config,
                logger=logger,
                stream_label=stream_label,
            )
            if candidate_time is not None and candidate_score > best_score:
                best_bip_time = candidate_time
                best_score = candidate_score

    if best_bip_time is not None:
        _log(logger, f"Bip selectionne a {best_bip_time:.3f}s (score={best_score:.2f})")
    else:
        _log(logger, "Aucun bip fiable detecte via FFmpeg.")

    return best_bip_time, True


def detect_bip_simple(
    video_file: str,
    config: DetectionConfig | None = None,
    logger: Logger | None = None,
) -> float | None:
    config = config or DetectionConfig()
    try:
        y, sr = librosa.load(video_file, sr=None, mono=True)
        if len(y) == 0:
            _log(logger, "L'audio charge directement est vide.")
            return None

        energy = np.abs(y)
        window_size = max(1, int(sr * 0.01))
        if len(energy) > window_size:
            kernel = np.ones(window_size, dtype=np.float32) / window_size
            energy_smooth = np.convolve(energy, kernel, mode="same")
        else:
            energy_smooth = energy

        threshold = max(float(np.max(energy_smooth)) * 0.5, float(np.median(energy_smooth)) * 4.0)
        peaks, _ = find_peaks(
            energy_smooth,
            height=threshold,
            distance=max(1, int(sr * 0.1)),
        )

        for peak_index in peaks:
            peak_height = float(energy_smooth[peak_index])
            onset_threshold = max(float(np.median(energy_smooth)) * 2.0, peak_height * 0.2)
            onset_index = _backtrack_onset(energy_smooth, int(peak_index), onset_threshold)
            candidate_time = onset_index / sr
            if candidate_time < config.min_analysis_start_s:
                continue

            _log(logger, f"Bip detecte avec la methode simple a {candidate_time:.3f}s")
            return float(candidate_time)

        _log(logger, "La methode simple n'a trouve aucun bip exploitable.")
        return None
    except Exception as exc:
        _log(logger, f"Erreur dans detect_bip_simple : {exc}")
        return None


def detect_bip(
    video_file: str,
    config: DetectionConfig | None = None,
    logger: Logger | None = None,
) -> tuple[float | None, bool]:
    config = config or DetectionConfig()
    bip_time, used_ffmpeg = detect_bip_with_ffmpeg(video_file, config=config, logger=logger)
    if bip_time is not None:
        return bip_time, used_ffmpeg

    _log(logger, "Bascule vers la detection audio simplifiee.")
    return detect_bip_simple(video_file, config=config, logger=logger), used_ffmpeg


def analyze_video(
    video_file: str,
    config: DetectionConfig | None = None,
    logger: Logger | None = None,
) -> AnalysisResult:
    config = config or DetectionConfig()
    debug_messages: list[str] = []

    def collector(message: str) -> None:
        debug_messages.append(message)
        _log(logger, message)

    normalized_path = str(Path(video_file))
    if not os.path.exists(normalized_path):
        message = "Le fichier video selectionne est introuvable."
        collector(message)
        return AnalysisResult(
            video_path=normalized_path,
            flash_time=None,
            bip_time=None,
            offset_ms=None,
            status="missing_file",
            message=message,
            details=debug_messages,
            used_ffmpeg=False,
        )

    collector(f"Analyse de {normalized_path}")
    flash_time = detect_flash(normalized_path, config=config, logger=collector)
    bip_time, used_ffmpeg = detect_bip(normalized_path, config=config, logger=collector)

    if flash_time is None:
        return AnalysisResult(
            video_path=normalized_path,
            flash_time=None,
            bip_time=bip_time,
            offset_ms=None,
            status="flash_missing",
            message="Flash non detecte. Verifie l'eclairage et le contraste.",
            details=debug_messages,
            used_ffmpeg=used_ffmpeg,
        )

    if bip_time is None:
        return AnalysisResult(
            video_path=normalized_path,
            flash_time=flash_time,
            bip_time=None,
            offset_ms=None,
            status="bip_missing",
            message="Bip non detecte. Verifie le volume, la frequence et la piste audio.",
            details=debug_messages,
            used_ffmpeg=used_ffmpeg,
        )

    offset_ms = (bip_time - flash_time) * 1000.0
    if abs(offset_ms) <= config.sync_tolerance_ms:
        status = "synced"
        message = f"Audio et video synchrones ({offset_ms:+.1f} ms)."
    elif offset_ms > 0:
        status = "audio_late"
        message = f"Audio en retard de {abs(offset_ms):.1f} ms."
    else:
        status = "audio_early"
        message = f"Audio en avance de {abs(offset_ms):.1f} ms."

    collector(
        (
            "Resultat final : "
            f"flash={flash_time:.3f}s, bip={bip_time:.3f}s, "
            f"ecart={offset_ms:+.1f} ms"
        )
    )
    return AnalysisResult(
        video_path=normalized_path,
        flash_time=flash_time,
        bip_time=bip_time,
        offset_ms=offset_ms,
        status=status,
        message=message,
        details=debug_messages,
        used_ffmpeg=used_ffmpeg,
    )


def create_test_audio(
    duration: float,
    bip_time: float,
    sample_rate: int = 44100,
    frequency: int = 1000,
) -> str:
    samples = int(duration * sample_rate)
    audio = np.zeros(samples, dtype=np.float32)

    bip_duration = 0.1
    bip_samples = int(bip_duration * sample_rate)
    bip_start = int(bip_time * sample_rate)

    if bip_start + bip_samples <= samples:
        t = np.linspace(0.0, bip_duration, bip_samples, endpoint=False)
        envelope = np.sin(np.pi * t / bip_duration)
        bip = 0.5 * envelope * np.sin(2.0 * np.pi * frequency * t)
        audio[bip_start : bip_start + bip_samples] = bip

    temp_audio_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    audio_path = temp_audio_file.name
    temp_audio_file.close()

    audio_int16 = (audio * 32767).astype(np.int16)
    wav_write(audio_path, sample_rate, audio_int16)
    return audio_path


def create_test_video(
    output_path: str = "test_video.mp4",
    duration: float = 5.0,
    flash_time: float = 2.0,
    bip_time: float = 2.1,
    fps: int = 30,
    logger: Logger | None = None,
) -> TestVideoResult:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    width, height = 1280, 720
    total_frames = int(duration * fps)
    flash_frame = int(flash_time * fps)
    expected_offset_ms = (bip_time - flash_time) * 1000.0

    temp_video_path: str | None = None
    audio_path: str | None = None

    try:
        temp_video_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_video_path = temp_video_file.name
        temp_video_file.close()

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_writer = cv2.VideoWriter(temp_video_path, fourcc, fps, (width, height))

        _log(logger, f"Creation de la video de test : {output}")
        _log(logger, f"Flash a {flash_time:.3f}s | Bip a {bip_time:.3f}s | Ecart attendu {expected_offset_ms:+.1f} ms")

        for frame_num in range(total_frames):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            current_time = frame_num / fps
            cv2.putText(
                frame,
                f"Time: {current_time:.2f}s",
                (50, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 255),
                2,
            )

            if frame_num == flash_frame:
                frame = np.full((height, width, 3), 255, dtype=np.uint8)
                cv2.putText(
                    frame,
                    "FLASH!",
                    (width // 2 - 100, height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    3,
                    (0, 0, 0),
                    4,
                )
            elif abs(frame_num - flash_frame) <= 2:
                brightness = 100 - abs(frame_num - flash_frame) * 30
                frame = np.full((height, width, 3), brightness, dtype=np.uint8)
                cv2.putText(
                    frame,
                    f"Time: {current_time:.2f}s",
                    (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 255, 255),
                    2,
                )

            video_writer.write(frame)

        video_writer.release()

        audio_path = create_test_audio(duration=duration, bip_time=bip_time)
        ffmpeg_path = find_ffmpeg()

        if not ffmpeg_path:
            shutil.copy2(temp_video_path, output)
            message = "Video creee sans audio integre, FFmpeg est introuvable."
            _log(logger, message)
            return TestVideoResult(
                output_path=str(output),
                expected_offset_ms=expected_offset_ms,
                audio_embedded=False,
                ffmpeg_path=None,
                message=message,
            )

        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            temp_video_path,
            "-i",
            audio_path,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            shutil.copy2(temp_video_path, output)
            message = "FFmpeg a echoue, la video de test a ete creee sans audio."
            _log(logger, f"{message} Details : {result.stderr.strip()}")
            return TestVideoResult(
                output_path=str(output),
                expected_offset_ms=expected_offset_ms,
                audio_embedded=False,
                ffmpeg_path=ffmpeg_path,
                message=message,
            )

        message = f"Video de test creee avec succes ({expected_offset_ms:+.1f} ms attendus)."
        _log(logger, message)
        return TestVideoResult(
            output_path=str(output),
            expected_offset_ms=expected_offset_ms,
            audio_embedded=True,
            ffmpeg_path=ffmpeg_path,
            message=message,
        )
    finally:
        for temp_path in (temp_video_path, audio_path):
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
