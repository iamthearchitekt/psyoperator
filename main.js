/**
 * PSYOPERATOR — Electron Main Process & Native FFmpeg Splicing Engine
 * Zero-copy local video ingestion + multi-batch fast-seek FFmpeg splicing.
 */

const { app, BrowserWindow, ipcMain, dialog, shell, screen } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');
const { pathToFileURL } = require('url');

function getRendersDir(inputPath) {
  try {
    const videosDir = path.join(app.getPath('videos'), 'PSYOPERATOR');
    fs.mkdirSync(videosDir, { recursive: true });
    return videosDir;
  } catch (_) {
    const fallback = inputPath ? path.dirname(inputPath) : os.tmpdir();
    return fallback;
  }
}

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 980,
    height: 615,
    minWidth: 820,
    minHeight: 575,
    backgroundColor: '#020203',
    autoHideMenuBar: true,
    icon: path.join(__dirname, 'psyoperator.ico'),
    title: 'PSYOPERATOR',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'index.html'));
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// --- Helper: Run a child process and collect stdout/stderr ---
function runProcess(cmd, args) {
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, { windowsHide: true });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (d) => { stdout += d.toString(); });
    proc.stderr.on('data', (d) => { stderr += d.toString(); });
    proc.on('error', (err) => reject(err));
    proc.on('close', (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${cmd} exited with code ${code}:\n${stderr.trim()}`));
    });
  });
}

// --- Probe video with ffprobe ---
async function probeVideo(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    throw new Error(`Video file not found: ${filePath}`);
  }
  const { stdout } = await runProcess('ffprobe', [
    '-v', 'quiet',
    '-print_format', 'json',
    '-show_format',
    '-show_streams',
    filePath
  ]);
  const data = JSON.parse(stdout || '{}');
  const streams = data.streams || [];
  const fmt = data.format || {};

  const vStream = streams.find((s) => s.codec_type === 'video');
  if (!vStream) throw new Error(`No video stream found in ${filePath}`);
  const aStream = streams.find((s) => s.codec_type === 'audio');

  const duration = parseFloat(fmt.duration || vStream.duration || '0');
  if (duration <= 0.05) throw new Error(`Video duration too short (${duration}s)`);

  let width = parseInt(vStream.width || '1280', 10);
  let height = parseInt(vStream.height || '720', 10);
  width = Math.max(2, width - (width % 2));
  height = Math.max(2, height - (height % 2));

  let fps = 30.0;
  const fpsStr = vStream.avg_frame_rate || vStream.r_frame_rate || '30/1';
  if (fpsStr.includes('/')) {
    const [num, den] = fpsStr.split('/').map(Number);
    if (den > 0 && num > 0) fps = num / den;
  } else if (parseFloat(fpsStr) > 0) {
    fps = parseFloat(fpsStr);
  }
  fps = Math.min(Math.max(fps, 10.0), 120.0);

  const stat = fs.statSync(filePath);
  const sizeBytes = parseFloat(fmt.size || stat.size);

  return {
    path: filePath,
    filename: path.basename(filePath),
    duration,
    width,
    height,
    fps,
    has_audio: Boolean(aStream),
    codec_name: vStream.codec_name || 'h264',
    file_size_mb: sizeBytes / (1024 * 1024),
    frame_duration_ms: 1000.0 / Math.max(fps, 1.0)
  };
}

// --- Deterministic PRNG (Mulberry32) so timeline preview matches rendered cuts ---
function createRng(seed) {
  let a = (seed >>> 0) || (Date.now() >>> 0);
  return function () {
    let t = (a += 0x6D2B79F5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randUniform(rng, min, max) {
  return min + rng() * (max - min);
}

function randChoice(rng, arr) {
  return arr[Math.floor(rng() * arr.length)];
}

function pickEffect(rng, fxChance, threatGrade) {
  if (fxChance <= 0 || rng() >= fxChance) return 'none';
  if (threatGrade === 'occult') {
    return randChoice(rng, ['blood_ritual', 'abyss_invert', 'blood_ritual', 'necrotic_mono']);
  }
  if (threatGrade === 'nightmare') {
    return randChoice(rng, ['rgb_trauma', 'necrotic_mono', 'abyss_invert', 'blood_ritual']);
  }
  return randChoice(rng, ['blood_ritual', 'abyss_invert', 'necrotic_mono', 'rgb_trauma']);
}

function generateCutPlan(cfg, info) {
  const rng = createRng(cfg.seed || Date.now());
  const frameS = 1.0 / Math.max(info.fps, 24.0);
  let minS = Math.max(0.020, Math.min(cfg.min_cut_ms, cfg.max_cut_ms) / 1000.0);
  let maxS = Math.max(minS, Math.max(cfg.min_cut_ms, cfg.max_cut_ms) / 1000.0);
  minS = Math.max(minS, frameS * 0.95);
  maxS = Math.max(maxS, minS);

  const segments = [];

  if (cfg.mode === 'supercut') {
    const count = Math.max(1, cfg.num_cuts);
    let i = 0;
    while (i < count) {
      let dur = randUniform(rng, minS, maxS);
      const frames = Math.max(1, Math.round(dur / frameS));
      dur = frames * frameS;

      const maxStart = Math.max(0.0, info.duration - dur - 0.02);
      const start = maxStart > 0 ? randUniform(rng, 0.0, maxStart) : 0.0;

      const seg = {
        source_path: info.path,
        start_sec: Number(start.toFixed(4)),
        duration_sec: Number(dur.toFixed(4)),
        is_subliminal: true,
        effect: pickEffect(rng, cfg.fx_chance, cfg.threat_grade),
        has_audio: info.has_audio
      };
      segments.push(seg);
      i++;

      if (cfg.stutter_chance > 0 && rng() < cfg.stutter_chance && i < count) {
        const maxRep = Math.min(3, count - i);
        const repeats = 1 + Math.floor(rng() * maxRep);
        for (let r = 0; r < repeats; r++) {
          segments.push({
            source_path: seg.source_path,
            start_sec: seg.start_sec,
            duration_sec: seg.duration_sec,
            is_subliminal: true,
            effect: pickEffect(rng, Math.max(cfg.fx_chance, 0.5), cfg.threat_grade),
            has_audio: seg.has_audio
          });
          i++;
        }
      }
    }
  } else {
    let baseDur = info.duration;
    if (cfg.base_duration_sec > 0 && cfg.base_duration_sec < info.duration) {
      baseDur = cfg.base_duration_sec;
    }
    const numFlashes = Math.max(1, cfg.num_cuts);
    const slotLen = baseDur / (numFlashes + 0.5);
    let cursor = 0.0;

    for (let idx = 0; idx < numFlashes; idx++) {
      const minGap = Math.max(frameS * 2, slotLen * 0.35);
      const maxGap = Math.max(minGap, slotLen * 1.45);
      let normalDur = randUniform(rng, minGap, maxGap);
      if (cursor + normalDur >= baseDur - minS) {
        normalDur = Math.max(frameS, (baseDur - cursor) * 0.5);
      }
      if (normalDur >= frameS) {
        segments.push({
          source_path: info.path,
          start_sec: Number(cursor.toFixed(4)),
          duration_sec: Number(normalDur.toFixed(4)),
          is_subliminal: false,
          effect: 'none',
          has_audio: info.has_audio
        });
        cursor += normalDur;
      }

      let flashDur = randUniform(rng, minS, maxS);
      const flashFrames = Math.max(1, Math.round(flashDur / frameS));
      flashDur = flashFrames * frameS;

      const maxFlashStart = Math.max(0.0, info.duration - flashDur - 0.02);
      let flashStart = maxFlashStart > 0 ? randUniform(rng, 0.0, maxFlashStart) : 0.0;
      if (info.duration > 2.0) {
        for (let t = 0; t < 5; t++) {
          const candidate = randUniform(rng, 0.0, maxFlashStart);
          if (Math.abs(candidate - cursor) > Math.min(1.5, info.duration * 0.25)) {
            flashStart = candidate;
            break;
          }
        }
      }

      const flashSeg = {
        source_path: info.path,
        start_sec: Number(flashStart.toFixed(4)),
        duration_sec: Number(flashDur.toFixed(4)),
        is_subliminal: true,
        effect: pickEffect(rng, cfg.fx_chance, cfg.threat_grade),
        has_audio: info.has_audio
      };
      segments.push(flashSeg);

      if (cfg.stutter_chance > 0 && rng() < cfg.stutter_chance) {
        segments.push({
          source_path: flashSeg.source_path,
          start_sec: flashSeg.start_sec,
          duration_sec: flashSeg.duration_sec,
          is_subliminal: true,
          effect: pickEffect(rng, Math.max(cfg.fx_chance, 0.5), cfg.threat_grade),
          has_audio: flashSeg.has_audio
        });
      }

      cursor = Math.min(baseDur, cursor + flashDur);
      if (cursor >= baseDur - frameS) break;
    }

    const remaining = baseDur - cursor;
    if (remaining >= frameS * 2) {
      segments.push({
        source_path: info.path,
        start_sec: Number(cursor.toFixed(4)),
        duration_sec: Number(remaining.toFixed(4)),
        is_subliminal: false,
        effect: 'none',
        has_audio: info.has_audio
      });
    }
  }

  return segments;
}

function buildBatchFfmpegArgs(batch, info, includeSlicedAudio, outputFile, threatGrade, demonicAudio) {
  const args = ['-y', '-hide_banner', '-loglevel', 'error'];

  for (const seg of batch) {
    args.push(
      '-threads', '2',
      '-ss', seg.start_sec.toFixed(4),
      '-t', seg.duration_sec.toFixed(4),
      '-i', seg.source_path
    );
  }

  let w = info.width;
  let h = info.height;
  const maxWidth = 1920;
  if (w > maxWidth) {
    const scaleFactor = maxWidth / w;
    w = maxWidth - (maxWidth % 2);
    const rawH = Math.round(h * scaleFactor);
    h = Math.max(2, rawH - (rawH % 2));
  }
  const fps = Number(info.fps.toFixed(3));

  const filterParts = [];
  const concatInputs = [];

  batch.forEach((seg, idx) => {
    const vFilters = [
      `scale=${w}:${h}:force_original_aspect_ratio=decrease`,
      `pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2`,
      'setsar=1',
      `fps=${fps}`,
      'format=yuv420p'
    ];

    const eff = seg.effect;
    if (eff === 'blood_ritual') {
      vFilters.push(
        'colorbalance=rs=0.35:gs=-0.4:bs=-0.4:rm=0.75:gm=-0.5:bm=-0.5:rh=0.85,' +
        'eq=contrast=2.1:brightness=-0.07:gamma=0.82,vignette=PI/3.2'
      );
    } else if (eff === 'abyss_invert') {
      vFilters.push('negate,eq=contrast=1.95:saturation=0.25:brightness=-0.06,vignette=PI/3.2');
    } else if (eff === 'necrotic_mono') {
      vFilters.push('hue=s=0,eq=contrast=2.5:brightness=-0.09:gamma=0.78,vignette=PI/3');
    } else if (eff === 'rgb_trauma') {
      vFilters.push(
        'rgbashift=rh=-12:bh=12:rv=4:bv=-4,' +
        'eq=contrast=1.85:brightness=-0.06:saturation=1.3,vignette=PI/3.2'
      );
    } else {
      if (threatGrade === 'lethal') {
        vFilters.push('eq=contrast=1.32:brightness=-0.05:saturation=0.75:gamma=0.86,vignette=PI/3.8');
      } else if (threatGrade === 'nightmare') {
        vFilters.push('rgbashift=rh=-5:bh=5,eq=contrast=1.5:brightness=-0.07:saturation=0.55:gamma=0.8,vignette=PI/3.2');
      } else if (threatGrade === 'occult') {
        vFilters.push(
          'colorbalance=rm=0.22:gm=-0.18:bm=-0.18,' +
          'eq=contrast=1.45:brightness=-0.06:saturation=0.65:gamma=0.82,vignette=PI/3.3'
        );
      }
    }

    vFilters.push('setpts=PTS-STARTPTS');
    filterParts.push(`[${idx}:v]${vFilters.join(',')}[v${idx}]`);
    concatInputs.push(`[v${idx}]`);

    if (includeSlicedAudio) {
      if (seg.has_audio) {
        const extraA = demonicAudio
          ? 'asetrate=44100*0.86,aresample=44100,atempo=1.16279,acrusher=level_in=1:level_out=1:bits=9:mode=log:aa=1,'
          : '';
        filterParts.push(
          `[${idx}:a]${extraA}aresample=44100:async=1,` +
          `aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,` +
          `apad=whole_dur=${seg.duration_sec.toFixed(4)},` +
          `atrim=0:${seg.duration_sec.toFixed(4)},` +
          `asetpts=PTS-STARTPTS[a${idx}]`
        );
      } else {
        filterParts.push(
          `anullsrc=r=44100:cl=stereo:d=${seg.duration_sec.toFixed(4)},asetpts=PTS-STARTPTS[a${idx}]`
        );
      }
      concatInputs.push(`[a${idx}]`);
    }
  });

  const n = batch.length;
  if (includeSlicedAudio) {
    filterParts.push(`${concatInputs.join('')}concat=n=${n}:v=1:a=1[outv][outa]`);
  } else {
    filterParts.push(`${concatInputs.join('')}concat=n=${n}:v=1:a=0[outv]`);
  }

  args.push('-filter_complex', filterParts.join(';'), '-map', '[outv]');
  if (includeSlicedAudio) {
    args.push('-map', '[outa]', '-c:a', 'aac', '-b:a', '192k', '-ar', '44100', '-ac', '2');
  } else {
    args.push('-an');
  }

  args.push(
    '-c:v', 'libx264',
    '-preset', 'ultrafast',
    '-crf', '20',
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    outputFile
  );
  return args;
}

// --- IPC Handlers ---
ipcMain.handle('dialog:openVideo', async () => {
  const res = await dialog.showOpenDialog(mainWindow, {
    title: 'SELECT TARGET CARRIER VIDEO',
    properties: ['openFile'],
    filters: [
      { name: 'Video Files', extensions: ['mp4', 'mov', 'mkv', 'webm', 'avi', 'm4v', 'wmv', 'flv'] },
      { name: 'All Files', extensions: ['*'] }
    ]
  });
  if (res.canceled || !res.filePaths.length) return null;
  return await probeVideo(res.filePaths[0]);
});

ipcMain.handle('video:probePath', async (_event, filePath) => {
  return await probeVideo(filePath);
});

ipcMain.handle('video:generatePlan', async (_event, req) => {
  const info = await probeVideo(req.input_path);
  const segs = generateCutPlan(req, info);
  return {
    source_duration: info.duration,
    total_duration: segs.reduce((acc, s) => acc + s.duration_sec, 0),
    segments: segs
  };
});

ipcMain.handle('video:render', async (event, req) => {
  const sendProg = (percent, message) => {
    event.sender.send('render:progress', { percent, message });
  };

  const t0 = Date.now();
  sendProg(3, 'PROBING VIDEO...');
  const info = await probeVideo(req.input_path);
  const segments = generateCutPlan(req, info);
  if (!segments.length) throw new Error('Cut plan generated 0 segments');

  const totalDuration = segments.reduce((acc, s) => acc + s.duration_sec, 0);
  const includeSlicedAudio = (req.audio_mode === 'slice' || req.audio_mode === 'demonic_slice') && info.has_audio;
  const demonicAudio = req.audio_mode === 'demonic_slice';
  const needContinuousAudio = req.audio_mode === 'continuous' && info.has_audio;

  const stem = path.basename(req.input_path, path.extname(req.input_path));
  const outName = `${stem}_PSYOP_${Date.now() % 100000}.mp4`;
  const outPath = path.join(getRendersDir(req.input_path), outName);

  const BATCH_SIZE = 12;
  const batches = [];
  for (let i = 0; i < segments.length; i += BATCH_SIZE) {
    batches.push(segments.slice(i, i + BATCH_SIZE));
  }

  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'psyop_electron_'));
  try {
    if (batches.length === 1 && !needContinuousAudio) {
      sendProg(20, `SPLICING ${segments.length} CUTS (${totalDuration.toFixed(1)}S)...`);
      const args = buildBatchFfmpegArgs(
        batches[0], info, includeSlicedAudio, outPath, req.threat_grade, demonicAudio
      );
      await runProcess('ffmpeg', args);
    } else {
      const chunkFiles = [];
      for (let bIdx = 0; bIdx < batches.length; bIdx++) {
        const pct = Math.round(10 + (76 * bIdx) / batches.length);
        sendProg(pct, `RENDERING BATCH ${bIdx + 1}/${batches.length} (${batches[bIdx].length} CUTS)...`);
        const chunkPath = path.join(tempDir, `chunk_${String(bIdx).padStart(4, '0')}.mp4`);
        const args = buildBatchFfmpegArgs(
          batches[bIdx], info, includeSlicedAudio, chunkPath, req.threat_grade, demonicAudio
        );
        await runProcess('ffmpeg', args);
        chunkFiles.push(chunkPath);
      }

      sendProg(88, 'STITCHING OUTPUT...');
      const concatListPath = path.join(tempDir, 'concat_list.txt');
      const listContent = chunkFiles
        .map((cf) => `file '${cf.replace(/\\/g, '/').replace(/'/g, "'\\''")}'`)
        .join('\n');
      fs.writeFileSync(concatListPath, listContent, 'utf8');

      const stitchedPath = needContinuousAudio ? path.join(tempDir, 'stitched.mp4') : outPath;
      await runProcess('ffmpeg', [
        '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'concat', '-safe', '0',
        '-i', concatListPath,
        '-c', 'copy',
        '-movflags', '+faststart',
        stitchedPath
      ]);

      if (needContinuousAudio) {
        sendProg(94, 'MUXING AUDIO...');
        await runProcess('ffmpeg', [
          '-y', '-hide_banner', '-loglevel', 'error',
          '-i', stitchedPath,
          '-stream_loop', '-1',
          '-i', req.input_path,
          '-map', '0:v:0',
          '-map', '1:a:0',
          '-c:v', 'copy',
          '-c:a', 'aac', '-b:a', '192k',
          '-t', totalDuration.toFixed(4),
          '-movflags', '+faststart',
          outPath
        ]);
      }
    }

    sendProg(100, 'DONE.');
    const outInfo = await probeVideo(outPath);
    const elapsedSec = ((Date.now() - t0) / 1000).toFixed(2);

    return {
      output_path: outPath,
      output_filename: outName,
      video_url: pathToFileURL(outPath).href,
      elapsed_sec: Number(elapsedSec),
      num_segments: segments.length,
      output_duration: Number(outInfo.duration.toFixed(2))
    };
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

ipcMain.handle('shell:revealFile', (_event, filePath) => {
  if (filePath && fs.existsSync(filePath)) {
    shell.showItemInFolder(path.normalize(filePath));
  }
});

ipcMain.handle('shell:openFile', (_event, filePath) => {
  if (filePath && fs.existsSync(filePath)) {
    shell.openPath(path.normalize(filePath));
  }
});

ipcMain.handle('window:expandForResult', () => {
  if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isMaximized()) return;
  const [curW, curH] = mainWindow.getSize();
  const display = screen.getDisplayMatching(mainWindow.getBounds());
  const maxH = display ? display.workAreaSize.height - 24 : 940;
  const targetH = Math.min(920, maxH);
  if (curH < targetH) {
    mainWindow.setSize(curW, targetH, true);
  }
});
