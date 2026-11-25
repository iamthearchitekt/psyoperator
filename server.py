"""
PSYOPERATOR - Classified Psychological Operations Subliminal Conditioning Terminal
Zero-emoji cold intelligence / MKULTRA / DARPA retinal conditioning interface + FFmpeg engine.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from engine import (
    DEFAULT_DIRECTIVES,
    RenderConfig,
    generate_cut_plan,
    probe_video,
    render_subliminal_video,
)

app = FastAPI(title="PSYOPERATOR")

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "renders"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

RENDER_STATE = {
    "active": False,
    "percent": 0.0,
    "message": "STANDBY // AWAITING CONDITIONING EXECUTION",
}


class PlanRequest(BaseModel):
    input_path: str
    mode: str = "supercut"
    num_cuts: int = 50
    min_cut_ms: int = 35
    max_cut_ms: int = 130
    base_duration_sec: float = 15.0
    audio_mode: str = "slice"
    threat_grade: str = "lethal"
    stutter_chance: float = 0.25
    fx_chance: float = 0.45
    directive_chance: float = 0.0
    directives_csv: str = "OBEY, SUBMIT, COMPLY, NO ESCAPE, WATCH, CONSUME, FORGET, FEAR"
    seed: Optional[int] = None


def _parse_directives(csv_str: str) -> List[str]:
    words = [w.strip().upper() for w in (csv_str or "").split(",") if w.strip()]
    return words if words else list(DEFAULT_DIRECTIVES)


def _info_dict(path_str: str, display_name: Optional[str] = None) -> dict:
    info = probe_video(path_str)
    return {
        "path": path_str,
        "filename": display_name or Path(path_str).name,
        "duration": info.duration,
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "has_audio": info.has_audio,
        "file_size_mb": info.file_size_mb,
        "frame_duration_ms": info.frame_duration_ms,
    }


@app.get("/api/init_state")
def get_init_state():
    uploads = sorted(
        [p for p in UPLOADS_DIR.glob("*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    latest_video = None
    if uploads:
        try:
            latest_video = _info_dict(str(uploads[0]))
        except Exception:
            pass

    renders = sorted(
        [
            p
            for p in OUTPUTS_DIR.glob("*.mp4")
            if p.is_file() and not p.name.startswith("synthetic_source")
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    latest_render = None
    if renders:
        try:
            r_info = probe_video(str(renders[0]))
            latest_render = {
                "output_path": str(renders[0]),
                "output_filename": renders[0].name,
                "video_url": f"/api/video/{renders[0].name}",
                "output_duration": round(r_info.duration, 2),
            }
        except Exception:
            pass

    return {
        "latest_video": latest_video,
        "latest_render": latest_render,
    }


@app.post("/api/upload")
def upload_video(file: UploadFile = File(...)):
    ext = Path(file.filename or "video.mp4").suffix or ".mp4"
    safe_stem = (
        "".join(c for c in Path(file.filename or "video").stem if c.isalnum() or c in ("-", "_"))
        or "video"
    )
    dest = UPLOADS_DIR / f"{safe_stem}_{int(time.time()) % 100000}{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f, length=1024 * 1024 * 4)
    try:
        return _info_dict(str(dest), display_name=Path(file.filename or dest.name).name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/progress")
def get_render_progress():
    return RENDER_STATE


@app.post("/api/plan")
def preview_plan(req: PlanRequest):
    if not os.path.isfile(req.input_path):
        raise HTTPException(status_code=404, detail="Input video not found")
    info = probe_video(req.input_path)
    cfg = RenderConfig(
        input_path=req.input_path,
        output_path="preview.mp4",
        mode=req.mode,
        num_cuts=req.num_cuts,
        min_cut_ms=req.min_cut_ms,
        max_cut_ms=req.max_cut_ms,
        base_duration_sec=req.base_duration_sec,
        audio_mode=req.audio_mode,
        threat_grade=req.threat_grade,
        stutter_chance=req.stutter_chance,
        fx_chance=req.fx_chance,
        directive_chance=req.directive_chance,
        directives=_parse_directives(req.directives_csv),
        seed=req.seed,
    )
    segs = generate_cut_plan(cfg, main_info=info)
    return {
        "source_duration": info.duration,
        "total_duration": sum(s.duration_sec for s in segs),
        "segments": [
            {
                "start_sec": s.start_sec,
                "duration_sec": s.duration_sec,
                "is_subliminal": s.is_subliminal,
                "effect": s.effect,
                "directive_text": s.directive_text,
            }
            for s in segs
        ],
    }


@app.post("/api/render")
def run_render(req: PlanRequest):
    if not os.path.isfile(req.input_path):
        raise HTTPException(status_code=404, detail="Input video not found")
    p = Path(req.input_path)
    out_name = f"{p.stem}_PSYOP_{int(time.time()) % 100000}.mp4"
    out_path = OUTPUTS_DIR / out_name

    cfg = RenderConfig(
        input_path=req.input_path,
        output_path=str(out_path),
        mode=req.mode,
        num_cuts=req.num_cuts,
        min_cut_ms=req.min_cut_ms,
        max_cut_ms=req.max_cut_ms,
        base_duration_sec=req.base_duration_sec,
        audio_mode=req.audio_mode,
        threat_grade=req.threat_grade,
        stutter_chance=req.stutter_chance,
        fx_chance=req.fx_chance,
        directive_chance=req.directive_chance,
        directives=_parse_directives(req.directives_csv),
        seed=req.seed,
    )

    def _on_prog(pct: float, msg: str) -> None:
        RENDER_STATE["active"] = True
        RENDER_STATE["percent"] = round(pct, 1)
        RENDER_STATE["message"] = msg

    RENDER_STATE["active"] = True
    RENDER_STATE["percent"] = 2.0
    RENDER_STATE["message"] = "INITIALIZING RETINAL CONDITIONING SEQUENCE..."
    t0 = time.perf_counter()
    try:
        segs = render_subliminal_video(cfg, progress_callback=_on_prog)
    except Exception as exc:
        RENDER_STATE["active"] = False
        RENDER_STATE["message"] = f"FATAL: {exc}"
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        RENDER_STATE["active"] = False
        RENDER_STATE["percent"] = 100.0

    elapsed = time.perf_counter() - t0
    out_info = probe_video(str(out_path))
    return {
        "output_path": str(out_path),
        "output_filename": out_name,
        "video_url": f"/api/video/{out_name}",
        "elapsed_sec": round(elapsed, 2),
        "num_segments": len(segs),
        "output_duration": round(out_info.duration, 2),
    }


@app.get("/api/video/{filename}")
def serve_rendered_video(filename: str):
    target = OUTPUTS_DIR / Path(filename).name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Rendered file not found")
    return FileResponse(str(target), media_type="video/mp4", filename=target.name)


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>PSYOPERATOR // DEPT. OF PSYCHOLOGICAL OPERATIONS [MK-ULTRA]</title>
<style>
  :root {
    --void: #020203;
    --panel: #060507;
    --border-dim: #26060b;
    --border-blood: #6e0714;
    --crimson: #e6001f;
    --crimson-bright: #ff0026;
    --crimson-dark: #4d000a;
    --bone: #ded8d8;
    --ash: #786b6d;
    --amber: #d48800;
  }
  @keyframes pulseThreat {
    0%, 100% { box-shadow: 0 0 22px rgba(230, 0, 31, 0.25), inset 0 0 16px rgba(140, 0, 18, 0.25); }
    50% { box-shadow: 0 0 38px rgba(255, 0, 38, 0.55), inset 0 0 28px rgba(230, 0, 31, 0.45); }
  }
  @keyframes blinkLed {
    0%, 48% { opacity: 1; }
    50%, 100% { opacity: 0.15; }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background-color: var(--void);
    background-image:
      radial-gradient(ellipse at 50% 0%, rgba(120, 0, 15, 0.22) 0%, rgba(2, 2, 3, 0.98) 70%);
    color: var(--bone);
    font-family: "Consolas", "JetBrains Mono", "Lucida Console", "Courier New", monospace;
    padding: 14px 22px 30px 22px;
    max-width: 1040px;
    margin: 0 auto;
    min-height: 100vh;
    position: relative;
  }
  .dossier-strip {
    background: #0a0204;
    border: 1px solid var(--border-blood);
    border-left: 4px solid var(--crimson);
    color: var(--crimson);
    font-size: 10px;
    font-weight: 900;
    letter-spacing: 2.2px;
    padding: 6px 12px;
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    text-transform: uppercase;
  }
  .led {
    display: inline-block;
    width: 7px;
    height: 7px;
    background: var(--crimson-bright);
    box-shadow: 0 0 10px var(--crimson-bright);
    margin-right: 8px;
    animation: blinkLed 1.1s infinite;
  }
  .redacted {
    background: var(--bone);
    color: var(--bone);
    padding: 0 4px;
    transition: 0.2s;
    cursor: crosshair;
    user-select: none;
  }
  .redacted:hover {
    background: var(--crimson-dark);
    color: #fff;
  }
  .header-panel {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #060304;
    border: 1px solid var(--border-blood);
    padding: 12px 16px;
    margin-bottom: 12px;
    position: relative;
  }
  .brand-cluster {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .eye-sigil {
    width: 52px;
    height: 52px;
    flex-shrink: 0;
    filter: drop-shadow(0 0 8px rgba(255, 0, 38, 0.65));
  }
  .title-stack h1 {
    font-size: 27px;
    font-weight: 900;
    letter-spacing: 7px;
    color: #ffffff;
    text-shadow: -2px 0 var(--crimson), 2px 0 #3d0008;
    line-height: 1.05;
  }
  .title-sub {
    font-size: 10px;
    color: var(--crimson);
    letter-spacing: 2.4px;
    font-weight: 800;
    margin-top: 4px;
  }
  .eeg-box {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
  }
  #eegCanvas {
    width: 240px;
    height: 40px;
    background: #030102;
    border: 1px solid #3d060d;
  }
  .eeg-label {
    font-size: 9px;
    color: var(--ash);
    letter-spacing: 1.6px;
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--border-dim);
    border-left: 3px solid var(--border-blood);
    padding: 13px 16px;
    margin-bottom: 11px;
    position: relative;
    box-shadow: inset 0 0 32px rgba(0, 0, 0, 0.95);
  }
  .card::before {
    content: "+";
    position: absolute;
    top: 4px;
    right: 8px;
    color: var(--crimson);
    font-size: 11px;
    opacity: 0.55;
  }
  .dropzone {
    border: 1px dashed var(--border-blood);
    border-left: 4px solid var(--crimson);
    background: linear-gradient(180deg, #0c0305 0%, #040102 100%);
    text-align: center;
    padding: 16px;
    cursor: crosshair;
    transition: 0.15s;
  }
  .dropzone.dragover, .dropzone:hover {
    border-color: var(--crimson-bright);
    background: #160307;
    box-shadow: 0 0 28px rgba(255, 0, 38, 0.2), inset 0 0 22px rgba(255, 0, 38, 0.14);
  }
  .drop-tag {
    font-size: 10px;
    letter-spacing: 3px;
    color: var(--crimson);
    font-weight: 900;
    margin-bottom: 4px;
  }
  .drop-title {
    font-size: 15px;
    font-weight: 900;
    margin-bottom: 5px;
    color: #ffffff;
    letter-spacing: 1.5px;
  }
  .drop-meta {
    font-size: 11px;
    color: var(--ash);
    margin-bottom: 11px;
    letter-spacing: 0.6px;
  }
  .upload-bar-wrap {
    height: 6px;
    background: #040102;
    border: 1px solid var(--border-blood);
    overflow: hidden;
    margin: 10px auto;
    max-width: 520px;
    display: none;
  }
  .upload-bar-fill {
    height: 100%;
    width: 0%;
    background: var(--crimson-bright);
    box-shadow: 0 0 12px var(--crimson-bright);
    transition: width 0.12s;
  }
  .btn-row { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
  button {
    background: #100306;
    color: var(--bone);
    border: 1px solid #4a0710;
    padding: 7px 14px;
    font-family: inherit;
    font-weight: 800;
    font-size: 11px;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    cursor: pointer;
    transition: 0.12s;
  }
  button:hover {
    border-color: var(--crimson-bright);
    background: #290309;
    color: #fff;
    box-shadow: 0 0 14px rgba(255, 0, 38, 0.35);
  }
  .mode-row { display: flex; gap: 10px; margin-bottom: 11px; }
  .mode-btn {
    flex: 1;
    padding: 11px;
    font-size: 11px;
    letter-spacing: 1.5px;
    background: #080304;
    color: var(--ash);
    border: 1px solid #2b060c;
  }
  .mode-btn.active {
    background: linear-gradient(90deg, #2e0208, #120104);
    border-color: var(--crimson-bright);
    border-left: 4px solid var(--crimson-bright);
    color: #ffffff;
    box-shadow: 0 0 18px rgba(255, 0, 38, 0.25);
  }
  .preset-row { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
  .preset-chip {
    font-size: 10px;
    padding: 6px 10px;
    background: #0b0305;
    border-color: #38060d;
    color: #c2b2b4;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
  }
  .directive-row {
    display: grid;
    grid-template-columns: 3fr 1fr;
    gap: 10px;
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid #240509;
  }
  .field label {
    display: block;
    font-size: 10px;
    font-weight: 900;
    color: var(--crimson);
    margin-bottom: 5px;
    letter-spacing: 1.4px;
    text-transform: uppercase;
  }
  .field input, .field select {
    width: 100%;
    background: #040102;
    border: 1px solid #38070e;
    color: #ffffff;
    padding: 8px 10px;
    font-family: inherit;
    font-weight: 700;
    font-size: 12px;
    outline: none;
  }
  .field input:focus, .field select:focus {
    border-color: var(--crimson-bright);
    box-shadow: 0 0 10px rgba(255, 0, 38, 0.35);
  }
  .timeline-bar {
    height: 38px;
    background: #020101;
    border: 1px solid #3d060d;
    display: flex;
    overflow: hidden;
    margin-top: 8px;
    position: relative;
  }
  .seg { height: 100%; border-right: 1px solid rgba(0, 0, 0, 0.8); position: relative; }
  .legend-row {
    display: flex;
    gap: 14px;
    margin-top: 6px;
    font-size: 9px;
    color: var(--ash);
    letter-spacing: 1.2px;
  }
  .swatch {
    display: inline-block;
    width: 9px;
    height: 9px;
    margin-right: 5px;
    vertical-align: middle;
  }
  .render-btn {
    width: 100%;
    height: 62px;
    background: linear-gradient(180deg, #8a0012 0%, #380006 55%, #160002 100%);
    border: 2px solid var(--crimson-bright);
    font-family: inherit;
    font-size: 17px;
    font-weight: 900;
    letter-spacing: 4.5px;
    color: #ffffff;
    text-transform: uppercase;
    cursor: crosshair;
    margin-top: 4px;
    animation: pulseThreat 2.2s infinite;
    text-shadow: 0 0 12px rgba(255, 0, 38, 0.95);
  }
  .render-btn:hover {
    background: linear-gradient(180deg, #bf001a 0%, #54000a 55%, #240004 100%);
    letter-spacing: 5.5px;
  }
  .render-btn:disabled {
    background: repeating-linear-gradient(
      -45deg,
      #1a0104,
      #1a0104 14px,
      #330309 14px,
      #330309 28px
    );
    color: var(--crimson-bright);
    cursor: wait;
  }
  .result-box {
    margin-top: 13px;
    display: none;
    border: 1px solid var(--crimson-bright);
    border-left: 4px solid var(--crimson-bright);
    background: #050102;
    box-shadow: 0 0 32px rgba(255, 0, 38, 0.22);
  }
  video {
    width: 100%;
    max-height: 420px;
    background: #000;
    border: 1px solid #3a060d;
    margin-top: 10px;
  }
  .stats-badge {
    background: #160205;
    border: 1px solid #4d0711;
    color: var(--crimson-bright);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1.2px;
    padding: 3px 9px;
  }
</style>
</head>
<body>
  <div class="dossier-strip">
    <span><span class="led"></span>DEPT. OF PSYCHOLOGICAL OPERATIONS // PROJECT <span class="redacted" title="Click/Hover to Declassify">MK-MONARCH</span></span>
    <span>CLEARANCE: EYES ONLY // COGNITIVE INTRUSION TERMINAL</span>
  </div>

  <div class="header-panel">
    <div class="brand-cluster">
      <!-- Cold Surveillance Panopticon / Retinal Crosshair Vector Sigil -->
      <svg class="eye-sigil" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <polygon points="50,6 95,86 5,86" stroke="#ff0026" stroke-width="2.5" fill="rgba(120,0,16,0.12)"/>
        <path d="M16 56 C32 34, 68 34, 84 56 C68 78, 32 78, 16 56 Z" stroke="#ded8d8" stroke-width="2.2" fill="#050102"/>
        <circle cx="50" cy="56" r="13" stroke="#ff0026" stroke-width="2.2" fill="rgba(255,0,38,0.18)"/>
        <circle cx="50" cy="56" r="4.5" fill="#ff0026"/>
        <line x1="50" y1="22" x2="50" y2="38" stroke="#ff0026" stroke-width="1.5"/>
        <line x1="50" y1="74" x2="50" y2="90" stroke="#ff0026" stroke-width="1.5"/>
        <line x1="8" y1="56" x2="24" y2="56" stroke="#ff0026" stroke-width="1.5"/>
        <line x1="76" y1="56" x2="92" y2="56" stroke="#ff0026" stroke-width="1.5"/>
      </svg>
      <div class="title-stack">
        <h1>PSYOPERATOR</h1>
        <div class="title-sub">SUB-THRESHOLD RETINAL &amp; PSYCHOACOUSTIC SPLICING SYSTEM</div>
      </div>
    </div>
    <div class="eeg-box">
      <canvas id="eegCanvas" width="240" height="40"></canvas>
      <div class="eeg-label">NEURAL ENTRAINMENT // TACHISTOSCOPIC PULSE</div>
    </div>
  </div>

  <div class="card dropzone" id="dropzone">
    <input type="file" id="fileInput" accept="video/*" style="display:none">
    <div class="drop-tag">[ CARRIER MEDIA INGESTION ]</div>
    <div class="drop-title" id="videoTitle">DROP TARGET VIDEO FOOTAGE HERE — OR CLICK TO INGEST</div>
    <div class="drop-meta" id="videoMeta">RAW STREAM INTERCEPT • MP4 / MOV / MKV / WEBM / AVI • SUB-FRAME EXTRACTION</div>
    <div class="upload-bar-wrap" id="uploadBarWrap">
      <div class="upload-bar-fill" id="uploadBarFill"></div>
    </div>
    <div class="btn-row">
      <button onclick="event.stopPropagation(); document.getElementById('fileInput').click()">[ + SELECT TARGET CARRIER FILE ]</button>
    </div>
  </div>

  <div class="card">
    <div class="mode-row">
      <button class="mode-btn active" id="modeSupercut" onclick="setMode('supercut')">
        [ MODE 01 // TACHISTOSCOPIC ASSAULT ] — STITCH VIOLENT RANDOM MICRO-SEQUENCES
      </button>
      <button class="mode-btn" id="modeInsert" onclick="setMode('subliminal_insert')">
        [ MODE 02 // COVERT SLEEPER INSERTS ] — SPLICE 1–3 FRAME FLASHES INTO CARRIER TIMELINE
      </button>
    </div>
    <div class="preset-row">
      <span style="font-size:10px;color:var(--crimson);font-weight:900;letter-spacing:1.5px;">DOCTRINE PROTOCOLS:</span>
      <button class="preset-chip" onclick="applyPreset('supercut',55,35,110,30,45,0,'lethal','slice')">[ PROTOCOL: BLACKOUT BLITZ ]</button>
      <button class="preset-chip" onclick="applyPreset('supercut',80,33,45,20,60,0,'nightmare','demonic_slice')">[ PROTOCOL: MK-ULTRA 1-FRAME ]</button>
      <button class="preset-chip" onclick="applyPreset('subliminal_insert',16,33,65,15,50,0,'occult','slice')">[ PROTOCOL: SLEEPER AGENT ]</button>
      <button class="preset-chip" onclick="applyPreset('supercut',65,40,135,45,70,0,'nightmare','demonic_slice')">[ PROTOCOL: SENSORY OVERLOAD ]</button>
    </div>
  </div>

  <div class="card">
    <div class="grid">
      <div class="field">
        <label>SPLICE VECTOR COUNT</label>
        <input type="number" id="numCuts" value="50" min="3" max="160" onchange="refreshPlan()">
      </div>
      <div class="field">
        <label>MIN RETINAL EXPOSURE (MS)</label>
        <input type="number" id="minMs" value="35" min="20" max="2000" step="5" onchange="refreshPlan()">
      </div>
      <div class="field">
        <label>MAX RETINAL EXPOSURE (MS)</label>
        <input type="number" id="maxMs" value="130" min="25" max="3000" step="10" onchange="refreshPlan()">
      </div>
      <div class="field">
        <label>OPTICAL THREAT GRADING</label>
        <select id="threatGrade" onchange="refreshPlan()">
          <option value="lethal">LETHAL // CRUSHED ABYSS + VIGNETTE</option>
          <option value="nightmare">NIGHTMARE // RGB TRAUMA + NOIR</option>
          <option value="occult">OCCULT // ARTERIAL + NEGATIVE</option>
          <option value="raw">RAW // UNGRADED CARRIER</option>
        </select>
      </div>
      <div class="field">
        <label>PSYCHOACOUSTIC MODE</label>
        <select id="audioMode">
          <option value="slice">HARD-CUT GLITCH (SLICE AUDIO)</option>
          <option value="demonic_slice">PITCH-DROPPED BITCRUSH TRAUMA</option>
          <option value="continuous">CONTINUOUS CARRIER TRACK</option>
          <option value="mute">SENSORY DEPRIVATION (MUTE)</option>
        </select>
      </div>
      <div class="field">
        <label>STUTTER ECHO PROBABILITY %</label>
        <input type="number" id="stutterPct" value="25" min="0" max="75" step="5" onchange="refreshPlan()">
      </div>
      <div class="field">
        <label>OPTICAL TRAUMA FLASH %</label>
        <input type="number" id="fxPct" value="45" min="0" max="100" step="5" onchange="refreshPlan()">
      </div>
      <div class="field">
        <label>CARRIER WINDOW (SEC)</label>
        <input type="number" id="baseDur" value="15" min="0" max="600" step="5" onchange="refreshPlan()">
      </div>
    </div>
  </div>

  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
      <span style="font-size:10px;font-weight:900;color:var(--crimson);letter-spacing:1.8px;">[ RETINAL CONDITIONING TIMELINE VECTOR ]</span>
      <span class="stats-badge" id="planStats">NO CARRIER LOCKED</span>
      <button onclick="rerollSeed()" style="padding:4px 10px;font-size:10px;">[ MUTATE ENTROPY SEED ]</button>
    </div>
    <div class="timeline-bar" id="timelineBar"></div>
    <div class="legend-row">
      <span><span class="swatch" style="background:#7a0012"></span>SUBLIMINAL CUT</span>
      <span><span class="swatch" style="background:#ff0026"></span>ARTERIAL / RGB TRAUMA</span>
      <span><span class="swatch" style="background:#e2dada"></span>ABYSS NEGATIVE INVERT</span>
      <span><span class="swatch" style="background:#171215"></span>CARRIER STREAM</span>
    </div>
  </div>

  <button class="render-btn" id="renderBtn" onclick="renderVideo()">[ EXECUTE PSYOP TRANSMISSION // SPLICE SEQUENCE ]</button>

  <div class="card result-box" id="resultBox">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
      <span id="resultSummary" style="font-weight:900;color:var(--crimson-bright);letter-spacing:1.2px;font-size:11px;">TRANSMISSION ARMED</span>
      <a id="downloadLink" href="#" download style="color:#fff;background:#3b0209;border:1px solid var(--crimson-bright);padding:6px 14px;text-decoration:none;font-weight:900;font-size:11px;letter-spacing:1.4px;">[ EXTRACT CONDITIONED MP4 ]</a>
    </div>
    <video id="outputVideo" controls autoplay playsinline></video>
  </div>

<script>
  let currentPath = null;
  let currentMode = 'supercut';
  let currentSeed = Math.floor(Math.random() * 999999);
  let activeUploadPromise = null;
  let isRendering = false;

  // Live Neural Entrainment / Tachistoscopic Oscilloscope
  (function initOscilloscope() {
    const canvas = document.getElementById('eegCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let phase = 0;
    function draw() {
      ctx.fillStyle = 'rgba(3, 1, 2, 0.28)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.beginPath();
      ctx.strokeStyle = isRendering ? '#ff0026' : '#a80018';
      ctx.lineWidth = isRendering ? 1.8 : 1.3;
      const mid = canvas.height / 2;
      for (let x = 0; x < canvas.width; x++) {
        let y = mid + Math.sin((x * 0.09) + phase) * 5 + Math.cos((x * 0.23) - phase * 1.7) * 3;
        const spikeChance = isRendering ? 0.91 : 0.975;
        if (Math.random() > spikeChance) {
          y += (Math.random() - 0.5) * (isRendering ? 34 : 24);
        }
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      phase += isRendering ? 0.35 : 0.14;
      requestAnimationFrame(draw);
    }
    draw();
  })();

  const dz = document.getElementById('dropzone');
  const fi = document.getElementById('fileInput');

  dz.addEventListener('click', () => fi.click());
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', async e => {
    e.preventDefault();
    dz.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
      await uploadFile(e.dataTransfer.files[0]);
    }
  });
  fi.addEventListener('change', async () => {
    if (fi.files.length > 0) await uploadFile(fi.files[0]);
  });

  function uploadFile(file) {
    const btn = document.getElementById('renderBtn');
    const barWrap = document.getElementById('uploadBarWrap');
    const barFill = document.getElementById('uploadBarFill');
    barWrap.style.display = 'block';
    barFill.style.width = '0%';
    btn.disabled = true;

    activeUploadPromise = new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload', true);

      xhr.upload.onprogress = e => {
        if (e.lengthComputable) {
          const pct = Math.round((e.loaded / e.total) * 100);
          const mbLoaded = (e.loaded / (1024 * 1024)).toFixed(1);
          const mbTotal = (e.total / (1024 * 1024)).toFixed(1);
          barFill.style.width = pct + '%';
          document.getElementById('videoTitle').textContent =
            `[ INTERCEPTING ${file.name.toUpperCase()} // ${pct}% (${mbLoaded} / ${mbTotal} MB) ]`;
          btn.textContent = `[ INGESTING TARGET STREAM... ${pct}% ]`;
        }
      };

      xhr.onload = () => {
        barWrap.style.display = 'none';
        btn.disabled = false;
        btn.textContent = '[ EXECUTE PSYOP TRANSMISSION // SPLICE SEQUENCE ]';
        activeUploadPromise = null;
        if (xhr.status >= 200 && xhr.status < 300) {
          const info = JSON.parse(xhr.responseText);
          setVideoInfo(info);
          resolve(info);
        } else {
          alert('Ingestion failed: ' + xhr.responseText);
          reject(new Error(xhr.responseText));
        }
      };

      xhr.onerror = () => {
        barWrap.style.display = 'none';
        btn.disabled = false;
        btn.textContent = '[ EXECUTE PSYOP TRANSMISSION // SPLICE SEQUENCE ]';
        activeUploadPromise = null;
        alert('Network error while ingesting file.');
        reject(new Error('Network error'));
      };

      const fd = new FormData();
      fd.append('file', file);
      xhr.send(fd);
    });

    return activeUploadPromise;
  }

  function setVideoInfo(info) {
    currentPath = info.path;
    document.getElementById('videoTitle').textContent = 'CARRIER LOCKED // ' + info.filename.toUpperCase();
    document.getElementById('videoMeta').textContent =
      `${info.width}×${info.height} • ${info.fps.toFixed(2)} FPS (1 FRAME = ${info.frame_duration_ms.toFixed(1)} MS) • DURATION: ${info.duration.toFixed(2)}S • ${info.file_size_mb.toFixed(1)} MB`;
    rerollSeed();
  }

  function setMode(m) {
    currentMode = m;
    document.getElementById('modeSupercut').classList.toggle('active', m === 'supercut');
    document.getElementById('modeInsert').classList.toggle('active', m === 'subliminal_insert');
    refreshPlan();
  }

  function applyPreset(mode, cuts, minMs, maxMs, stutter, fx, dirPct, grade, audio) {
    document.getElementById('numCuts').value = cuts;
    document.getElementById('minMs').value = minMs;
    document.getElementById('maxMs').value = maxMs;
    document.getElementById('stutterPct').value = stutter;
    document.getElementById('fxPct').value = fx;
    if (grade) document.getElementById('threatGrade').value = grade;
    if (audio) document.getElementById('audioMode').value = audio;
    setMode(mode);
  }

  function rerollSeed() {
    currentSeed = Math.floor(Math.random() * 9999999);
    refreshPlan();
  }

  function buildPayload() {
    return {
      input_path: currentPath,
      mode: currentMode,
      num_cuts: parseInt(document.getElementById('numCuts').value || '50'),
      min_cut_ms: parseInt(document.getElementById('minMs').value || '35'),
      max_cut_ms: parseInt(document.getElementById('maxMs').value || '130'),
      base_duration_sec: parseFloat(document.getElementById('baseDur').value || '15'),
      audio_mode: document.getElementById('audioMode').value,
      threat_grade: document.getElementById('threatGrade').value,
      stutter_chance: parseInt(document.getElementById('stutterPct').value || '0') / 100.0,
      fx_chance: parseInt(document.getElementById('fxPct').value || '0') / 100.0,
      directive_chance: 0.0,
      directives_csv: '',
      seed: currentSeed
    };
  }

  async function refreshPlan() {
    if (!currentPath) return;
    const res = await fetch('/api/plan', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(buildPayload())
    });
    if (!res.ok) return;
    const data = await res.json();
    const bar = document.getElementById('timelineBar');
    bar.innerHTML = '';
    const total = data.total_duration || 1;
    let subCount = 0;
    let fxCount = 0;
    let dirCount = 0;
    data.segments.forEach(s => {
      if (s.is_subliminal) subCount++;
      if (s.effect && s.effect !== 'none') fxCount++;
      if (s.directive_text) dirCount++;
      const div = document.createElement('div');
      div.className = 'seg';
      div.style.width = Math.max(0.4, (s.duration_sec / total) * 100) + '%';
      if (s.directive_text) {
        div.style.background = '#d48800';
        div.title = `DIRECTIVE: "${s.directive_text}" (${Math.round(s.duration_sec*1000)}ms)`;
      } else if (!s.is_subliminal) {
        div.style.background = '#171215';
      } else if (s.effect === 'abyss_invert') {
        div.style.background = '#e2dada';
      } else if (s.effect === 'necrotic_mono') {
        div.style.background = '#5a4e50';
      } else if (s.effect === 'rgb_trauma' || s.effect === 'blood_ritual') {
        div.style.background = '#ff0026';
      } else {
        div.style.background = '#7a0012';
      }
      bar.appendChild(div);
    });
    document.getElementById('planStats').textContent =
      `${subCount} CUTS • ${fxCount} TRAUMA FLASHES • PAYLOAD: ${data.total_duration.toFixed(2)}S`;
  }

  function showRenderOutput(data) {
    document.getElementById('resultBox').style.display = 'block';
    const summaryText = data.elapsed_sec
      ? `[ PAYLOAD ARMED ] ${data.num_segments} VECTORS (${data.output_duration}S) ENCODED IN ${data.elapsed_sec}S -> ${data.output_path}`
      : `[ PAYLOAD ARMED ] DURATION: ${data.output_duration}S -> ${data.output_path}`;
    document.getElementById('resultSummary').textContent = summaryText;
    const vid = document.getElementById('outputVideo');
    vid.src = data.video_url + '?t=' + Date.now();
    vid.play().catch(() => {});
    const dl = document.getElementById('downloadLink');
    dl.href = data.video_url;
    dl.download = data.output_filename;
  }

  async function renderVideo() {
    if (activeUploadPromise) {
      await activeUploadPromise;
    }
    if (!currentPath) {
      fi.click();
      return;
    }
    const btn = document.getElementById('renderBtn');
    btn.disabled = true;
    isRendering = true;
    btn.textContent = '[ ENCODING RETINAL CONDITIONING PAYLOAD... 0% ]';

    const pollTimer = setInterval(async () => {
      try {
        const pr = await fetch('/api/progress');
        if (pr.ok) {
          const st = await pr.json();
          if (st.active) {
            btn.textContent = `[ ${st.message.toUpperCase()} // ${Math.round(st.percent)}% ]`;
          }
        }
      } catch (_) {}
    }, 350);

    try {
      const res = await fetch('/api/render', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(buildPayload())
      });
      if (!res.ok) {
        alert('Execution failed: ' + await res.text());
        return;
      }
      const data = await res.json();
      showRenderOutput(data);
      rerollSeed();
    } finally {
      clearInterval(pollTimer);
      isRendering = false;
      btn.disabled = false;
      btn.textContent = '[ EXECUTE PSYOP TRANSMISSION // SPLICE SEQUENCE ]';
    }
  }

  window.addEventListener('DOMContentLoaded', () => {});
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
