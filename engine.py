"""
PSYOPERATOR - Core FFmpeg Subliminal Splicing, Dark Threat Grading & Directive Injection Engine
Fast, frame-accurate micro-sequence extractor and splicer using FFmpeg.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional


DEFAULT_DIRECTIVES = [
    "OBEY",
    "SUBMIT",
    "COMPLY",
    "NO ESCAPE",
    "WATCH",
    "CONSUME",
    "FORGET",
    "FEAR",
]


@dataclass
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    codec_name: str = "h264"
    file_size_mb: float = 0.0

    @property
    def frame_duration_ms(self) -> float:
        return 1000.0 / max(self.fps, 1.0)


@dataclass
class CutSegment:
    source_path: str
    start_sec: float
    duration_sec: float
    is_subliminal: bool = True
    effect: str = "none"  # "none" | "blood_ritual" | "abyss_invert" | "necrotic_mono" | "rgb_trauma"
    directive_text: str = ""  # Optional 1-frame burned-in subliminal command (e.g. "OBEY")
    has_audio: bool = True


@dataclass
class RenderConfig:
    input_path: str
    output_path: str
    secondary_source_path: Optional[str] = None
    mode: str = "supercut"  # "supercut" | "subliminal_insert"
    num_cuts: int = 50
    min_cut_ms: int = 35
    max_cut_ms: int = 130
    base_duration_sec: float = 15.0  # Used in subliminal_insert mode (0 = full video)
    audio_mode: str = "slice"  # "slice" | "demonic_slice" | "continuous" | "mute"
    threat_grade: str = "lethal"  # "lethal" | "nightmare" | "occult" | "raw"
    stutter_chance: float = 0.25  # 0.0 to 1.0: chance to repeat a micro-cut 2-3x
    fx_chance: float = 0.45  # 0.0 to 1.0: chance to apply visual flash FX on a cut
    directive_chance: float = 0.0  # 0.0 to 1.0: chance to flash a 1-frame PSYOP command text (0 = off by default)
    directives: List[str] = field(default_factory=lambda: list(DEFAULT_DIRECTIVES))
    seed: Optional[int] = None
    preset: str = "ultrafast"
    crf: int = 20
    max_width: int = 1920


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def probe_video(path: str) -> VideoInfo:
    """Inspect a video file using ffprobe and return its stream metadata."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Video file not found: {path}")

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
    )
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {res.stderr.strip()}")

    data = json.loads(res.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise ValueError(f"No video stream found in: {path}")

    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
    if duration <= 0.05:
        raise ValueError(f"Video duration is too short or unreadable ({duration:.3f}s)")

    width = int(video_stream.get("width") or 1280)
    height = int(video_stream.get("height") or 720)
    width = max(2, width - (width % 2))
    height = max(2, height - (height % 2))

    fps = 30.0
    fps_str = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "30/1"
    if "/" in fps_str:
        num, den = fps_str.split("/", 1)
        if float(den) > 0 and float(num) > 0:
            fps = float(num) / float(den)
    elif float(fps_str) > 0:
        fps = float(fps_str)
    fps = min(max(fps, 10.0), 120.0)

    size_bytes = float(fmt.get("size") or os.path.getsize(path))

    return VideoInfo(
        path=path,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        has_audio=audio_stream is not None,
        codec_name=video_stream.get("codec_name", "h264"),
        file_size_mb=size_bytes / (1024 * 1024),
    )


def extract_thumbnail(video_path: str, timestamp_sec: float, output_png: str, width: int = 320) -> bool:
    """Extract a single frame thumbnail as PNG."""
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{max(0.0, timestamp_sec):.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        output_png,
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        creationflags=_creation_flags(),
    )
    return res.returncode == 0 and os.path.isfile(output_png)


def _pick_effect(rng: random.Random, fx_chance: float, threat_grade: str = "lethal") -> str:
    if fx_chance <= 0.0 or rng.random() >= fx_chance:
        return "none"
    if threat_grade == "occult":
        return rng.choice(["blood_ritual", "abyss_invert", "blood_ritual", "necrotic_mono"])
    if threat_grade == "nightmare":
        return rng.choice(["rgb_trauma", "necrotic_mono", "abyss_invert", "blood_ritual"])
    return rng.choice(["blood_ritual", "abyss_invert", "necrotic_mono", "rgb_trauma"])


def _pick_directive(rng: random.Random, chance: float, pool: List[str]) -> str:
    clean_pool = [w.strip().upper() for w in pool if w and w.strip()]
    if not clean_pool or chance <= 0.0 or rng.random() >= chance:
        return ""
    return rng.choice(clean_pool)


def generate_cut_plan(
    config: RenderConfig,
    main_info: Optional[VideoInfo] = None,
    secondary_info: Optional[VideoInfo] = None,
) -> List[CutSegment]:
    """
    Build the exact ordered list of micro-segments to splice together.
    """
    if main_info is None:
        main_info = probe_video(config.input_path)
    if config.secondary_source_path and secondary_info is None:
        secondary_info = probe_video(config.secondary_source_path)

    sub_source = secondary_info if secondary_info is not None else main_info
    rng = random.Random(config.seed if config.seed is not None else time.time_ns())

    min_s = max(0.020, min(config.min_cut_ms, config.max_cut_ms) / 1000.0)
    max_s = max(min_s, max(config.min_cut_ms, config.max_cut_ms) / 1000.0)
    frame_s = 1.0 / max(main_info.fps, 24.0)
    min_s = max(min_s, frame_s * 0.95)
    max_s = max(max_s, min_s)

    segments: List[CutSegment] = []

    if config.mode == "supercut":
        count = max(1, config.num_cuts)
        i = 0
        while i < count:
            dur = rng.uniform(min_s, max_s)
            frames = max(1, round(dur / frame_s))
            dur = frames * frame_s

            src = sub_source if (secondary_info and rng.random() < 0.65) else main_info
            max_start = max(0.0, src.duration - dur - 0.02)
            start = rng.uniform(0.0, max_start) if max_start > 0 else 0.0

            effect = _pick_effect(rng, config.fx_chance, config.threat_grade)
            directive = _pick_directive(rng, config.directive_chance, config.directives)
            seg = CutSegment(
                source_path=src.path,
                start_sec=round(start, 4),
                duration_sec=round(dur, 4),
                is_subliminal=True,
                effect=effect,
                directive_text=directive,
                has_audio=src.has_audio,
            )
            segments.append(seg)
            i += 1

            if config.stutter_chance > 0 and rng.random() < config.stutter_chance and i < count:
                repeats = rng.randint(1, min(3, count - i))
                for _ in range(repeats):
                    segments.append(
                        CutSegment(
                            source_path=seg.source_path,
                            start_sec=seg.start_sec,
                            duration_sec=seg.duration_sec,
                            is_subliminal=True,
                            effect=_pick_effect(rng, max(config.fx_chance, 0.5), config.threat_grade),
                            directive_text=_pick_directive(rng, config.directive_chance, config.directives),
                            has_audio=seg.has_audio,
                        )
                    )
                    i += 1

    else:
        base_dur = main_info.duration
        if config.base_duration_sec > 0 and config.base_duration_sec < main_info.duration:
            base_dur = config.base_duration_sec

        num_flashes = max(1, config.num_cuts)
        slot_len = base_dur / (num_flashes + 0.5)
        cursor = 0.0

        for _ in range(num_flashes):
            min_gap = max(frame_s * 2, slot_len * 0.35)
            max_gap = max(min_gap, slot_len * 1.45)
            normal_dur = rng.uniform(min_gap, max_gap)

            if cursor + normal_dur >= base_dur - min_s:
                normal_dur = max(frame_s, (base_dur - cursor) * 0.5)

            if normal_dur >= frame_s:
                segments.append(
                    CutSegment(
                        source_path=main_info.path,
                        start_sec=round(cursor, 4),
                        duration_sec=round(normal_dur, 4),
                        is_subliminal=False,
                        effect="none",
                        directive_text="",
                        has_audio=main_info.has_audio,
                    )
                )
                cursor += normal_dur

            flash_dur = rng.uniform(min_s, max_s)
            flash_frames = max(1, round(flash_dur / frame_s))
            flash_dur = flash_frames * frame_s

            max_flash_start = max(0.0, sub_source.duration - flash_dur - 0.02)
            flash_start = rng.uniform(0.0, max_flash_start) if max_flash_start > 0 else 0.0
            if sub_source.path == main_info.path and main_info.duration > 2.0:
                for _ in range(5):
                    candidate = rng.uniform(0.0, max_flash_start)
                    if abs(candidate - cursor) > min(1.5, main_info.duration * 0.25):
                        flash_start = candidate
                        break

            flash_seg = CutSegment(
                source_path=sub_source.path,
                start_sec=round(flash_start, 4),
                duration_sec=round(flash_dur, 4),
                is_subliminal=True,
                effect=_pick_effect(rng, config.fx_chance, config.threat_grade),
                directive_text=_pick_directive(rng, config.directive_chance, config.directives),
                has_audio=sub_source.has_audio,
            )
            segments.append(flash_seg)

            if config.stutter_chance > 0 and rng.random() < config.stutter_chance:
                segments.append(
                    CutSegment(
                        source_path=flash_seg.source_path,
                        start_sec=flash_seg.start_sec,
                        duration_sec=flash_seg.duration_sec,
                        is_subliminal=True,
                        effect=_pick_effect(rng, max(config.fx_chance, 0.5), config.threat_grade),
                        directive_text=_pick_directive(rng, config.directive_chance, config.directives),
                        has_audio=flash_seg.has_audio,
                    )
                )

            cursor = min(base_dur, cursor + flash_dur)
            if cursor >= base_dur - frame_s:
                break

        remaining = base_dur - cursor
        if remaining >= frame_s * 2:
            segments.append(
                CutSegment(
                    source_path=main_info.path,
                    start_sec=round(cursor, 4),
                    duration_sec=round(remaining, 4),
                    is_subliminal=False,
                    effect="none",
                    directive_text="",
                    has_audio=main_info.has_audio,
                )
            )

    return segments


def _sanitize_drawtext(text: str) -> str:
    """Keep only safe alphanumeric/space characters for FFmpeg drawtext filter."""
    cleaned = "".join(c for c in text.upper() if c.isalnum() or c in (" ", "-", "/"))
    return cleaned.strip()[:28]


def _build_batch_ffmpeg_cmd(
    batch: List[CutSegment],
    main_info: VideoInfo,
    include_sliced_audio: bool,
    output_file: str,
    preset: str = "ultrafast",
    crf: int = 20,
    max_width: int = 1920,
    threat_grade: str = "lethal",
    demonic_audio: bool = False,
) -> List[str]:
    """
    Construct an FFmpeg command that fast-seeks each CutSegment in `batch`
    and concatenates them with dark threat grading, flash FX, 1-frame PSYOP directives, and audio slicing.
    """
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    for seg in batch:
        cmd.extend([
            "-threads", "2",
            "-ss", f"{seg.start_sec:.4f}",
            "-t", f"{seg.duration_sec:.4f}",
            "-i", seg.source_path,
        ])

    filter_parts: List[str] = []
    concat_inputs: List[str] = []
    w, h = main_info.width, main_info.height
    if max_width > 0 and w > max_width:
        scale_factor = max_width / float(w)
        w = max_width - (max_width % 2)
        h = max(2, int(round(h * scale_factor)) - (int(round(h * scale_factor)) % 2))
    fps = round(main_info.fps, 3)

    font_path = "C\\:/Windows/Fonts/impact.ttf"
    has_impact = os.path.isfile("C:/Windows/Fonts/impact.ttf")
    font_size = max(48, int(h * 0.18))

    for idx, seg in enumerate(batch):
        v_filters = [
            f"scale={w}:{h}:force_original_aspect_ratio=decrease",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
            "setsar=1",
            f"fps={fps}",
            "format=yuv420p",
        ]

        eff = seg.effect
        if eff in ("blood_ritual", "red_flash"):
            v_filters.append(
                "colorbalance=rs=0.35:gs=-0.4:bs=-0.4:rm=0.75:gm=-0.5:bm=-0.5:rh=0.85,"
                "eq=contrast=2.1:brightness=-0.07:gamma=0.82,vignette=PI/3.2"
            )
        elif eff in ("abyss_invert", "invert"):
            v_filters.append(
                "negate,eq=contrast=1.95:saturation=0.25:brightness=-0.06,vignette=PI/3.2"
            )
        elif eff in ("necrotic_mono", "high_contrast"):
            v_filters.append(
                "hue=s=0,eq=contrast=2.5:brightness=-0.09:gamma=0.78,vignette=PI/3"
            )
        elif eff == "rgb_trauma":
            v_filters.append(
                "rgbashift=rh=-12:bh=12:rv=4:bv=-4,"
                "eq=contrast=1.85:brightness=-0.06:saturation=1.3,vignette=PI/3.2"
            )
        else:
            if threat_grade == "lethal":
                v_filters.append(
                    "eq=contrast=1.32:brightness=-0.05:saturation=0.75:gamma=0.86,vignette=PI/3.8"
                )
            elif threat_grade == "nightmare":
                v_filters.append(
                    "rgbashift=rh=-5:bh=5,eq=contrast=1.5:brightness=-0.07:saturation=0.55:gamma=0.8,vignette=PI/3.2"
                )
            elif threat_grade == "occult":
                v_filters.append(
                    "colorbalance=rm=0.22:gm=-0.18:bm=-0.18,"
                    "eq=contrast=1.45:brightness=-0.06:saturation=0.65:gamma=0.82,vignette=PI/3.3"
                )

        v_filters.append("setpts=PTS-STARTPTS")
        filter_parts.append(f"[{idx}:v]{','.join(v_filters)}[v{idx}]")
        concat_inputs.append(f"[v{idx}]")

        if include_sliced_audio:
            if seg.has_audio:
                extra_a = ""
                if demonic_audio:
                    extra_a = "asetrate=44100*0.86,aresample=44100,atempo=1.16279,acrusher=level_in=1:level_out=1:bits=9:mode=log:aa=1,"
                a_chain = (
                    f"[{idx}:a]{extra_a}aresample=44100:async=1,"
                    f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                    f"apad=whole_dur={seg.duration_sec:.4f},"
                    f"atrim=0:{seg.duration_sec:.4f},"
                    f"asetpts=PTS-STARTPTS[a{idx}]"
                )
            else:
                a_chain = (
                    f"anullsrc=r=44100:cl=stereo:d={seg.duration_sec:.4f},"
                    f"asetpts=PTS-STARTPTS[a{idx}]"
                )
            filter_parts.append(a_chain)
            concat_inputs.append(f"[a{idx}]")

    n = len(batch)
    if include_sliced_audio:
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[outv][outa]")
    else:
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=0[outv]")

    filter_complex = ";".join(filter_parts)

    cmd.extend(["-filter_complex", filter_complex, "-map", "[outv]"])
    if include_sliced_audio:
        cmd.extend(["-map", "[outa]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"])
    else:
        cmd.append("-an")

    cmd.extend([
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_file,
    ])
    return cmd


def render_subliminal_video(
    config: RenderConfig,
    segments: Optional[List[CutSegment]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> List[CutSegment]:
    """
    Execute the full subliminal cut splice render.
    """
    def report(pct: float, msg: str) -> None:
        if progress_callback:
            progress_callback(max(0.0, min(100.0, pct)), msg)

    report(2.0, "Probing video...")
    main_info = probe_video(config.input_path)
    secondary_info = probe_video(config.secondary_source_path) if config.secondary_source_path else None

    if segments is None:
        report(5.0, "Generating cut plan...")
        segments = generate_cut_plan(config, main_info, secondary_info)

    if not segments:
        raise ValueError("Cut plan produced 0 segments.")

    total_duration = sum(s.duration_sec for s in segments)
    include_sliced_audio = (config.audio_mode in ("slice", "demonic_slice")) and (
        main_info.has_audio or (secondary_info is not None and secondary_info.has_audio)
    )
    demonic_audio = config.audio_mode == "demonic_slice"

    BATCH_SIZE = 12
    batches = [segments[i:i + BATCH_SIZE] for i in range(0, len(segments), BATCH_SIZE)]
    num_batches = len(batches)

    os.makedirs(os.path.dirname(os.path.abspath(config.output_path)), exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="psyop_cut_")

    try:
        need_post_continuous_audio = (
            config.audio_mode == "continuous" and main_info.has_audio
        )

        if num_batches == 1 and not need_post_continuous_audio:
            if cancel_check and cancel_check():
                raise InterruptedError("Render cancelled by user.")
            report(15.0, f"Rendering {len(segments)} cuts ({total_duration:.1f}s)...")
            cmd = _build_batch_ffmpeg_cmd(
                batches[0],
                main_info,
                include_sliced_audio=include_sliced_audio,
                output_file=config.output_path,
                preset=config.preset,
                crf=config.crf,
                max_width=config.max_width,
                threat_grade=config.threat_grade,
                demonic_audio=demonic_audio,
            )
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_creation_flags(),
            )
            if res.returncode != 0:
                raise RuntimeError(f"FFmpeg render error:\n{res.stderr.strip()}")
            report(100.0, "Done.")
            return segments

        batch_files: List[str] = []
        for b_idx, batch in enumerate(batches):
            if cancel_check and cancel_check():
                raise InterruptedError("Render cancelled by user.")

            pct = 10.0 + (78.0 * b_idx / num_batches)
            report(
                pct,
                f"Rendering batch {b_idx + 1}/{num_batches} ({len(batch)} cuts)...",
            )
            chunk_path = os.path.join(temp_dir, f"chunk_{b_idx:04d}.mp4")
            cmd = _build_batch_ffmpeg_cmd(
                batch,
                main_info,
                include_sliced_audio=include_sliced_audio,
                output_file=chunk_path,
                preset=config.preset,
                crf=config.crf,
                max_width=config.max_width,
                threat_grade=config.threat_grade,
                demonic_audio=demonic_audio,
            )
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_creation_flags(),
            )
            if res.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg batch {b_idx + 1} failed:\n{res.stderr.strip()}"
                )
            batch_files.append(chunk_path)

        if cancel_check and cancel_check():
            raise InterruptedError("Render cancelled by user.")

        report(88.0, "Stitching output...")
        concat_list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for bf in batch_files:
                safe_path = bf.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        stitched_video = (
            os.path.join(temp_dir, "stitched_video.mp4")
            if need_post_continuous_audio
            else config.output_path
        )

        concat_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            stitched_video,
        ]
        res = subprocess.run(
            concat_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_creation_flags(),
        )
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed:\n{res.stderr.strip()}")

        if need_post_continuous_audio:
            report(94.0, "LOCKING CONTINUOUS CARRIER FREQUENCY...")
            mux_cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", stitched_video,
                "-stream_loop", "-1",
                "-i", config.input_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-t", f"{total_duration:.4f}",
                "-movflags", "+faststart",
                config.output_path,
            ]
            res = subprocess.run(
                mux_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_creation_flags(),
            )
            if res.returncode != 0:
                raise RuntimeError(f"FFmpeg audio mux failed:\n{res.stderr.strip()}")

        report(100.0, "PSYOP PAYLOAD ARMED.")
        return segments

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
