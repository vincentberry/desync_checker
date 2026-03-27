import sys
import time
from pathlib import Path

import cv2
from PyQt6 import QtCore, QtGui, QtMultimedia, QtWidgets

from desync_metadata import APP_CREATOR, APP_GITHUB_URL, APP_LICENSE_NAME, APP_NAME, APP_VERSION
from desync_core import (
    analyze_video,
    build_timeline_data,
    check_environment,
    create_test_video,
    format_environment_report,
    get_default_output_path,
    is_supported_video_file,
)


STATUS_STYLES = {
    "synced": "color: #1f7a1f; font-weight: bold;",
    "audio_late": "color: #b36b00; font-weight: bold;",
    "audio_early": "color: #b00020; font-weight: bold;",
    "flash_missing": "color: #8a4500; font-weight: bold;",
    "bip_missing": "color: #8a4500; font-weight: bold;",
    "missing_file": "color: #8a0000; font-weight: bold;",
}


def _find_asset(relative_path: str) -> str | None:
    candidate_roots: list[Path] = []

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        candidate_roots.append(Path(bundled_root))

    candidate_roots.extend(
        [
            Path(__file__).resolve().parent,
            Path(sys.executable).resolve().parent,
            Path.cwd(),
        ]
    )

    seen: set[str] = set()
    for root in candidate_roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        candidate = root / relative_path
        if candidate.exists():
            return str(candidate)

    return None


def _load_app_icon() -> QtGui.QIcon:
    for relative_path in ("assets/desync_checker.ico", "assets/desync_checker_logo.png"):
        asset_path = _find_asset(relative_path)
        if not asset_path:
            continue
        icon = QtGui.QIcon(asset_path)
        if not icon.isNull():
            return icon
    return QtGui.QIcon()


def _load_logo_pixmap(target_size: int = 96) -> QtGui.QPixmap | None:
    asset_path = _find_asset("assets/desync_checker_logo.png")
    if not asset_path:
        return None

    pixmap = QtGui.QPixmap(asset_path)
    if pixmap.isNull():
        return None

    return pixmap.scaled(
        target_size,
        target_size,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )


class AnalysisWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object)

    def __init__(self, video_path: str):
        super().__init__()
        self.video_path = video_path

    def run(self) -> None:
        result = analyze_video(self.video_path, logger=self.progress.emit)
        self.finished.emit(result)


class TestVideoWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object)

    def __init__(self, output_path: str, offset_ms: float):
        super().__init__()
        self.output_path = output_path
        self.offset_ms = offset_ms

    def run(self) -> None:
        flash_time = 2.0
        bip_time = flash_time + (self.offset_ms / 1000.0)
        result = create_test_video(
            output_path=self.output_path,
            duration=5.0,
            flash_time=flash_time,
            bip_time=bip_time,
            logger=self.progress.emit,
        )
        self.finished.emit(result)


class TimelineWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, video_path: str):
        super().__init__()
        self.video_path = video_path

    def run(self) -> None:
        try:
            result = build_timeline_data(self.video_path, logger=self.progress.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class WaveformWidget(QtWidgets.QWidget):
    timeSelected = QtCore.pyqtSignal(int, float)
    cursorMoved = QtCore.pyqtSignal(float)
    viewChanged = QtCore.pyqtSignal(float, float)

    def __init__(self):
        super().__init__()
        self.audio_tracks: list[object] = []
        self.duration_s = 0.0
        self.view_start_s = 0.0
        self.view_duration_s = 0.0
        self.playhead_time: float | None = None
        self.video_marker_time: float | None = None
        self.audio_marker_time: float | None = None
        self.audio_marker_track_index: int | None = None
        self.hover_time: float | None = None
        self.setMinimumHeight(150)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def set_audio_tracks(self, audio_tracks: list[object], duration_s: float) -> None:
        self.audio_tracks = audio_tracks
        self.duration_s = max(duration_s, 0.0)
        self.view_start_s = 0.0
        self.view_duration_s = self.duration_s
        self.hover_time = None
        lane_count = max(len(audio_tracks), 1)
        self.setMinimumHeight(max(150, lane_count * 76))
        self._emit_view_changed()
        self.update()

    def set_playhead_time(self, time_s: float | None) -> None:
        self.playhead_time = time_s
        self._ensure_time_visible(time_s)
        self.update()

    def set_video_marker_time(self, time_s: float | None) -> None:
        self.video_marker_time = time_s
        self._ensure_time_visible(time_s)
        self.update()

    def set_audio_marker(self, track_ui_index: int | None, time_s: float | None) -> None:
        self.audio_marker_track_index = track_ui_index
        self.audio_marker_time = time_s
        self._ensure_time_visible(time_s)
        self.update()

    def clear(self) -> None:
        self.audio_tracks = []
        self.duration_s = 0.0
        self.view_start_s = 0.0
        self.view_duration_s = 0.0
        self.playhead_time = None
        self.video_marker_time = None
        self.audio_marker_time = None
        self.audio_marker_track_index = None
        self.hover_time = None
        self.cursorMoved.emit(-1.0)
        self._emit_view_changed()
        self.update()

    def reset_zoom(self) -> None:
        self.view_start_s = 0.0
        self.view_duration_s = self.duration_s
        self._emit_view_changed()
        self.update()

    def _preview_resolution_s(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        resolutions: list[float] = []
        for track in self.audio_tracks:
            waveform = getattr(track, "waveform", [])
            if not waveform:
                continue
            track_duration_s = float(getattr(track, "duration_s", 0.0) or self.duration_s)
            if track_duration_s <= 0:
                continue
            resolutions.append(track_duration_s / len(waveform))

        if resolutions:
            return min(resolutions)

        return self.duration_s / 6000.0

    def _min_view_duration(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        preview_resolution_s = self._preview_resolution_s()
        return min(self.duration_s, max(0.01, preview_resolution_s * 24.0))

    def _visible_duration_s(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        if self.view_duration_s <= 0:
            return self.duration_s
        return min(max(self.view_duration_s, self._min_view_duration()), self.duration_s)

    def _visible_end_s(self) -> float:
        return self.view_start_s + self._visible_duration_s()

    def _clamp_view(self) -> None:
        if self.duration_s <= 0:
            self.view_start_s = 0.0
            self.view_duration_s = 0.0
            return

        self.view_duration_s = self._visible_duration_s()
        max_start = max(self.duration_s - self.view_duration_s, 0.0)
        self.view_start_s = min(max(self.view_start_s, 0.0), max_start)

    def _ensure_time_visible(self, time_s: float | None) -> None:
        if time_s is None or self.duration_s <= 0:
            return

        self._clamp_view()
        visible_duration_s = self._visible_duration_s()
        visible_start_s = self.view_start_s
        visible_end_s = visible_start_s + visible_duration_s
        margin_s = visible_duration_s * 0.1

        new_start_s = visible_start_s
        if time_s < visible_start_s + margin_s:
            new_start_s = time_s - margin_s
        elif time_s > visible_end_s - margin_s:
            new_start_s = time_s + margin_s - visible_duration_s

        max_start = max(self.duration_s - visible_duration_s, 0.0)
        self.view_start_s = min(max(new_start_s, 0.0), max_start)
        self._emit_view_changed()

    def _emit_view_changed(self) -> None:
        self.viewChanged.emit(self.view_start_s, self._visible_duration_s())

    def _time_from_x(self, x: float) -> float:
        self._clamp_view()
        visible_duration_s = self._visible_duration_s()
        if self.width() <= 0 or visible_duration_s <= 0:
            return 0.0
        return self.view_start_s + (x / max(float(self.width()), 1.0)) * visible_duration_s

    def _update_hover(self, event: QtGui.QMouseEvent) -> None:
        if self.duration_s <= 0 or self.width() <= 0:
            if self.hover_time is not None:
                self.hover_time = None
                self.cursorMoved.emit(-1.0)
                self.update()
            return

        lanes = self._lane_rects()
        x = min(max(event.position().x(), 0.0), float(self.width()))
        y = event.position().y()
        if any(lane_rect.contains(int(x), int(y)) for lane_rect in lanes):
            self.hover_time = self._time_from_x(x)
            self.cursorMoved.emit(self.hover_time)
        else:
            self.hover_time = None
            self.cursorMoved.emit(-1.0)
        self.update()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if self.duration_s <= 0 or self.width() <= 0:
            super().wheelEvent(event)
            return

        delta_y = event.angleDelta().y()
        if delta_y == 0:
            super().wheelEvent(event)
            return

        self._clamp_view()
        current_duration_s = self._visible_duration_s()
        cursor_ratio = min(max(event.position().x() / max(float(self.width()), 1.0), 0.0), 1.0)
        anchor_time_s = self.view_start_s + cursor_ratio * current_duration_s
        zoom_factor = 1.2 ** abs(delta_y / 120.0)

        if delta_y > 0:
            new_duration_s = current_duration_s / zoom_factor
        else:
            new_duration_s = current_duration_s * zoom_factor

        new_duration_s = min(max(new_duration_s, self._min_view_duration()), self.duration_s)
        self.view_duration_s = new_duration_s
        self.view_start_s = anchor_time_s - cursor_ratio * new_duration_s
        self._clamp_view()
        self._emit_view_changed()
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if not self.duration_s or self.width() <= 0:
            return

        lanes = self._lane_rects()
        if not lanes:
            return

        x = min(max(event.position().x(), 0.0), float(self.width()))
        y = event.position().y()
        time_s = self._time_from_x(x)
        for lane_index, lane_rect in enumerate(lanes):
            if lane_rect.contains(int(x), int(y)):
                emitted_index = lane_index if self.audio_tracks else -1
                self.timeSelected.emit(emitted_index, time_s)
                return

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self._update_hover(event)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        if self.hover_time is not None:
            self.hover_time = None
            self.cursorMoved.emit(-1.0)
            self.update()
        super().leaveEvent(event)

    def _lane_rects(self) -> list[QtCore.QRect]:
        rect = self.rect()
        if not self.audio_tracks and self.duration_s <= 0:
            return []

        lane_count = max(len(self.audio_tracks), 1)
        top_margin = 8
        bottom_margin = 8
        total_height = max(rect.height() - top_margin - bottom_margin, lane_count)
        lane_height = max(int(total_height / lane_count), 60)
        lane_rects: list[QtCore.QRect] = []

        current_top = rect.top() + top_margin
        for _ in range(lane_count):
            remaining = rect.bottom() - bottom_margin - current_top + 1
            if remaining <= 0:
                break
            current_height = min(lane_height, remaining)
            lane_rects.append(QtCore.QRect(rect.left(), current_top, rect.width(), current_height))
            current_top += current_height

        return lane_rects

    def _visible_waveform(self, waveform: list[float]) -> list[float]:
        if not waveform or self.duration_s <= 0:
            return waveform

        self._clamp_view()
        visible_duration_s = self._visible_duration_s()
        start_ratio = self.view_start_s / self.duration_s
        end_ratio = min((self.view_start_s + visible_duration_s) / self.duration_s, 1.0)
        total_points = len(waveform)
        start_index = min(max(int(start_ratio * total_points), 0), total_points - 1)
        end_index = min(max(int(end_ratio * total_points) + 1, start_index + 1), total_points)
        return waveform[start_index:end_index]

    def _draw_waveform_envelope(
        self,
        painter: QtGui.QPainter,
        waveform_rect: QtCore.QRect,
        waveform_min: list[float],
        waveform_max: list[float],
        color: QtGui.QColor,
    ) -> None:
        point_count = min(len(waveform_min), len(waveform_max))
        if point_count <= 0:
            return

        middle_y = waveform_rect.center().y()
        usable_height = max(waveform_rect.height() - 6, 10)
        half_height = usable_height / 2.0
        fill_color = QtGui.QColor(color)
        fill_color.setAlpha(180)

        for index in range(point_count):
            low = max(-1.0, min(1.0, waveform_min[index]))
            high = max(-1.0, min(1.0, waveform_max[index]))
            bar_left = waveform_rect.left() + int((index / point_count) * waveform_rect.width())
            bar_right = waveform_rect.left() + int(((index + 1) / point_count) * waveform_rect.width())
            bar_width = max(1, bar_right - bar_left)

            y_top = int(round(middle_y - high * half_height))
            y_bottom = int(round(middle_y - low * half_height))
            if y_bottom < y_top:
                y_top, y_bottom = y_bottom, y_top

            bar_height = max(1, y_bottom - y_top + 1)
            painter.fillRect(bar_left, y_top, bar_width, bar_height, fill_color)

            if bar_width >= 3:
                painter.fillRect(bar_left, y_top, bar_width, 1, color)
                painter.fillRect(bar_left, y_bottom, bar_width, 1, color)

    def _grid_step_s(self) -> float:
        visible_duration_s = self._visible_duration_s()
        if visible_duration_s <= 0:
            return 0.0

        target_step_s = visible_duration_s / 8.0
        steps_s = [
            0.001,
            0.002,
            0.005,
            0.01,
            0.02,
            0.05,
            0.1,
            0.2,
            0.5,
            1.0,
            2.0,
            5.0,
            10.0,
            20.0,
            30.0,
            60.0,
        ]
        for step_s in steps_s:
            if step_s >= target_step_s:
                return step_s
        return steps_s[-1]

    def _draw_grid(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        visible_duration_s = self._visible_duration_s()
        grid_step_s = self._grid_step_s()
        if visible_duration_s <= 0 or grid_step_s <= 0:
            return

        start_time_s = self.view_start_s
        end_time_s = start_time_s + visible_duration_s
        start_tick = int(start_time_s / grid_step_s)
        if start_tick * grid_step_s < start_time_s:
            start_tick += 1

        font = painter.font()
        font.setPointSize(max(font.pointSize() - 1, 7))
        painter.setFont(font)

        tick_index = start_tick
        while True:
            tick_time_s = tick_index * grid_step_s
            if tick_time_s >= end_time_s:
                break
            ratio = (tick_time_s - start_time_s) / visible_duration_s
            x = rect.left() + int(rect.width() * ratio)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 30), 1))
            painter.drawLine(x, rect.top(), x, rect.bottom())

            if grid_step_s < 1.0:
                label = f"{tick_time_s * 1000.0:.0f} ms"
            else:
                label = f"{tick_time_s:.2f}s"
            painter.setPen(QtGui.QPen(QtGui.QColor("#94a3b8")))
            painter.drawText(x + 4, rect.bottom() - 4, label)
            tick_index += 1

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, QtGui.QColor("#111827"))

        if not self.audio_tracks:
            if self.duration_s <= 0:
                painter.setPen(QtGui.QPen(QtGui.QColor("#cbd5e1")))
                painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, "Timeline audio indisponible")
                return

            lane_rect = self._lane_rects()[0]
            painter.fillRect(lane_rect, QtGui.QColor("#0f172a"))
            painter.setPen(QtGui.QPen(QtGui.QColor("#1e293b"), 1))
            painter.drawRect(lane_rect.adjusted(0, 0, -1, -1))

            label_rect = lane_rect.adjusted(8, 4, -8, -lane_rect.height() + 20)
            painter.setPen(QtGui.QPen(QtGui.QColor("#e2e8f0")))
            painter.drawText(
                label_rect,
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                "Point audio libre",
            )

            waveform_rect = lane_rect.adjusted(0, 22, 0, -6)
            middle_y = waveform_rect.center().y()
            self._draw_grid(painter, waveform_rect)
            painter.setPen(QtGui.QPen(QtGui.QColor("#203047"), 1))
            painter.drawLine(waveform_rect.left(), int(middle_y), waveform_rect.right(), int(middle_y))
            painter.setPen(QtGui.QPen(QtGui.QColor("#f59e0b")))
            painter.drawText(
                waveform_rect,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                "Aucune piste detectee. Clique ici pour poser un point audio manuel.",
            )
            self._draw_marker(painter, self.playhead_time, QtGui.QColor("#e2e8f0"), waveform_rect, "lecture")
            self._draw_marker(painter, self.video_marker_time, QtGui.QColor("#22c55e"), waveform_rect, "video")
            self._draw_marker(painter, self.audio_marker_time, QtGui.QColor("#fb923c"), waveform_rect, "audio")
            self._draw_marker(painter, self.hover_time, QtGui.QColor("#60a5fa"), waveform_rect, "")
            return

        lane_rects = self._lane_rects()
        for lane_index, lane_rect in enumerate(lane_rects):
            track = self.audio_tracks[lane_index]
            lane_color = QtGui.QColor("#4fc3f7") if getattr(track, "loaded", False) else QtGui.QColor("#475569")
            label_color = QtGui.QColor("#e2e8f0") if getattr(track, "loaded", False) else QtGui.QColor("#94a3b8")

            painter.fillRect(lane_rect, QtGui.QColor("#0f172a"))
            painter.setPen(QtGui.QPen(QtGui.QColor("#1e293b"), 1))
            painter.drawRect(lane_rect.adjusted(0, 0, -1, -1))

            label_rect = lane_rect.adjusted(8, 4, -8, -lane_rect.height() + 20)
            painter.setPen(QtGui.QPen(label_color))
            painter.drawText(label_rect, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, track.label)

            waveform_rect = lane_rect.adjusted(0, 22, 0, -6)
            middle_y = waveform_rect.center().y()
            usable_height = max(waveform_rect.height() - 4, 10)
            waveform = getattr(track, "waveform", [])
            visible_waveform = self._visible_waveform(waveform)
            visible_waveform_min = self._visible_waveform(getattr(track, "waveform_min", []))
            visible_waveform_max = self._visible_waveform(getattr(track, "waveform_max", []))

            self._draw_grid(painter, waveform_rect)
            painter.setPen(QtGui.QPen(QtGui.QColor("#203047"), 1))
            painter.drawLine(waveform_rect.left(), int(middle_y), waveform_rect.right(), int(middle_y))

            if visible_waveform_min and visible_waveform_max:
                self._draw_waveform_envelope(
                    painter,
                    waveform_rect,
                    visible_waveform_min,
                    visible_waveform_max,
                    lane_color,
                )
            else:
                step_x = waveform_rect.width() / max(len(visible_waveform), 1)
                half_height = usable_height / 2.0
                waveform_pen = QtGui.QPen(lane_color, 1)
                waveform_pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
                painter.setPen(waveform_pen)

                for index, value in enumerate(visible_waveform):
                    amplitude = max(0.0, min(1.0, value)) * half_height
                    x = waveform_rect.left() + int(index * step_x)
                    painter.drawLine(x, int(middle_y - amplitude), x, int(middle_y + amplitude))

            if not getattr(track, "loaded", False):
                painter.setPen(QtGui.QPen(QtGui.QColor("#f59e0b")))
                painter.drawText(
                    waveform_rect,
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    "Piste detectee mais waveform non chargee",
                )

            self._draw_marker(painter, self.playhead_time, QtGui.QColor("#e2e8f0"), waveform_rect, "lecture")
            self._draw_marker(painter, self.video_marker_time, QtGui.QColor("#22c55e"), waveform_rect, "video")
            if self.audio_marker_track_index == lane_index:
                self._draw_marker(painter, self.audio_marker_time, QtGui.QColor("#fb923c"), waveform_rect, "audio")
            self._draw_marker(painter, self.hover_time, QtGui.QColor("#60a5fa"), waveform_rect, "")

    def _draw_marker(
        self,
        painter: QtGui.QPainter,
        time_s: float | None,
        color: QtGui.QColor,
        rect: QtCore.QRect,
        label: str,
    ) -> None:
        visible_duration_s = self._visible_duration_s()
        if time_s is None or visible_duration_s <= 0:
            return

        visible_start_s = self.view_start_s
        visible_end_s = visible_start_s + visible_duration_s
        if time_s < visible_start_s or time_s > visible_end_s:
            return

        ratio = min(max((time_s - visible_start_s) / visible_duration_s, 0.0), 1.0)
        x = rect.left() + int(rect.width() * ratio)
        painter.setPen(QtGui.QPen(color, 2))
        painter.drawLine(x, rect.top(), x, rect.bottom())
        if label:
            painter.drawText(x + 4, rect.top() + 14, label)


class DesyncChecker(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.video_path: str | None = None
        self.analysis_worker: AnalysisWorker | None = None
        self.generation_worker: TestVideoWorker | None = None
        self.timeline_worker: TimelineWorker | None = None
        self.preview_capture: cv2.VideoCapture | None = None
        self.timeline_data = None
        self.media_summary_lines: list[str] = []
        self.current_frame_index = 0
        self.current_frame_image: QtGui.QImage | None = None
        self.manual_audio_time: float | None = None
        self.manual_audio_track_ui_index: int | None = None
        self.auto_flash_time: float | None = None
        self.auto_bip_time: float | None = None
        self.audio_view_start_s = 0.0
        self.audio_view_duration_s = 0.0
        self.audio_cursor_time_s: float | None = None
        self.playback_speed = 1.0
        self.playback_position_frames = 0.0
        self.playback_last_tick_s: float | None = None
        self.playback_timer = QtCore.QTimer(self)
        self.playback_timer.setInterval(20)
        self.playback_timer.timeout.connect(self._advance_playback)
        self.audio_output = QtMultimedia.QAudioOutput(self)
        self.audio_output.setVolume(1.0)
        self.audio_player = QtMultimedia.QMediaPlayer(self)
        self.audio_player.setAudioOutput(self.audio_output)
        self.audio_player.errorOccurred.connect(self._handle_audio_error)
        self.audio_player.hasAudioChanged.connect(self._handle_audio_availability_changed)
        self.audio_player.mediaStatusChanged.connect(self._handle_audio_media_status_changed)
        self.audio_available = False

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - Audio/Video Offset")
        self.setGeometry(100, 60, 1180, 720)
        self.setAcceptDrops(True)
        self.app_icon = _load_app_icon()
        if not self.app_icon.isNull():
            self.setWindowIcon(self.app_icon)

        self._build_ui()
        self._update_playback_status()
        self._setup_shortcuts()
        self.refresh_environment_status()
        self._set_timeline_enabled(False)

    def _build_ui(self) -> None:
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(8)
        header_layout.addStretch(1)

        logo_pixmap = _load_logo_pixmap(72)
        if logo_pixmap is not None:
            logo_label = QtWidgets.QLabel()
            logo_label.setPixmap(logo_pixmap)
            logo_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            logo_label.setFixedSize(84, 84)
            header_layout.addWidget(logo_label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        title = QtWidgets.QLabel("Verifier et caler un decalage audio/video")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        header_layout.addWidget(title, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch(1)
        main_layout.addLayout(header_layout)

        self.environment_label = QtWidgets.QLabel("")
        self.environment_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.environment_label)

        self.label = QtWidgets.QLabel("Aucune video chargee")
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("padding: 8px; border: 1px solid #c9c9c9; border-radius: 6px;")
        main_layout.addWidget(self.label)

        top_actions = QtWidgets.QHBoxLayout()
        top_actions.setSpacing(6)

        self.btn_load = QtWidgets.QPushButton("Charger une video")
        self.btn_load.clicked.connect(self.load_video)
        top_actions.addWidget(self.btn_load)

        self.btn_tests_menu = QtWidgets.QToolButton()
        self.btn_tests_menu.setText("Tests")
        self.btn_tests_menu.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        tests_menu = QtWidgets.QMenu(self.btn_tests_menu)
        tests_menu.addAction("Generer test 0 ms", lambda: self.generate_test_video(0.0))
        tests_menu.addAction("Generer test +100 ms", lambda: self.generate_test_video(100.0))
        self.btn_tests_menu.setMenu(tests_menu)
        top_actions.addWidget(self.btn_tests_menu)

        self.btn_doctor = QtWidgets.QPushButton("Diagnostiquer")
        self.btn_doctor.clicked.connect(self.run_diagnostics)
        top_actions.addWidget(self.btn_doctor)
        top_actions.addStretch(1)

        main_layout.addLayout(top_actions)

        self.result_label = QtWidgets.QLabel("")
        self.result_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-size: 16px;")
        self.result_label.setVisible(False)
        main_layout.addWidget(self.result_label)

        self.details_label = QtWidgets.QLabel("")
        self.details_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.details_label.setWordWrap(True)
        self.details_label.setVisible(False)
        main_layout.addWidget(self.details_label)

        content_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        content_splitter.setChildrenCollapsible(False)

        self.timeline_group = QtWidgets.QGroupBox("Timeline de calage")
        timeline_layout = QtWidgets.QVBoxLayout()
        timeline_layout.setContentsMargins(8, 8, 8, 8)
        timeline_layout.setSpacing(6)

        timeline_header = QtWidgets.QHBoxLayout()
        timeline_header.setContentsMargins(0, 0, 0, 0)
        timeline_header.addStretch(1)
        self.btn_timeline_help = QtWidgets.QToolButton()
        self.btn_timeline_help.setText("?")
        self.btn_timeline_help.setAutoRaise(True)
        self.btn_timeline_help.setToolTip("Aide timeline")
        self.btn_timeline_help.clicked.connect(self._show_timeline_help)
        timeline_header.addWidget(self.btn_timeline_help)
        timeline_layout.addLayout(timeline_header)

        self.preview_label = QtWidgets.QLabel("Apercu video")
        self.preview_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(560, 315)
        self.preview_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.preview_label.setStyleSheet("background: #101010; color: #e5e7eb; border-radius: 8px;")
        timeline_layout.addWidget(self.preview_label)

        playback_controls = QtWidgets.QHBoxLayout()
        playback_controls.setSpacing(6)
        self.btn_play_pause = QtWidgets.QPushButton("Play")
        self.btn_play_pause.clicked.connect(self._toggle_playback)
        playback_controls.addWidget(self.btn_play_pause)

        self.chk_audio_enabled = QtWidgets.QCheckBox("Audio")
        self.chk_audio_enabled.setChecked(True)
        self.chk_audio_enabled.toggled.connect(self._set_audio_enabled)
        playback_controls.addWidget(self.chk_audio_enabled)

        self.btn_slower = QtWidgets.QPushButton("Vitesse -")
        self.btn_slower.clicked.connect(lambda: self._change_playback_speed(-1))
        playback_controls.addWidget(self.btn_slower)

        self.speed_combo = QtWidgets.QComboBox()
        for speed in (0.25, 0.5, 1.0, 1.5, 2.0, 4.0):
            self.speed_combo.addItem(f"x{speed:g}", speed)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        playback_controls.addWidget(self.speed_combo)

        self.btn_faster = QtWidgets.QPushButton("Vitesse +")
        self.btn_faster.clicked.connect(lambda: self._change_playback_speed(1))
        playback_controls.addWidget(self.btn_faster)

        self.playback_status_label = QtWidgets.QLabel("Lecture arretee")
        playback_controls.addWidget(self.playback_status_label, stretch=1)
        timeline_layout.addLayout(playback_controls)

        frame_controls = QtWidgets.QHBoxLayout()
        frame_controls.setSpacing(6)
        self.btn_prev_frame = QtWidgets.QPushButton("Frame -1")
        self.btn_prev_frame.clicked.connect(lambda: self._step_frame(-1))
        frame_controls.addWidget(self.btn_prev_frame)

        self.frame_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.setSingleStep(1)
        self.frame_slider.valueChanged.connect(self._on_frame_slider_changed)
        frame_controls.addWidget(self.frame_slider, stretch=1)

        self.btn_next_frame = QtWidgets.QPushButton("Frame +1")
        self.btn_next_frame.clicked.connect(lambda: self._step_frame(1))
        frame_controls.addWidget(self.btn_next_frame)

        timeline_layout.addLayout(frame_controls)

        self.frame_position_label = QtWidgets.QLabel("Frame courante : -")
        self.frame_position_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        timeline_layout.addWidget(self.frame_position_label)

        self.waveform_widget = WaveformWidget()
        self.waveform_widget.timeSelected.connect(self._set_audio_marker_time)
        self.waveform_widget.cursorMoved.connect(self._handle_waveform_cursor_moved)
        self.waveform_widget.viewChanged.connect(self._handle_waveform_view_changed)
        timeline_layout.addWidget(self.waveform_widget)

        audio_input_layout = QtWidgets.QHBoxLayout()
        audio_input_layout.setSpacing(6)
        audio_input_label = QtWidgets.QLabel("Temps audio :")
        audio_input_layout.addWidget(audio_input_label)

        self.audio_time_input_ms = QtWidgets.QDoubleSpinBox()
        self.audio_time_input_ms.setRange(0.0, 86_400_000.0)
        self.audio_time_input_ms.setDecimals(1)
        self.audio_time_input_ms.setSingleStep(10.0)
        self.audio_time_input_ms.setSuffix(" ms")
        self.audio_time_input_ms.valueChanged.connect(self._apply_manual_audio_time_input)
        audio_input_layout.addWidget(self.audio_time_input_ms)

        self.btn_use_playhead_audio = QtWidgets.QPushButton("Audio = tete de lecture")
        self.btn_use_playhead_audio.clicked.connect(self._mark_audio_from_playhead)
        audio_input_layout.addWidget(self.btn_use_playhead_audio)

        self.btn_reset_audio_zoom = QtWidgets.QPushButton("Reset zoom")
        self.btn_reset_audio_zoom.clicked.connect(self.waveform_widget.reset_zoom)
        audio_input_layout.addWidget(self.btn_reset_audio_zoom)

        audio_input_layout.addStretch(1)
        self.audio_precision_label = QtWidgets.QLabel("Vue audio : -")
        self.audio_precision_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.audio_precision_label.setStyleSheet("color: #94a3b8;")
        audio_input_layout.addWidget(self.audio_precision_label)
        timeline_layout.addLayout(audio_input_layout)

        self.manual_offset_label = QtWidgets.QLabel("Ecart en direct : selectionne un point audio")
        self.manual_offset_label.setStyleSheet("font-size: 15px; font-weight: bold;")

        timeline_layout.addWidget(self.manual_offset_label)

        self.timeline_group.setLayout(timeline_layout)
        content_splitter.addWidget(self.timeline_group)

        sidebar_widget = QtWidgets.QWidget()
        sidebar_layout = QtWidgets.QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)

        self.media_info_group = QtWidgets.QGroupBox("Infos fichier")
        media_layout = QtWidgets.QVBoxLayout()
        media_layout.setContentsMargins(8, 8, 8, 8)
        self.media_info_box = QtWidgets.QPlainTextEdit()
        self.media_info_box.setReadOnly(True)
        self.media_info_box.setPlaceholderText("Les infos media du fichier charge apparaitront ici.")
        self.media_info_box.setMinimumHeight(240)
        media_layout.addWidget(self.media_info_box)
        self.media_info_group.setLayout(media_layout)
        self.media_info_group.setMinimumWidth(320)
        sidebar_layout.addWidget(self.media_info_group, stretch=3)

        self.log_group = QtWidgets.QGroupBox("Journal")
        log_layout = QtWidgets.QVBoxLayout()
        log_layout.setContentsMargins(8, 8, 8, 8)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Les etapes d'analyse, de generation et de chargement de timeline apparaitront ici.")
        self.log_box.setMaximumBlockCount(2000)
        self.log_box.setMinimumHeight(140)
        log_layout.addWidget(self.log_box)
        self.log_group.setLayout(log_layout)
        sidebar_layout.addWidget(self.log_group, stretch=2)

        sidebar_widget.setLayout(sidebar_layout)
        content_splitter.addWidget(sidebar_widget)
        content_splitter.setStretchFactor(0, 5)
        content_splitter.setStretchFactor(1, 2)
        content_splitter.setSizes([820, 360])

        main_layout.addWidget(content_splitter, stretch=1)

        footer_layout = QtWidgets.QHBoxLayout()
        footer_layout.setSpacing(8)

        hint = QtWidgets.QLabel(
            "Astuce : tu peux aussi glisser-deposer une video compatible dans cette fenetre."
        )
        hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5b6470;")
        footer_layout.addWidget(hint, stretch=1)

        self.project_meta_label = QtWidgets.QLabel(
            (
                f"Version {APP_VERSION} | Cree par {APP_CREATOR} | "
                f"<a href=\"{APP_GITHUB_URL}\">GitHub</a> | {APP_LICENSE_NAME}"
            )
        )
        self.project_meta_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.project_meta_label.setOpenExternalLinks(True)
        self.project_meta_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.project_meta_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextBrowserInteraction)
        self.project_meta_label.setStyleSheet("color: #5b6470;")
        footer_layout.addWidget(self.project_meta_label, stretch=0)

        main_layout.addLayout(footer_layout)

        self.setLayout(main_layout)

    def refresh_environment_status(self) -> None:
        report = check_environment()
        if report.ffmpeg_available:
            text = f"Environnement OK - FFmpeg detecte : {report.ffmpeg_path}"
            style = "color: #1f7a1f;"
        else:
            text = "FFmpeg non trouve - l'analyse peut fonctionner, mais la timeline audio et la generation seront plus fragiles."
            style = "color: #8a4500;"
        self.environment_label.setText(text)
        self.environment_label.setStyleSheet(style)

    def _setup_shortcuts(self) -> None:
        shortcuts: list[tuple[str, object]] = [
            ("Space", self._toggle_playback),
            ("Left", lambda: self._step_frame(-1)),
            ("Right", lambda: self._step_frame(1)),
            ("Shift+Left", lambda: self._jump_seconds(-1.0)),
            ("Shift+Right", lambda: self._jump_seconds(1.0)),
            ("Up", lambda: self._change_playback_speed(1)),
            ("Down", lambda: self._change_playback_speed(-1)),
        ]
        self.shortcuts: list[QtGui.QShortcut] = []
        for key_sequence, callback in shortcuts:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key_sequence), self)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

    def _show_timeline_help(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Aide timeline",
            (
                "Calage manuel\n"
                "- place la tete de lecture sur le flash\n"
                "- clique sur la waveform ou saisis un temps audio\n"
                "- l'ecart se calcule en direct entre la frame courante et le point audio\n"
                "- survole la waveform pour lire le temps exact sous le curseur\n"
                "- s'il n'y a pas de piste audio, utilise la zone libre ou la saisie en ms\n"
                "- molette souris : zoom audio\n"
                "- double-clic sur la waveform : reset zoom\n\n"
                "Raccourcis\n"
                "- Espace : play/pause\n"
                "- Fleche gauche/droite : frame par frame\n"
                "- Shift + fleche gauche/droite : saute 1 seconde\n"
                "- Fleche haut/bas : change la vitesse"
            ),
        )

    def _load_audio_source(self, video_path: str | None) -> None:
        self.audio_player.stop()
        self.audio_available = False
        if not video_path:
            self.audio_player.setSource(QtCore.QUrl())
            return

        self.audio_player.setSource(QtCore.QUrl.fromLocalFile(video_path))
        self.audio_player.setPlaybackRate(self.playback_speed)
        self.append_log(f"Source audio Qt chargee : {video_path}")

    def _set_audio_enabled(self, enabled: bool) -> None:
        self.audio_output.setMuted(not enabled)
        if not enabled:
            self.audio_player.pause()
        elif self._is_playing():
            self._sync_audio_to_current_frame(play_if_needed=True)
        self._update_playback_status()

    def _sync_audio_to_current_frame(self, play_if_needed: bool = False) -> None:
        if self.timeline_data is None or self.video_path is None or not self.chk_audio_enabled.isChecked():
            return

        target_position_ms = int(round(self._frame_to_time(self.frame_slider.value()) * 1000.0))
        self.audio_player.setPlaybackRate(self.playback_speed)
        self.audio_player.setPosition(target_position_ms)
        if play_if_needed:
            self.audio_player.play()

    def _handle_audio_availability_changed(self, available: bool) -> None:
        self.audio_available = bool(available)
        message = "Audio Qt disponible." if available else "Audio Qt indisponible pour ce fichier."
        self.append_log(message)
        self._render_media_info()
        self._update_playback_status()

    def _handle_audio_media_status_changed(self, status: QtMultimedia.QMediaPlayer.MediaStatus) -> None:
        if status == QtMultimedia.QMediaPlayer.MediaStatus.InvalidMedia:
            self.append_log("Qt Multimedia ne peut pas lire l'audio de ce fichier.")
        elif status == QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia and self._is_playing():
            self.audio_player.pause()

    def _handle_audio_error(self, _error: QtMultimedia.QMediaPlayer.Error, error_message: str) -> None:
        if error_message:
            self.append_log(f"Erreur audio Qt : {error_message}")

    def _build_media_summary_section(self) -> list[str]:
        audio_playback_text = "Audio Qt : disponible" if self.audio_available else "Audio Qt : indisponible ou non detecte"
        if self.media_summary_lines:
            lines: list[str] = []
            audio_replaced = False
            for line in self.media_summary_lines:
                if line.startswith("Audio Qt :"):
                    lines.append(audio_playback_text)
                    audio_replaced = True
                else:
                    lines.append(line)
            if not audio_replaced:
                lines.append(audio_playback_text)
            return lines

        return [audio_playback_text]

    def append_log(self, message: str) -> None:
        self.log_box.appendPlainText(message)

    def _is_playing(self) -> bool:
        return self.playback_timer.isActive()

    def _set_timeline_enabled(self, enabled: bool) -> None:
        widgets = [
            self.preview_label,
            self.btn_play_pause,
            self.chk_audio_enabled,
            self.btn_slower,
            self.speed_combo,
            self.btn_faster,
            self.btn_prev_frame,
            self.frame_slider,
            self.btn_next_frame,
            self.audio_time_input_ms,
            self.btn_use_playhead_audio,
            self.btn_reset_audio_zoom,
            self.waveform_widget,
        ]
        for widget in widgets:
            widget.setEnabled(enabled)

    def _release_preview_capture(self) -> None:
        if self.preview_capture is not None:
            self.preview_capture.release()
            self.preview_capture = None

    def set_video_path(self, path: str) -> None:
        self.video_path = path
        self.timeline_data = None
        self.media_summary_lines = [
            "Timeline : preparation en cours...",
            "Pistes audio : chargement...",
            "Audio Qt : chargement...",
        ]
        self.current_frame_index = 0
        self.current_frame_image = None
        self.playback_position_frames = 0.0
        self.playback_last_tick_s = None
        self.manual_audio_time = None
        self.manual_audio_track_ui_index = None
        self.auto_flash_time = None
        self.auto_bip_time = None
        self.audio_view_start_s = 0.0
        self.audio_view_duration_s = 0.0
        self.audio_cursor_time_s = None
        self._pause_playback()
        self._release_preview_capture()
        self.waveform_widget.clear()
        self._load_audio_source(path)
        self.preview_label.setText("Chargement de l'apercu...")
        self.preview_label.setPixmap(QtGui.QPixmap())
        self.label.setText(f"Video chargee : {path}")
        self.label.setToolTip(path)
        self.result_label.setText("")
        self.result_label.setStyleSheet("font-size: 16px;")
        self.result_label.setVisible(False)
        self.details_label.setText("")
        self.details_label.setVisible(False)
        self.frame_position_label.setText("Frame courante : chargement...")
        self._render_media_info()
        self.waveform_widget.set_video_marker_time(None)
        self._sync_audio_time_input(None)
        self._refresh_audio_precision_label()
        self.manual_offset_label.setText("Ecart en direct : selectionne un point audio")
        self.manual_offset_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self._set_timeline_enabled(False)
        self._start_timeline_load()

    def _start_timeline_load(self) -> None:
        if not self.video_path:
            return

        if self.timeline_worker is not None and self.timeline_worker.isRunning():
            self.timeline_worker.wait()

        self.append_log(f"Chargement de la timeline pour {self.video_path}")
        self.timeline_worker = TimelineWorker(self.video_path)
        self.timeline_worker.progress.connect(self.append_log)
        self.timeline_worker.finished.connect(self._handle_timeline_ready)
        self.timeline_worker.failed.connect(self._handle_timeline_failed)
        self.timeline_worker.start()

    def _handle_timeline_ready(self, timeline_data) -> None:
        self.timeline_worker = None
        self.timeline_data = timeline_data
        self.playback_position_frames = 0.0
        self.playback_last_tick_s = None
        loaded_tracks = sum(1 for track in timeline_data.audio_tracks if track.loaded)
        if timeline_data.audio_tracks and loaded_tracks == 0:
            audio_status = f"{len(timeline_data.audio_tracks)} piste(s) detectee(s), mais aucune waveform chargee"
        elif timeline_data.audio_tracks:
            audio_status = f"{loaded_tracks}/{len(timeline_data.audio_tracks)} piste(s) audio chargee(s)"
        else:
            audio_status = "aucune piste audio detectee, mode point audio libre"
        if timeline_data.audio_tracks:
            tracks_text = " ; ".join(track.label for track in timeline_data.audio_tracks)
        else:
            tracks_text = "aucune piste detectee, clique dans la zone audio ou saisis un temps manuel"
        audio_playback_text = "Audio Qt : disponible" if self.audio_available else "Audio Qt : indisponible ou non detecte"
        self.media_summary_lines = [
            f"Timeline : {timeline_data.frame_count} frames | {timeline_data.duration_s:.3f}s | {timeline_data.fps:.3f} fps",
            f"Audio timeline : {audio_status}",
            f"Pistes audio : {tracks_text}",
            audio_playback_text,
        ]
        self.waveform_widget.set_audio_tracks(timeline_data.audio_tracks, timeline_data.duration_s)
        self.waveform_widget.set_playhead_time(0.0)
        self.waveform_widget.set_audio_marker(None, None)
        self._render_media_info()
        self.frame_slider.blockSignals(True)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(max(timeline_data.frame_count - 1, 0))
        self.frame_slider.setValue(0)
        self.frame_slider.blockSignals(False)
        self._set_timeline_enabled(timeline_data.frame_count > 0)
        self._update_playback_status()

        self._release_preview_capture()
        self.preview_capture = cv2.VideoCapture(timeline_data.video_path)
        self._display_frame(0)

    def _handle_timeline_failed(self, error_message: str) -> None:
        self.timeline_worker = None
        self._pause_playback()
        self.media_summary_lines = [
            f"Timeline : indisponible ({error_message})",
            "Pistes audio : indisponibles",
            "Audio Qt : indisponible ou non detecte",
        ]
        self._render_media_info()
        self.append_log(f"Timeline indisponible : {error_message}")
        self._set_timeline_enabled(False)

    def _display_frame(self, frame_index: int) -> None:
        if self.preview_capture is None or self.timeline_data is None:
            return

        max_frame = max(self.timeline_data.frame_count - 1, 0)
        frame_index = min(max(frame_index, 0), max_frame)

        self.preview_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        success, frame = self.preview_capture.read()
        if not success:
            self.preview_label.setText("Impossible de lire cette frame.")
            return

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb_frame.shape
        image = QtGui.QImage(
            rgb_frame.data,
            width,
            height,
            channels * width,
            QtGui.QImage.Format.Format_RGB888,
        ).copy()

        self.current_frame_image = image
        self.current_frame_index = frame_index
        self._render_current_frame()

        current_time = self._frame_to_time(frame_index)
        self.frame_position_label.setText(
            f"Frame courante : {frame_index + 1}/{self.timeline_data.frame_count} | "
            f"{self._frame_window_text(frame_index)}"
        )
        self.waveform_widget.set_playhead_time(current_time)
        self.waveform_widget.set_video_marker_time(current_time)
        self._update_manual_offset()

    def _render_current_frame(self) -> None:
        if self.current_frame_image is None:
            return

        pixmap = QtGui.QPixmap.fromImage(self.current_frame_image)
        scaled = pixmap.scaled(
            self.preview_label.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def _render_media_info(self) -> None:
        sections: list[str] = []
        summary_lines = self._build_media_summary_section()
        if summary_lines:
            sections.append("Resume")
            sections.append("-" * len("Resume"))
            sections.extend(summary_lines)
            sections.append("")

        if self.timeline_data is None:
            self.media_info_box.setPlainText("\n".join(sections).strip())
            return

        for section in self.timeline_data.media_info_sections:
            sections.append(section.title)
            sections.append("-" * len(section.title))
            sections.extend(section.lines)
            sections.append("")

        self.media_info_box.setPlainText("\n".join(sections).strip())

    def _update_playback_status(self) -> None:
        state = "Lecture" if self._is_playing() else "Pause"
        self.btn_play_pause.setText("Pause" if self._is_playing() else "Play")
        if not self.chk_audio_enabled.isChecked():
            audio_state = "audio coupe"
        elif self.audio_available:
            audio_state = "audio on"
        else:
            audio_state = "audio indisponible"
        clock_state = "audio maitre" if self._is_audio_clock_active() else "timer maitre"
        self.playback_status_label.setText(f"{state} | vitesse x{self.playback_speed:g} | {audio_state} | {clock_state}")

    def _is_audio_clock_active(self) -> bool:
        return (
            self.timeline_data is not None
            and self.chk_audio_enabled.isChecked()
            and self.audio_available
            and self.audio_player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
        )

    def _on_speed_changed(self, index: int) -> None:
        if index < 0:
            return
        speed_value = self.speed_combo.itemData(index)
        if speed_value is None:
            return
        self.playback_speed = float(speed_value)
        if self._is_playing():
            self.playback_last_tick_s = time.perf_counter()
            self.audio_player.setPlaybackRate(self.playback_speed)
        self._update_playback_status()

    def _change_playback_speed(self, direction: int) -> None:
        new_index = self.speed_combo.currentIndex() + direction
        new_index = min(max(new_index, 0), self.speed_combo.count() - 1)
        if new_index != self.speed_combo.currentIndex():
            self.speed_combo.setCurrentIndex(new_index)

    def _toggle_playback(self) -> None:
        if self.timeline_data is None or self.timeline_data.frame_count <= 0:
            return
        if self._is_playing():
            self._pause_playback()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        if self.timeline_data is None or self.timeline_data.frame_count <= 0:
            return
        if self.frame_slider.value() >= self.frame_slider.maximum():
            self.frame_slider.setValue(self.frame_slider.minimum())
        self.playback_position_frames = float(self.frame_slider.value())
        self.playback_last_tick_s = time.perf_counter()
        self._sync_audio_to_current_frame(play_if_needed=True)
        self.playback_timer.start()
        self._update_playback_status()

    def _pause_playback(self) -> None:
        if self.playback_timer.isActive():
            self.playback_timer.stop()
        self.playback_last_tick_s = None
        self.audio_player.pause()
        self._update_playback_status()

    def _advance_playback(self) -> None:
        if self.timeline_data is None or self.timeline_data.frame_count <= 0:
            self._pause_playback()
            return

        if self._is_audio_clock_active():
            audio_time_s = max(self.audio_player.position(), 0) / 1000.0
            max_frame = self.frame_slider.maximum()
            target_frame = min(max(self._time_to_frame(audio_time_s), self.frame_slider.minimum()), max_frame)
            self.playback_position_frames = float(target_frame)
            if target_frame != self.frame_slider.value():
                self.frame_slider.setValue(target_frame)
            if target_frame >= max_frame and audio_time_s >= self._frame_to_time(max_frame):
                self._pause_playback()
            return

        now = time.perf_counter()
        if self.playback_last_tick_s is None:
            self.playback_last_tick_s = now
            return

        elapsed_s = max(0.0, now - self.playback_last_tick_s)
        self.playback_last_tick_s = now
        self.playback_position_frames += elapsed_s * self.timeline_data.fps * self.playback_speed

        if self.playback_position_frames >= self.frame_slider.maximum():
            self.frame_slider.setValue(self.frame_slider.maximum())
            self.playback_position_frames = float(self.frame_slider.maximum())
            self._pause_playback()
            return

        target_frame = int(self.playback_position_frames)
        if target_frame != self.frame_slider.value():
            self.frame_slider.setValue(target_frame)

    def _jump_seconds(self, seconds: float) -> None:
        if self.timeline_data is None:
            return
        if self._is_playing():
            self._pause_playback()
        target_frame = self.frame_slider.value() + int(round(seconds * self.timeline_data.fps))
        target_frame = min(max(target_frame, self.frame_slider.minimum()), self.frame_slider.maximum())
        self.frame_slider.setValue(target_frame)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render_current_frame()

    def _fps(self) -> float:
        if self.timeline_data is None or self.timeline_data.fps <= 0:
            return 0.0
        return self.timeline_data.fps

    def _frame_duration_s(self) -> float:
        fps = self._fps()
        if fps <= 0:
            return 0.0
        return 1.0 / fps

    def _format_time(self, time_s: float) -> str:
        fps = self._fps()
        frame_value = time_s * fps if fps > 0 else 0.0
        return f"{time_s:.3f}s | {time_s * 1000.0:.1f} ms | {frame_value:.2f} fr"

    def _format_offset(self, offset_ms: float) -> str:
        fps = self._fps()
        offset_frames = (offset_ms / 1000.0) * fps if fps > 0 else 0.0
        fps_text = f" @ {fps:.3f} fps" if fps > 0 else ""
        return f"{offset_ms:+.1f} ms | {offset_frames:+.2f} fr{fps_text}"

    def _preview_precision_ms(self) -> float | None:
        if self.timeline_data is None:
            return None

        resolutions_ms: list[float] = []
        for track in self.timeline_data.audio_tracks:
            waveform = getattr(track, "waveform", [])
            if not waveform:
                continue
            track_duration_s = float(getattr(track, "duration_s", 0.0) or self.timeline_data.duration_s)
            if track_duration_s <= 0:
                continue
            resolutions_ms.append((track_duration_s / len(waveform)) * 1000.0)

        if resolutions_ms:
            return min(resolutions_ms)
        if self.timeline_data.duration_s > 0:
            return (self.timeline_data.duration_s / 6000.0) * 1000.0
        return None

    def _refresh_audio_precision_label(self) -> None:
        view_ms = self.audio_view_duration_s * 1000.0
        precision_ms = self._preview_precision_ms()
        parts: list[str] = []
        if self.audio_cursor_time_s is not None:
            parts.append(f"Curseur {self.audio_cursor_time_s * 1000.0:.1f} ms")
        if view_ms > 0:
            parts.append(f"Vue {view_ms:.1f} ms")
        if precision_ms is not None:
            parts.append(f"Preview ~{precision_ms:.2f} ms")
        self.audio_precision_label.setText(" | ".join(parts) if parts else "Vue audio : -")

    def _handle_waveform_view_changed(self, start_s: float, duration_s: float) -> None:
        self.audio_view_start_s = start_s
        self.audio_view_duration_s = duration_s
        self._refresh_audio_precision_label()

    def _handle_waveform_cursor_moved(self, time_s: float) -> None:
        self.audio_cursor_time_s = None if time_s < 0 else time_s
        self._refresh_audio_precision_label()

    def _frame_to_time(self, frame_index: int) -> float:
        if self.timeline_data is None or self.timeline_data.fps <= 0:
            return 0.0
        return frame_index / self.timeline_data.fps

    def _time_to_frame(self, time_s: float) -> int:
        if self.timeline_data is None or self.timeline_data.fps <= 0:
            return 0
        return int(round(time_s * self.timeline_data.fps))

    def _frame_window_text(self, frame_index: int) -> str:
        start_s = self._frame_to_time(frame_index)
        frame_duration_s = self._frame_duration_s()
        if frame_duration_s <= 0:
            return self._format_time(start_s)

        end_s = start_s + frame_duration_s
        center_s = start_s + (frame_duration_s / 2.0)
        return (
            f"fenetre {start_s * 1000.0:.1f}-{end_s * 1000.0:.1f} ms | "
            f"centre {center_s * 1000.0:.1f} ms"
        )

    def _get_audio_track(self, track_ui_index: int | None):
        if self.timeline_data is None or track_ui_index is None:
            return None
        if track_ui_index < 0 or track_ui_index >= len(self.timeline_data.audio_tracks):
            return None
        return self.timeline_data.audio_tracks[track_ui_index]

    def _sync_audio_time_input(self, time_s: float | None) -> None:
        value_ms = 0.0 if time_s is None else max(time_s * 1000.0, 0.0)
        self.audio_time_input_ms.blockSignals(True)
        self.audio_time_input_ms.setValue(value_ms)
        self.audio_time_input_ms.blockSignals(False)

    def _default_audio_track_index(self) -> int:
        if self.timeline_data is not None and self.timeline_data.primary_audio_track_index is not None:
            return int(self.timeline_data.primary_audio_track_index)
        return -1

    def _set_manual_audio_marker(self, time_s: float, track_ui_index: int | None = None) -> None:
        if self.timeline_data is not None and self.timeline_data.duration_s > 0:
            time_s = min(max(time_s, 0.0), self.timeline_data.duration_s)
        else:
            time_s = max(time_s, 0.0)

        selected_track_index = self._default_audio_track_index() if track_ui_index is None else track_ui_index
        track = self._get_audio_track(selected_track_index)

        self.manual_audio_time = time_s
        self.manual_audio_track_ui_index = selected_track_index
        self.waveform_widget.set_audio_marker(selected_track_index, time_s)
        self._sync_audio_time_input(time_s)

        self._update_manual_offset()

    def _on_frame_slider_changed(self, value: int) -> None:
        self.playback_position_frames = float(value)
        if self._is_playing():
            self.playback_last_tick_s = time.perf_counter()
        else:
            self._sync_audio_to_current_frame(play_if_needed=False)
        self._display_frame(value)

    def _step_frame(self, delta: int) -> None:
        if self._is_playing():
            self._pause_playback()
        value = self.frame_slider.value() + delta
        value = min(max(value, self.frame_slider.minimum()), self.frame_slider.maximum())
        self.frame_slider.setValue(value)

    def _set_audio_marker_time(self, track_ui_index: int, time_s: float) -> None:
        self._set_manual_audio_marker(time_s, track_ui_index=track_ui_index)

    def _apply_manual_audio_time_input(self, _value: float | None = None) -> None:
        if self.timeline_data is None:
            return
        self._set_manual_audio_marker(self.audio_time_input_ms.value() / 1000.0)

    def _mark_audio_from_playhead(self) -> None:
        if self.timeline_data is None:
            return
        self._set_manual_audio_marker(self._frame_to_time(self.current_frame_index))

    def _update_manual_offset(self) -> None:
        if self.timeline_data is None or self.manual_audio_time is None:
            self.manual_offset_label.setText("Ecart en direct : selectionne un point audio")
            self.manual_offset_label.setStyleSheet("font-size: 16px; font-weight: bold;")
            return

        video_time = self._frame_to_time(self.current_frame_index)
        offset_ms = (self.manual_audio_time - video_time) * 1000.0
        half_frame_ms = (self._frame_duration_s() * 1000.0) / 2.0
        if abs(offset_ms) <= 40.0:
            text = f"Ecart en direct : {self._format_offset(offset_ms)} | synchro"
            style = "color: #1f7a1f; font-size: 16px; font-weight: bold;"
        elif offset_ms > 0:
            text = f"Ecart en direct : {self._format_offset(offset_ms)} | audio en retard"
            style = "color: #b36b00; font-size: 16px; font-weight: bold;"
        else:
            text = f"Ecart en direct : {self._format_offset(offset_ms)} | audio en avance"
            style = "color: #b00020; font-size: 16px; font-weight: bold;"

        if half_frame_ms > 0:
            text += f" | precision video +/-{half_frame_ms:.1f} ms"

        self.manual_offset_label.setText(text)
        self.manual_offset_label.setStyleSheet(style)

    def set_busy(self, busy: bool) -> None:
        if busy and self._is_playing():
            self._pause_playback()
        buttons = [
            self.btn_load,
            self.btn_tests_menu,
            self.btn_doctor,
        ]
        for button in buttons:
            button.setEnabled(not busy)

        manual_enabled = (not busy) and self.timeline_data is not None and self.timeline_data.frame_count > 0
        self._set_timeline_enabled(manual_enabled)

    def load_video(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choisir une video",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi)",
        )
        if path:
            self.set_video_path(path)

    def start_analysis(self) -> None:
        if not self.video_path:
            return

        self.log_box.clear()
        self.append_log(f"Demarrage de l'analyse automatique pour {self.video_path}")
        self.result_label.setText("Analyse auto en cours...")
        self.result_label.setStyleSheet("color: #004f7c; font-weight: bold; font-size: 16px;")
        self.result_label.setVisible(True)
        self.details_label.setText("")
        self.details_label.setVisible(False)
        self.refresh_environment_status()
        self.set_busy(True)

        self.analysis_worker = AnalysisWorker(self.video_path)
        self.analysis_worker.progress.connect(self.append_log)
        self.analysis_worker.finished.connect(self._handle_analysis_finished)
        self.analysis_worker.start()

    def _handle_analysis_finished(self, result) -> None:
        self.set_busy(False)
        self.analysis_worker = None

        style = STATUS_STYLES.get(result.status, "color: #333333; font-weight: bold;")
        self.result_label.setText(result.message)
        self.result_label.setStyleSheet(style)
        self.result_label.setVisible(bool(result.message))

        details = []
        if result.flash_time is not None:
            details.append(f"Flash auto : {self._format_time(result.flash_time)}")
            self.auto_flash_time = result.flash_time
        if result.bip_time is not None:
            details.append(f"Bip auto : {self._format_time(result.bip_time)}")
            self.auto_bip_time = result.bip_time
        if result.offset_ms is not None:
            details.append(f"Ecart auto : {self._format_offset(result.offset_ms)}")
        details.append(f"Extraction FFmpeg : {'oui' if result.used_ffmpeg else 'non'}")

        details_text = " | ".join(details)
        self.details_label.setText(details_text)
        self.details_label.setVisible(bool(details_text))

        if self.auto_flash_time is not None and self.timeline_data is not None:
            frame_index = self._time_to_frame(self.auto_flash_time)
            frame_index = min(max(frame_index, self.frame_slider.minimum()), self.frame_slider.maximum())
            self.frame_slider.setValue(frame_index)

        if self.manual_audio_time is None and self.auto_bip_time is not None:
            preferred_track = self.timeline_data.primary_audio_track_index if self.timeline_data is not None else None
            self._set_manual_audio_marker(self.auto_bip_time, track_ui_index=preferred_track)

        self._update_manual_offset()

    def generate_test_video(self, offset_ms: float) -> None:
        default_name = "test_sync_video.mp4" if offset_ms == 0 else "test_desync_100ms.mp4"
        default_path = get_default_output_path(default_name)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Enregistrer la video de test",
            default_path,
            "Video Files (*.mp4)",
        )
        if not path:
            return

        self.log_box.clear()
        self.append_log(f"Preparation d'une video de test avec un ecart attendu de {offset_ms:+.0f} ms")
        self.result_label.setText("Generation de la video de test...")
        self.result_label.setStyleSheet("color: #004f7c; font-weight: bold; font-size: 16px;")
        self.result_label.setVisible(True)
        self.details_label.setText("")
        self.details_label.setVisible(False)
        self.refresh_environment_status()
        self.set_busy(True)

        self.generation_worker = TestVideoWorker(path, offset_ms)
        self.generation_worker.progress.connect(self.append_log)
        self.generation_worker.finished.connect(self._handle_generation_finished)
        self.generation_worker.start()

    def _handle_generation_finished(self, result) -> None:
        self.set_busy(False)
        self.generation_worker = None
        self.set_video_path(result.output_path)

        if result.audio_embedded:
            style = "color: #1f7a1f; font-weight: bold; font-size: 16px;"
        else:
            style = "color: #8a4500; font-weight: bold; font-size: 16px;"

        self.result_label.setText(result.message)
        self.result_label.setStyleSheet(style)
        self.result_label.setVisible(bool(result.message))
        details_text = f"Fichier : {result.output_path} | Ecart attendu : {self._format_offset(result.expected_offset_ms)}"
        self.details_label.setText(details_text)
        self.details_label.setVisible(True)

    def run_diagnostics(self) -> None:
        self.refresh_environment_status()
        self.append_log("Diagnostic de l'environnement :")
        for line in format_environment_report(check_environment()):
            self.append_log(f"- {line}")

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(is_supported_video_file(url.toLocalFile()) for url in urls if url.isLocalFile()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue

            candidate = url.toLocalFile()
            if is_supported_video_file(candidate):
                self.set_video_path(candidate)
                self.append_log(f"Video chargee par glisser-deposer : {candidate}")
                event.acceptProposedAction()
                return

        event.ignore()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._pause_playback()
        self.audio_player.stop()
        self._release_preview_capture()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Desync Checker")
    app_icon = _load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = DesyncChecker()
    window.show()
    sys.exit(app.exec())
