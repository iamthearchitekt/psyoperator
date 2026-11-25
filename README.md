# PSYOPERATOR

Lightweight desktop subliminal cut & rapid supercut video renderer built with Electron and FFmpeg.

## Features
- **Rapid Supercut Mode** — Extracts random frame-snapped micro-sequences (down to 1 frame / ~33 ms) and splices them into a fast-cut sequence.
- **Subliminal Inserts Mode** — Keeps the base clip playing and injects 1–3 frame flashes from random timestamps throughout the timeline.
- **Visual Grades & Flash FX** — Dark + Vignette, RGB Split + Noir, Crimson + Invert, or Original (Raw), plus configurable Stutter % and Flash FX %.
- **Audio Modes** — Slice Audio with Cuts, Pitch-Drop + Crush, Continuous Audio, or Mute.

## Requirements
- [FFmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe` available on system `PATH`)
- Node.js 18+ (for development / building from source)

## Development & Build
```bash
npm install
npm start
```

Build the branded Windows NSIS installer (`dist/PSYOPERATOR-Setup-1.0.0.exe`):
```bash
npm run dist
```
