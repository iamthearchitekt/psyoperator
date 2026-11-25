"""
SUBLIMINAL // CUT - Lightweight Subliminal Cut Video Renderer
Drop a video, preview the random micro-cut splice map, and hit RENDER.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, QUrl, Signal, QRectF
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from engine import (
    CutSegment,
    RenderConfig,
    VideoInfo,
    extract_thumbnail,
    generate_cut_plan,
    probe_video,
    render_subliminal_video,
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv"}


class DropZoneFrame(QFrame):
    """Drag-and-drop video loader card with thumbnail preview and metadata badge."""

    fileDropped = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("DropZone")
        self.setMinimumHeight(124)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        # Thumbnail preview label
        self.thumb_label = QLabel("DROP\nVIDEO")
        self.thumb_label.setFixedSize(160, 92)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setObjectName("ThumbBox")
        layout.addWidget(self.thumb_label)

        # Info & action column
        info_col = QVBoxLayout()
        info_col.setSpacing(6)

        self.title_label = QLabel("Drag & Drop Video Here  —  or Click Browse")
        self.title_label.setObjectName("DropTitle")
        self.title_label.setWordWrap(True)
        info_col.addWidget(self.title_label)

        self.meta_label = QLabel("Supports MP4, MOV, MKV, WEBM, AVI • Ready for instant 1-click splicing")
        self.meta_label.setObjectName("DropMeta")
        self.meta_label.setWordWrap(True)
        info_col.addWidget(self.meta_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.browse_btn = QPushButton("📂 Select Video...")
        self.browse_btn.setObjectName("SecondaryBtn")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.browse_btn)

        self.demo_btn = QPushButton("🧪 Generate Demo Clip")
        self.demo_btn.setObjectName("GhostBtn")
        self.demo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.demo_btn.setToolTip("Generate a 12-second synthetic test video to try out rendering immediately")
        btn_row.addWidget(self.demo_btn)

        btn_row.addStretch()
        info_col.addLayout(btn_row)
        layout.addLayout(info_col, stretch=1)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                local = url.toLocalFile()
                if Path(local).suffix.lower() in VIDEO_EXTENSIONS:
                    event.acceptProposedAction()
                    self.setProperty("dragActive", True)
                    self.style().unpolish(self)
                    self.style().polish(self)
                    return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if Path(local).suffix.lower() in VIDEO_EXTENSIONS:
                self.fileDropped.emit(local)
                event.acceptProposedAction()
                return


class TimelineMapWidget(QWidget):
    """Visualizes the planned micro-cuts and subliminal flashes along the output timeline."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(46)
        self.setMaximumHeight(52)
        self.segments: List[CutSegment] = []
        self.source_duration: float = 10.0

    def set_segments(self, segments: List[CutSegment], source_duration: float = 10.0) -> None:
        self.segments = segments
        self.source_duration = max(0.1, source_duration)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#2a2a38"), 1))
        painter.setBrush(QColor("#111118"))
        painter.drawRoundedRect(rect, 6, 6)

        if not self.segments:
            painter.setPen(QColor("#68687a"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Load a video to preview the subliminal splice map")
            return

        total_dur = sum(s.duration_sec for s in self.segments)
        if total_dur <= 0:
            return

        inner = rect.adjusted(4, 4, -4, -4)
        w = inner.width()
        h = inner.height()
        x_cursor = float(inner.left())

        for seg in self.segments:
            seg_w = max(1.5, (seg.duration_sec / total_dur) * w)
            # Determine segment color based on role & effect
            if not seg.is_subliminal:
                color = QColor("#23394d")  # Normal base video segment
            elif seg.effect == "invert":
                color = QColor("#00f5d4")  # Cyan flash for inverted frame
            elif seg.effect == "high_contrast":
                color = QColor("#ffbe0b")  # Amber flash for high contrast
            elif seg.effect == "red_flash":
                color = QColor("#ff003c")  # Bright crimson flash
            else:
                # Vary hue brightness slightly by source start position
                ratio = min(1.0, max(0.0, seg.start_sec / self.source_duration))
                r = int(225 + 30 * ratio)
                g = int(35 + 45 * (1.0 - ratio))
                b = int(75 + 60 * ratio)
                color = QColor(r, g, b)

            seg_rect = QRectF(x_cursor, inner.top(), min(seg_w, inner.right() - x_cursor), h)
            painter.fillRect(seg_rect, color)

            # Subtle divider line if wide enough
            if seg_w > 3.5:
                painter.setPen(QPen(QColor(15, 15, 22, 170), 1))
                painter.drawLine(int(x_cursor), inner.top(), int(x_cursor), inner.bottom())

            x_cursor += (seg.duration_sec / total_dur) * w
            if x_cursor >= inner.right():
                break


class RenderWorker(QThread):
    """Background worker thread running the FFmpeg subliminal splice render."""

    progressChanged = Signal(float, str)
    finishedSuccess = Signal(str, float, int)
    failedError = Signal(str)

    def __init__(self, config: RenderConfig, segments: List[CutSegment]) -> None:
        super().__init__()
        self.config = config
        self.segments = segments
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            segs = render_subliminal_video(
                self.config,
                segments=self.segments,
                progress_callback=lambda pct, msg: self.progressChanged.emit(pct, msg),
                cancel_check=lambda: self._cancelled,
            )
            elapsed = time.perf_counter() - t0
            self.finishedSuccess.emit(self.config.output_path, elapsed, len(segs))
        except Exception as exc:
            self.failedError.emit(str(exc))


class SubliminalCutWindow(QMainWindow):
    def __init__(self, initial_video: Optional[str] = None) -> None:
        super().__init__()
        self.setWindowTitle("PSYOPERATOR — Subliminal Cut Video Renderer")
        self.setMinimumSize(760, 700)
        self.resize(820, 740)

        self.video_info: Optional[VideoInfo] = None
        self.secondary_path: Optional[str] = None
        self.planned_segments: List[CutSegment] = []
        self.current_seed: int = int(time.time() * 1000) % 999999
        self.worker: Optional[RenderWorker] = None
        self.last_output_path: Optional[str] = None

        self._build_ui()
        self._apply_stylesheet()

        if initial_video and os.path.isfile(initial_video):
            self.load_video(initial_video)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 18)
        root.setSpacing(12)

        # 1. Header bar
        header_row = QHBoxLayout()
        title_lbl = QLabel("👁️ PSYOPERATOR")
        title_lbl.setObjectName("AppHeader")
        header_row.addWidget(title_lbl)

        badge_lbl = QLabel("SUBLIMINAL CUT VIDEO RENDERER")
        badge_lbl.setObjectName("HeaderBadge")
        header_row.addWidget(badge_lbl)
        header_row.addStretch()
        root.addLayout(header_row)

        # 2. Drag & drop video loader card
        self.drop_zone = DropZoneFrame()
        self.drop_zone.fileDropped.connect(self.load_video)
        self.drop_zone.browse_btn.clicked.connect(self._browse_input_video)
        self.drop_zone.demo_btn.clicked.connect(self._generate_and_load_demo_video)
        root.addWidget(self.drop_zone)

        # 3. Mode Toggle + Quick Presets Card
        mode_card = QFrame()
        mode_card.setObjectName("PanelCard")
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(14, 10, 14, 10)
        mode_layout.setSpacing(8)

        mode_top = QHBoxLayout()
        mode_lbl = QLabel("SPLICE MODE:")
        mode_lbl.setObjectName("SectionLabel")
        mode_top.addWidget(mode_lbl)

        self.btn_mode_supercut = QPushButton("⚡ Rapid Supercut (Stitch Random Micro-Clips)")
        self.btn_mode_supercut.setCheckable(True)
        self.btn_mode_supercut.setChecked(True)
        self.btn_mode_supercut.setObjectName("ModeToggleBtn")
        self.btn_mode_supercut.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_supercut.clicked.connect(lambda: self._set_mode("supercut"))
        mode_top.addWidget(self.btn_mode_supercut, stretch=1)

        self.btn_mode_insert = QPushButton("👁️ Subliminal Flash Inserts (Splice Flashes Into Video)")
        self.btn_mode_insert.setCheckable(True)
        self.btn_mode_insert.setObjectName("ModeToggleBtn")
        self.btn_mode_insert.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_insert.clicked.connect(lambda: self._set_mode("subliminal_insert"))
        mode_top.addWidget(self.btn_mode_insert, stretch=1)
        mode_layout.addLayout(mode_top)

        # Quick presets row
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        p_lbl = QLabel("PRESETS:")
        p_lbl.setObjectName("MutedLabel")
        preset_row.addWidget(p_lbl)

        presets = [
            ("⚡ Hyper Blitz (50× 40–120ms)", "supercut", 50, 40, 120, 20, 15),
            ("🎞️ 1-Frame Tachistoscope (75× 33–45ms)", "supercut", 75, 33, 45, 10, 25),
            ("🥊 Fight Club Flashes (14× 33–65ms)", "subliminal_insert", 14, 33, 65, 10, 20),
            ("🌀 Chaos Glitch (40× 60–220ms)", "supercut", 40, 60, 220, 35, 30),
        ]
        for label, mode, cuts, mn, mx, stut, fx in presets:
            b = QPushButton(label)
            b.setObjectName("PresetChip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(
                lambda _=False, m=mode, c=cuts, a=mn, z=mx, s=stut, f=fx: self._apply_preset(m, c, a, z, s, f)
            )
            preset_row.addWidget(b)
        preset_row.addStretch()
        mode_layout.addLayout(preset_row)
        root.addWidget(mode_card)

        # 4. Parameters Grid Card
        params_card = QFrame()
        params_card.setObjectName("PanelCard")
        grid = QGridLayout(params_card)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)

        # Row 0: Number of Cuts & Audio Handling
        grid.addWidget(self._make_label("RANDOM CUTS COUNT"), 0, 0)
        cuts_box = QHBoxLayout()
        self.cuts_slider = QSlider(Qt.Orientation.Horizontal)
        self.cuts_slider.setRange(3, 160)
        self.cuts_slider.setValue(45)
        self.cuts_spin = QSpinBox()
        self.cuts_spin.setRange(3, 160)
        self.cuts_spin.setValue(45)
        self.cuts_spin.setSuffix(" cuts")
        self.cuts_slider.valueChanged.connect(self.cuts_spin.setValue)
        self.cuts_spin.valueChanged.connect(self.cuts_slider.setValue)
        self.cuts_spin.valueChanged.connect(self._refresh_cut_plan)
        cuts_box.addWidget(self.cuts_slider, stretch=1)
        cuts_box.addWidget(self.cuts_spin)
        grid.addLayout(cuts_box, 0, 1)

        grid.addWidget(self._make_label("AUDIO SPLICING"), 0, 2)
        self.audio_combo = QComboBox()
        self.audio_combo.addItem("🔊 Hard-Cut Glitch Audio (Slice with Video)", "slice")
        self.audio_combo.addItem("🎵 Continuous Original Audio Track", "continuous")
        self.audio_combo.addItem("🔇 Mute Audio (Silent Output)", "mute")
        grid.addWidget(self.audio_combo, 0, 3)

        # Row 1: Min Cut Duration (ms) & Max Cut Duration (ms)
        grid.addWidget(self._make_label("MIN CUT LENGTH"), 1, 0)
        self.min_ms_spin = QSpinBox()
        self.min_ms_spin.setRange(20, 2000)
        self.min_ms_spin.setSingleStep(10)
        self.min_ms_spin.setValue(40)
        self.min_ms_spin.setSuffix(" ms  (~1-2 frames)")
        self.min_ms_spin.valueChanged.connect(self._on_min_ms_changed)
        grid.addWidget(self.min_ms_spin, 1, 1)

        grid.addWidget(self._make_label("MAX CUT LENGTH"), 1, 2)
        self.max_ms_spin = QSpinBox()
        self.max_ms_spin.setRange(25, 3000)
        self.max_ms_spin.setSingleStep(15)
        self.max_ms_spin.setValue(160)
        self.max_ms_spin.setSuffix(" ms")
        self.max_ms_spin.valueChanged.connect(self._on_max_ms_changed)
        grid.addWidget(self.max_ms_spin, 1, 3)

        # Row 2: Stutter Repeat Chance (%) & Visual Flash FX Chance (%)
        grid.addWidget(self._make_label("STUTTER REPEAT %"), 2, 0)
        self.stutter_spin = QSpinBox()
        self.stutter_spin.setRange(0, 75)
        self.stutter_spin.setSingleStep(5)
        self.stutter_spin.setValue(15)
        self.stutter_spin.setSuffix(" %  (Machine-gun echo)")
        self.stutter_spin.valueChanged.connect(self._refresh_cut_plan)
        grid.addWidget(self.stutter_spin, 2, 1)

        grid.addWidget(self._make_label("SUBLIMINAL FLASH FX %"), 2, 2)
        self.fx_spin = QSpinBox()
        self.fx_spin.setRange(0, 100)
        self.fx_spin.setSingleStep(5)
        self.fx_spin.setValue(15)
        self.fx_spin.setSuffix(" %  (Invert / Contrast / Red)")
        self.fx_spin.valueChanged.connect(self._refresh_cut_plan)
        grid.addWidget(self.fx_spin, 2, 3)

        # Row 3: Base Clip Duration (for Insert mode) & Optional Secondary Subliminal Source
        self.base_dur_label = self._make_label("BASE CLIP WINDOW")
        grid.addWidget(self.base_dur_label, 3, 0)
        self.base_dur_spin = QDoubleSpinBox()
        self.base_dur_spin.setRange(0.0, 3600.0)
        self.base_dur_spin.setSingleStep(5.0)
        self.base_dur_spin.setValue(15.0)
        self.base_dur_spin.setSpecialValueText("Full Source Duration")
        self.base_dur_spin.setSuffix(" sec (0 = Full)")
        self.base_dur_spin.setEnabled(False)
        self.base_dur_spin.valueChanged.connect(self._refresh_cut_plan)
        grid.addWidget(self.base_dur_spin, 3, 1)

        grid.addWidget(self._make_label("EXTERNAL FLASH POOL"), 3, 2)
        sec_row = QHBoxLayout()
        self.secondary_btn = QPushButton("Optional 2nd Video: Self (Same Video)")
        self.secondary_btn.setObjectName("GhostBtn")
        self.secondary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary_btn.setToolTip(
            "Optionally pick a second video to pull subliminal flashes from (defaults to using the main video itself)"
        )
        self.secondary_btn.clicked.connect(self._browse_secondary_video)
        sec_row.addWidget(self.secondary_btn, stretch=1)

        self.clear_sec_btn = QPushButton("✕")
        self.clear_sec_btn.setFixedWidth(28)
        self.clear_sec_btn.setObjectName("GhostBtn")
        self.clear_sec_btn.setVisible(False)
        self.clear_sec_btn.clicked.connect(self._clear_secondary_video)
        sec_row.addWidget(self.clear_sec_btn)
        grid.addLayout(sec_row, 3, 3)

        root.addWidget(params_card)

        # 5. Live Splice Timeline Map Card
        timeline_card = QFrame()
        timeline_card.setObjectName("PanelCard")
        tl_layout = QVBoxLayout(timeline_card)
        tl_layout.setContentsMargins(14, 10, 14, 10)
        tl_layout.setSpacing(6)

        tl_top = QHBoxLayout()
        tl_title = QLabel("LIVE SPLICE TIMELINE PREVIEW")
        tl_title.setObjectName("SectionLabel")
        tl_top.addWidget(tl_title)

        self.plan_stats_lbl = QLabel("No video loaded")
        self.plan_stats_lbl.setObjectName("StatsBadge")
        tl_top.addWidget(self.plan_stats_lbl)
        tl_top.addStretch()

        self.reroll_btn = QPushButton("🎲 Re-Roll Random Cuts")
        self.reroll_btn.setObjectName("GhostBtn")
        self.reroll_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reroll_btn.clicked.connect(self._reroll_seed)
        tl_top.addWidget(self.reroll_btn)
        tl_layout.addLayout(tl_top)

        self.timeline_widget = TimelineMapWidget()
        tl_layout.addWidget(self.timeline_widget)
        root.addWidget(timeline_card)

        # 6. Output Path Row
        out_row = QHBoxLayout()
        out_lbl = QLabel("OUTPUT FILE:")
        out_lbl.setObjectName("MutedLabel")
        out_row.addWidget(out_lbl)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Auto-generated next to source video upon load...")
        out_row.addWidget(self.output_edit, stretch=1)

        out_browse = QPushButton("Save As...")
        out_browse.setObjectName("GhostBtn")
        out_browse.clicked.connect(self._browse_output_path)
        out_row.addWidget(out_browse)
        root.addLayout(out_row)

        # 7. Progress Bar & Status Row
        prog_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% — Ready")
        prog_row.addWidget(self.progress_bar, stretch=1)

        self.play_out_btn = QPushButton("▶ Play Output")
        self.play_out_btn.setObjectName("SuccessBtn")
        self.play_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_out_btn.setVisible(False)
        self.play_out_btn.clicked.connect(self._play_last_output)
        prog_row.addWidget(self.play_out_btn)

        self.open_folder_btn = QPushButton("📂 Reveal File")
        self.open_folder_btn.setObjectName("GhostBtn")
        self.open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self._reveal_last_output)
        prog_row.addWidget(self.open_folder_btn)
        root.addLayout(prog_row)

        # 8. Giant Single-Click RENDER Button
        self.render_btn = QPushButton("⚡  RENDER SUBLIMINAL CUT")
        self.render_btn.setObjectName("GiantRenderBtn")
        self.render_btn.setMinimumHeight(58)
        self.render_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.render_btn.clicked.connect(self._on_render_clicked)
        root.addWidget(self.render_btn)

    def _make_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        return lbl

    def _set_mode(self, mode: str) -> None:
        is_supercut = mode == "supercut"
        self.btn_mode_supercut.setChecked(is_supercut)
        self.btn_mode_insert.setChecked(not is_supercut)
        self.base_dur_spin.setEnabled(not is_supercut)
        self._refresh_cut_plan()

    def _current_mode(self) -> str:
        return "supercut" if self.btn_mode_supercut.isChecked() else "subliminal_insert"

    def _apply_preset(
        self, mode: str, cuts: int, min_ms: int, max_ms: int, stutter: int, fx: int
    ) -> None:
        self._set_mode(mode)
        self.cuts_spin.blockSignals(True)
        self.min_ms_spin.blockSignals(True)
        self.max_ms_spin.blockSignals(True)
        self.stutter_spin.blockSignals(True)
        self.fx_spin.blockSignals(True)

        self.cuts_spin.setValue(cuts)
        self.cuts_slider.setValue(cuts)
        self.min_ms_spin.setValue(min_ms)
        self.max_ms_spin.setValue(max_ms)
        self.stutter_spin.setValue(stutter)
        self.fx_spin.setValue(fx)

        self.cuts_spin.blockSignals(False)
        self.min_ms_spin.blockSignals(False)
        self.max_ms_spin.blockSignals(False)
        self.stutter_spin.blockSignals(False)
        self.fx_spin.blockSignals(False)

        self._reroll_seed()

    def _on_min_ms_changed(self, val: int) -> None:
        if val > self.max_ms_spin.value():
            self.max_ms_spin.setValue(val)
        self._refresh_cut_plan()

    def _on_max_ms_changed(self, val: int) -> None:
        if val < self.min_ms_spin.value():
            self.min_ms_spin.setValue(val)
        self._refresh_cut_plan()

    def _reroll_seed(self) -> None:
        self.current_seed = int(time.time_ns() // 1000) % 9999999
        self._refresh_cut_plan()

    def _browse_input_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Source Video",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv);;All Files (*.*)",
        )
        if path:
            self.load_video(path)

    def _browse_secondary_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Optional Secondary Subliminal Source Video",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv);;All Files (*.*)",
        )
        if path:
            self.secondary_path = path
            self.secondary_btn.setText(f"2nd Pool: {Path(path).name}")
            self.clear_sec_btn.setVisible(True)
            self._refresh_cut_plan()

    def _clear_secondary_video(self) -> None:
        self.secondary_path = None
        self.secondary_btn.setText("Optional 2nd Video: Self (Same Video)")
        self.clear_sec_btn.setVisible(False)
        self._refresh_cut_plan()

    def _browse_output_path(self) -> None:
        default_path = self.output_edit.text().strip() or "subliminal_output.mp4"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Rendered Video As",
            default_path,
            "MP4 Video (*.mp4)",
        )
        if path:
            if not path.lower().endswith(".mp4"):
                path += ".mp4"
            self.output_edit.setText(path)

    def _generate_and_load_demo_video(self) -> None:
        """Create a dynamic 12-second synthetic test video with timecode & audio so the user can test immediately."""
        demo_dir = Path(os.path.dirname(os.path.abspath(__file__))) / "demo_videos"
        demo_dir.mkdir(parents=True, exist_ok=True)
        demo_path = str(demo_dir / "synthetic_source_12s.mp4")

        self.progress_bar.setFormat("Generating 12s demo source video...")
        QApplication.processEvents()

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=duration=12:size=1280x720:rate=30",
            "-f", "lavfi", "-i", "aevalsrc=0.25*sin(2*PI*(220+110*mod(t\\,4))*t):d=12:s=44100",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k",
            demo_path,
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
        if res.returncode != 0:
            QMessageBox.warning(self, "Demo Generation Failed", f"Could not generate demo clip:\n{res.stderr}")
            return

        self.load_video(demo_path)

    def load_video(self, path: str) -> None:
        try:
            info = probe_video(path)
        except Exception as exc:
            QMessageBox.critical(self, "Invalid Video File", f"Could not load video:\n{exc}")
            return

        self.video_info = info
        p = Path(path)
        self.drop_zone.title_label.setText(f"🎬 {p.name}")
        audio_tag = "Stereo/Audio" if info.has_audio else "No Audio Track"
        self.drop_zone.meta_label.setText(
            f"{info.width}×{info.height}  •  {info.fps:.2f} FPS (1 frame = {info.frame_duration_ms:.1f} ms)  •  "
            f"Duration: {info.duration:.2f}s  •  {info.file_size_mb:.1f} MB  •  {audio_tag}"
        )

        # Extract thumbnail preview
        thumb_file = os.path.join(tempfile.gettempdir(), "subliminal_thumb_preview.png")
        if extract_thumbnail(path, min(1.0, info.duration * 0.25), thumb_file, width=320):
            pix = QPixmap(thumb_file)
            if not pix.isNull():
                self.drop_zone.thumb_label.setPixmap(
                    pix.scaled(
                        self.drop_zone.thumb_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

        # Auto-populate default output path next to source
        stamp = int(time.time()) % 100000
        default_out = str(p.with_name(f"{p.stem}_subliminal_{stamp}.mp4"))
        self.output_edit.setText(default_out)

        self._reroll_seed()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Ready — Hit RENDER SUBLIMINAL CUT below")

    def _build_config(self) -> Optional[RenderConfig]:
        if not self.video_info:
            return None
        out_path = self.output_edit.text().strip()
        if not out_path:
            p = Path(self.video_info.path)
            out_path = str(p.with_name(f"{p.stem}_subliminal.mp4"))
            self.output_edit.setText(out_path)

        mode = "supercut" if self.btn_mode_supercut.isChecked() else "subliminal_insert"
        return RenderConfig(
            input_path=self.video_info.path,
            output_path=out_path,
            secondary_source_path=self.secondary_path,
            mode=mode,
            num_cuts=self.cuts_spin.value(),
            min_cut_ms=self.min_ms_spin.value(),
            max_cut_ms=self.max_ms_spin.value(),
            base_duration_sec=self.base_dur_spin.value(),
            audio_mode=self.audio_combo.currentData(),
            stutter_chance=self.stutter_spin.value() / 100.0,
            fx_chance=self.fx_spin.value() / 100.0,
            seed=self.current_seed,
        )

    def _refresh_cut_plan(self) -> None:
        if not self.video_info:
            return
        cfg = self._build_config()
        if not cfg:
            return
        try:
            self.planned_segments = generate_cut_plan(cfg, main_info=self.video_info)
            self.timeline_widget.set_segments(self.planned_segments, self.video_info.duration)

            total_dur = sum(s.duration_sec for s in self.planned_segments)
            sub_segs = [s for s in self.planned_segments if s.is_subliminal]
            avg_ms = (
                (sum(s.duration_sec for s in sub_segs) / len(sub_segs)) * 1000.0
                if sub_segs
                else 0.0
            )
            avg_frames = avg_ms / self.video_info.frame_duration_ms
            fx_count = sum(1 for s in sub_segs if s.effect != "none")
            self.plan_stats_lbl.setText(
                f"{len(sub_segs)} subliminal cuts  •  Avg cut: {avg_ms:.0f} ms (~{avg_frames:.1f} frames)  •  "
                f"{fx_count} FX flashes  •  Total Output: {total_dur:.2f}s"
            )
        except Exception as exc:
            self.plan_stats_lbl.setText(f"Plan error: {exc}")

    def _on_render_clicked(self) -> None:
        # If currently rendering, allow cancellation
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.render_btn.setEnabled(False)
            self.progress_bar.setFormat("Cancelling...")
            return

        if not self.video_info:
            self._browse_input_video()
            if not self.video_info:
                return

        cfg = self._build_config()
        if not cfg:
            return

        # Re-generate fresh cut plan if empty
        if not self.planned_segments:
            self._refresh_cut_plan()

        self.play_out_btn.setVisible(False)
        self.open_folder_btn.setVisible(False)
        self.render_btn.setText("⏹  CANCEL RENDER")
        self.render_btn.setProperty("rendering", True)
        self.render_btn.style().unpolish(self.render_btn)
        self.render_btn.style().polish(self.render_btn)

        self.worker = RenderWorker(cfg, list(self.planned_segments))
        self.worker.progressChanged.connect(self._on_render_progress)
        self.worker.finishedSuccess.connect(self._on_render_finished)
        self.worker.failedError.connect(self._on_render_failed)
        self.worker.start()

    def _on_render_progress(self, pct: float, msg: str) -> None:
        self.progress_bar.setValue(int(pct))
        self.progress_bar.setFormat(f"%p% — {msg}")

    def _on_render_finished(self, output_path: str, elapsed_sec: float, num_segs: int) -> None:
        self.last_output_path = output_path
        self._reset_render_btn()
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(
            f"100% — Spliced {num_segs} segments in {elapsed_sec:.1f}s -> {Path(output_path).name}"
        )
        self.play_out_btn.setVisible(True)
        self.open_folder_btn.setVisible(True)

        # Prepare a fresh output filename & seed for the next single-click render
        p = Path(self.video_info.path) if self.video_info else Path(output_path)
        stamp = int(time.time()) % 100000
        self.output_edit.setText(str(p.with_name(f"{p.stem}_subliminal_{stamp}.mp4")))
        self._reroll_seed()

    def _on_render_failed(self, err_msg: str) -> None:
        self._reset_render_btn()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Render stopped / failed")
        if "cancelled" not in err_msg.lower():
            QMessageBox.critical(self, "Render Error", f"Failed to render subliminal video:\n\n{err_msg}")

    def _reset_render_btn(self) -> None:
        self.render_btn.setEnabled(True)
        self.render_btn.setText("⚡  RENDER SUBLIMINAL CUT")
        self.render_btn.setProperty("rendering", False)
        self.render_btn.style().unpolish(self.render_btn)
        self.render_btn.style().polish(self.render_btn)

    def _play_last_output(self) -> None:
        if self.last_output_path and os.path.isfile(self.last_output_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output_path))

    def _reveal_last_output(self) -> None:
        if self.last_output_path and os.path.isfile(self.last_output_path):
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(self.last_output_path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.last_output_path)))

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #0d0d12;
                color: #ececf4;
                font-family: "Segoe UI", "Inter", sans-serif;
                font-size: 13px;
            }
            #AppHeader {
                font-size: 20px;
                font-weight: 900;
                letter-spacing: 1.5px;
                color: #ff2a5f;
            }
            #HeaderBadge {
                background-color: #1c1c28;
                color: #9e9eb8;
                font-size: 11px;
                font-weight: 700;
                padding: 4px 10px;
                border-radius: 4px;
                letter-spacing: 1px;
            }
            #DropZone {
                background-color: #151520;
                border: 2px dashed #323248;
                border-radius: 10px;
            }
            #DropZone[dragActive="true"] {
                border: 2px solid #ff2a5f;
                background-color: #1e1524;
            }
            #ThumbBox {
                background-color: #0b0b10;
                border: 1px solid #28283a;
                border-radius: 6px;
                color: #56566e;
                font-weight: 800;
                font-size: 12px;
            }
            #DropTitle {
                font-size: 15px;
                font-weight: 700;
                color: #ffffff;
            }
            #DropMeta {
                font-size: 12px;
                color: #9494ad;
            }
            #PanelCard {
                background-color: #14141d;
                border: 1px solid #242434;
                border-radius: 8px;
            }
            #SectionLabel {
                font-size: 11px;
                font-weight: 800;
                color: #8888a4;
                letter-spacing: 1px;
            }
            #FieldLabel {
                font-size: 11px;
                font-weight: 700;
                color: #a8a8c0;
            }
            #MutedLabel {
                font-size: 11px;
                font-weight: 600;
                color: #75758e;
            }
            #StatsBadge {
                background-color: #1d1d2b;
                color: #ffbe0b;
                font-size: 11px;
                font-weight: 700;
                padding: 3px 8px;
                border-radius: 4px;
            }
            QPushButton#ModeToggleBtn {
                background-color: #1c1c28;
                border: 1px solid #2d2d42;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 700;
                color: #9c9cb4;
            }
            QPushButton#ModeToggleBtn:checked {
                background-color: #2b1422;
                border: 1px solid #ff2a5f;
                color: #ffffff;
            }
            QPushButton#PresetChip {
                background-color: #1c1c28;
                border: 1px solid #2c2c3e;
                border-radius: 4px;
                padding: 4px 9px;
                font-size: 11px;
                font-weight: 600;
                color: #c8c8dc;
            }
            QPushButton#PresetChip:hover {
                border-color: #ff2a5f;
                color: #ffffff;
            }
            QPushButton#SecondaryBtn {
                background-color: #242436;
                border: 1px solid #3c3c56;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: 700;
                color: #ffffff;
            }
            QPushButton#SecondaryBtn:hover {
                background-color: #2f2f46;
                border-color: #ff2a5f;
            }
            QPushButton#GhostBtn {
                background-color: #1a1a26;
                border: 1px solid #2c2c40;
                border-radius: 5px;
                padding: 5px 11px;
                font-size: 12px;
                font-weight: 600;
                color: #b8b8d0;
            }
            QPushButton#GhostBtn:hover {
                background-color: #242436;
                color: #ffffff;
            }
            QPushButton#SuccessBtn {
                background-color: #0f3828;
                border: 1px solid #00f59b;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: 700;
                color: #00f59b;
            }
            QPushButton#SuccessBtn:hover {
                background-color: #164f39;
            }
            QPushButton#GiantRenderBtn {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff1744, stop:1 #ff5252);
                border: none;
                border-radius: 8px;
                font-size: 17px;
                font-weight: 900;
                letter-spacing: 1.5px;
                color: #ffffff;
            }
            QPushButton#GiantRenderBtn:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff335c, stop:1 #ff6b6b);
            }
            QPushButton#GiantRenderBtn[rendering="true"] {
                background-color: #3a2028;
                border: 1px solid #ff2a5f;
            }
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
                background-color: #1b1b28;
                border: 1px solid #2e2e44;
                border-radius: 5px;
                padding: 5px 8px;
                color: #f0f0f8;
                font-weight: 600;
            }
            QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus {
                border-color: #ff2a5f;
            }
            QProgressBar {
                background-color: #151520;
                border: 1px solid #28283c;
                border-radius: 5px;
                height: 24px;
                text-align: center;
                font-weight: 700;
                color: #ececf4;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff1744, stop:1 #ffbe0b);
                border-radius: 4px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #242436;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #ff2a5f;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 2px solid #ff2a5f;
                width: 14px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
            """
        )


def main() -> None:
    app = QApplication(sys.argv)
    initial_video = sys.argv[1] if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]) else None
    win = SubliminalCutWindow(initial_video=initial_video)
    win.setWindowFlags(win.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    win.show()
    win.setWindowFlags(win.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
    win.show()
    win.raise_()
    win.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
