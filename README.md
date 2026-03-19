# VideoAdSnip

A tool to detect and remove advertisements from video files using scene detection and a web-based UI for easy selection.

## Features

- **Scene Detection**: Automatically detect scene changes in videos
- **Web-based UI**: Interactive interface to preview and select ad scenes
- **Batch Processing**: Process entire directories of video files
- **Thumbnail Preview**: Visual scene thumbnails at native aspect ratios
- **Video Processing**: Remove selected scenes and create clean output videos
- **Multi-format Support**: Works with MP4, MKV, AVI, MOV, WEBM, FLV, WMV

## Requirements

- Python 3.10+
- FFmpeg (must be in PATH)

## Installation

```bash
# Clone the repository
git clone https://github.com/amorlzu/VideoAdSnip.git
cd VideoAdSnip

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install the package
pip install -e .
```

## Usage

### Process a Single Video

```bash
videoadsnip "path/to/video.mp4"
```

This will:
1. Analyze the video and detect scenes
2. Launch a web UI at http://127.0.0.1:5000
3. Allow you to select which scenes are ads
4. Create a clean version of the video

### Process a Directory

```bash
videoadsnip "path/to/videos/"
```

This will scan all video files in the directory (excluding files ending with `_clean`) and present them in a foldable list in the web UI.

### Command Line Options

```
videoadsnip [OPTIONS] INPUT

Arguments:
  INPUT                 Input video file or directory

Options:
  -o, --output PATH     Output file path (default: input_clean.mp4)
  -w, --window FLOAT    Detection window in seconds from start (default: 120)
  --no-ui               Skip web UI, use auto-detection only
  --port INTEGER        Port for web UI (default: 5000)
  --no-browser          Don't auto-open browser for web UI
  -v, --verbose         Enable verbose output
```

### Auto Mode (No UI)

For batch processing without the web interface:

```bash
videoadsnip "path/to/video.mp4" --no-ui
```

## How It Works

1. **Scene Detection**: Uses content-based scene detection to identify distinct scenes in the video
2. **Thumbnail Extraction**: Extracts thumbnails from the start frame of each scene
3. **Web UI**: Displays scenes with thumbnails for easy identification
4. **Selection**: Click on scenes that are advertisements
5. **Processing**: Uses FFmpeg to remove selected segments and create a clean video

### Smart Encoding (Frame-Accurate Cuts)

VideoAdSnip uses a smart encoding approach that achieves frame-accurate cuts while minimizing re-encoding:

```
For each segment to keep (start_time → end_time):

┌─────────────────────────────────────────────────────────────┐
│  Original video                                             │
│  ├─keyframe─┼───────┼─keyframe─┼───────┼─keyframe─┼───────┤ │
│                        ↑                                    │
│                    start_time                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Smart cut result:                                          │
│  ├─ Re-encode ─┤├──────── Stream Copy ────────────────────┤ │
│  (partial GOP)     (from next keyframe to end_time)         │
└─────────────────────────────────────────────────────────────┘
```

**How it works:**
1. **Keyframe Detection**: Analyzes the video to find all keyframe (I-frame) positions
2. **Partial Re-encoding**: Only re-encodes from the cut point to the next keyframe (typically 1-2 seconds)
3. **Stream Copy**: Uses direct stream copy for content between keyframes (fast, no quality loss)
4. **Codec Matching**: Detects and matches the original codec (H.264, HEVC, AAC, etc.) for seamless concatenation

**Benefits:**
- ✅ Frame-accurate cuts (no extra frames from removed scenes)
- ✅ Fast processing (minimal re-encoding)
- ✅ Preserves original quality (stream copy for most content)
- ✅ Works with any codec supported by FFmpeg

## Output

Processed videos are saved with a `_clean` suffix appended to the original filename:

- `video.mp4` → `video_clean.mp4`

## Development

### Running Tests

```bash
pip install -e ".[dev]"
pytest
```

### Code Style

The project uses:
- Ruff for linting
- MyPy for type checking

## License

MIT
