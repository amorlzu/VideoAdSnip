"""Flask web application for VideoAdSnip scene selection UI."""

import hashlib
import json
import platform
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file

from videoadsnip.scene_detector import Scene, SceneDetector
from videoadsnip.processor import VideoProcessor, get_unique_output_path


def _browse_files_macos() -> list[str]:
    """Open file browser on macOS using osascript."""
    script = '''
    set theFiles to choose file with prompt "Select Video Files" of type {"public.movie"} with multiple selections allowed
    set thePaths to {}
    repeat with aFile in theFiles
        set end of thePaths to POSIX path of aFile
    end repeat
    return thePaths
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        # AppleScript returns paths separated by comma
        paths = [p.strip() for p in result.stdout.strip().split(", ")]
        return paths
    return []


def _browse_files_windows() -> list[str]:
    """Open file browser on Windows using PowerShell."""
    script = '''
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Select Video Files"
    $dialog.Filter = "Video Files (*.mp4;*.mkv;*.avi;*.mov;*.webm;*.flv;*.wmv)|*.mp4;*.mkv;*.avi;*.mov;*.webm;*.flv;*.wmv|All Files (*.*)|*.*"
    $dialog.Multiselect = $true
    if ($dialog.ShowDialog() -eq 'OK') {
        $dialog.FileNames -join '|'
    }
    '''
    result = subprocess.run(
        ["powershell", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().split("|")
    return []

app = Flask(__name__)

# Global state
video_files: list[Path] = []
current_video_hash: str | None = None
video_hashes: dict[str, Path] = {}  # hash -> Path mapping
video_scenes: dict[str, list[Scene]] = {}  # hash -> scenes
video_thumbnails: dict[str, Path] = {}  # hash -> thumbnail dir
max_duration: float = 120.0


@dataclass
class QueueItem:
    """Represents a video in the processing queue."""
    video_hash: str
    video_name: str
    ad_scenes: list[int]  # Scene indices to remove
    output_path: str | None = None
    status: str = "pending"  # pending, processing, completed, error
    error_message: str | None = None


@dataclass
class ProcessingQueue:
    """Queue for batch video processing."""
    items: list[QueueItem] = field(default_factory=list)
    is_processing: bool = False
    current_index: int = -1
    progress: float = 0.0

    def clear(self) -> None:
        """Clear all items from the queue."""
        self.items = []
        self.is_processing = False
        self.current_index = -1
        self.progress = 0.0


# Queue state
processing_queue = ProcessingQueue()
queue_lock = threading.Lock()


def get_video_hash(video_path: Path) -> str:
    """Generate a short hash for a video file path."""
    return hashlib.md5(str(video_path).encode('utf-8')).hexdigest()[:12]


# Analysis state
analysis_status: dict[str, dict[str, Any]] = {}  # video_hash -> status dict


def init_app_with_videos(files: list[Path], duration: float | None = None) -> None:
    """
    Initialize the web app with multiple video files.
    Scene detection runs in background - server starts immediately.

    Args:
        files: List of video file paths
        duration: Maximum duration to analyze per video
    """
    global video_files, current_video_hash, video_hashes, video_scenes, video_thumbnails, max_duration, analysis_status

    video_files = files
    max_duration = duration or 120.0

    # Initialize video hashes and status
    for video_file in files:
        video_hash = get_video_hash(video_file)
        video_hashes[video_hash] = video_file
        analysis_status[video_hash] = {
            "status": "pending",  # pending, analyzing, completed, error
            "progress": 0,
            "error": None,
        }

    # Set first video as current
    if files:
        current_video_hash = get_video_hash(files[0])

    # Start background analysis
    _start_background_analysis()


def _start_background_analysis() -> None:
    """Start analyzing videos in background (sequentially to avoid resource contention)."""
    thread = threading.Thread(
        target=_analyze_all_videos_sequentially,
        daemon=True,
    )
    thread.start()


def _analyze_all_videos_sequentially() -> None:
    """Analyze all videos sequentially in a background thread."""
    for video_file in video_files:
        video_hash = get_video_hash(video_file)
        _analyze_video(video_file, video_hash)


def _analyze_video(video_file: Path, video_hash: str) -> None:
    """Analyze a single video (runs in background thread)."""
    global video_scenes, video_thumbnails, analysis_status

    try:
        analysis_status[video_hash]["status"] = "analyzing"
        analysis_status[video_hash]["progress"] = 10

        scene_detector = SceneDetector()

        detection_result = scene_detector.detect(
            video_file,
            start_time=0.0,
            end_time=max_duration,
        )

        analysis_status[video_hash]["progress"] = 70

        # Extract thumbnails
        thumbnail_dir = Path(tempfile.mkdtemp(prefix=f"videoadsnip_thumbs_"))
        updated_scenes = scene_detector.extract_thumbnails(video_file, detection_result.scenes, thumbnail_dir)

        video_scenes[video_hash] = updated_scenes
        video_thumbnails[video_hash] = thumbnail_dir

        analysis_status[video_hash]["status"] = "completed"
        analysis_status[video_hash]["progress"] = 100

    except Exception as e:
        analysis_status[video_hash]["status"] = "error"
        analysis_status[video_hash]["error"] = str(e)


@app.route("/")
def index() -> str:
    """Render the main page."""
    return render_template("index.html")


@app.route("/api/videos")
def get_videos() -> Response:
    """Get list of available videos with analysis status."""
    videos_data = []
    for vf in video_files:
        video_hash = get_video_hash(vf)
        status = analysis_status.get(video_hash, {})

        processor = VideoProcessor()
        try:
            info = processor.get_video_info(vf)
            videos_data.append({
                "id": video_hash,
                "name": vf.name,
                "path": str(vf),
                "duration": info["duration"],
                "resolution": f"{info['video']['width']}x{info['video']['height']}",
                "scene_count": len(video_scenes.get(video_hash, [])),
                "analysis_status": status.get("status", "pending"),
                "analysis_progress": status.get("progress", 0),
                "analysis_error": status.get("error"),
            })
        except Exception:
            videos_data.append({
                "id": video_hash,
                "name": vf.name,
                "path": str(vf),
                "error": True,
                "analysis_status": status.get("status", "pending"),
                "analysis_progress": status.get("progress", 0),
            })
    return jsonify({"videos": videos_data, "current": current_video_hash})


@app.route("/api/analysis/status")
def get_analysis_status() -> Response:
    """Get analysis status for all videos."""
    status_data = {}
    for video_hash, status in analysis_status.items():
        status_data[video_hash] = {
            "status": status.get("status", "pending"),
            "progress": status.get("progress", 0),
            "error": status.get("error"),
            "scene_count": len(video_scenes.get(video_hash, [])),
        }

    # Check if any are still analyzing
    any_analyzing = any(s.get("status") == "analyzing" for s in analysis_status.values())

    return jsonify({
        "videos": status_data,
        "any_analyzing": any_analyzing,
        "all_completed": all(s.get("status") == "completed" for s in analysis_status.values()),
    })


@app.route("/api/select/<video_hash>", methods=["POST"])
def select_video(video_hash: str) -> Response:
    """Select a video to work with."""
    global current_video_hash
    if video_hash not in video_hashes:
        return jsonify({"error": "Video not found"}), 404
    current_video_hash = video_hash
    return jsonify({"success": True, "video": video_hash})


@app.route("/api/scenes")
def get_scenes() -> Response:
    """Get detected scenes as JSON."""
    if not current_video_hash:
        return jsonify({"error": "No video selected"}), 400

    video_path = video_hashes.get(current_video_hash)
    scenes = video_scenes.get(current_video_hash, [])

    scenes_data = []
    for scene in scenes:
        scene_dict = {
            "index": scene.index,
            "start_time": scene.start_time,
            "end_time": scene.end_time,
            "start_frame": scene.start_frame,
            "end_frame": scene.end_frame,
            "duration": scene.duration,
        }
        if scene.thumbnail_path:
            scene_dict["thumbnail_url"] = f"/thumbnails/{current_video_hash}/{scene.index}"
        scenes_data.append(scene_dict)

    processor = VideoProcessor()
    info = processor.get_video_info(video_path)

    return jsonify({
        "scenes": scenes_data,
        "video_path": str(video_path),
        "video_name": video_path.name,
        "duration": info["duration"],
    })


@app.route("/thumbnails/<video_hash>/<int:scene_index>")
def get_thumbnail(video_hash: str, scene_index: int) -> Response:
    """Serve a thumbnail image."""
    scenes = video_scenes.get(video_hash, [])
    if 0 <= scene_index < len(scenes):
        scene = scenes[scene_index]
        if scene.thumbnail_path and scene.thumbnail_path.exists():
            return send_file(str(scene.thumbnail_path), mimetype="image/jpeg")
    return "Not found", 404


@app.route("/api/process", methods=["POST"])
def process_selections() -> Response:
    """Process user selections and create output video."""
    if not current_video_hash:
        return jsonify({"error": "No video selected"}), 400

    video_path = video_hashes.get(current_video_hash)
    if not video_path:
        return jsonify({"error": "Video not found"}), 404

    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    ad_scenes = data.get("ad_scenes", [])
    output_path = data.get("output_path")

    scenes = video_scenes.get(current_video_hash, [])

    # Calculate ad segments based on selected scene indices
    segments_to_remove: list[tuple[float, float]] = []
    for idx in ad_scenes:
        if 0 <= idx < len(scenes):
            scene = scenes[idx]
            segments_to_remove.append((scene.start_time, scene.end_time))

    if not output_path:
        # Default output path (auto-increment if exists)
        output_path = str(get_unique_output_path(video_path))

    try:
        processor = VideoProcessor()
        processor.remove_segments(video_path, Path(output_path), segments_to_remove)
        return jsonify({"success": True, "output_path": output_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/preview/<int:scene_index>")
def preview_scene(scene_index: int) -> Response:
    """Get a video preview for a specific scene."""
    if not current_video_hash:
        return "Not found", 404

    scenes = video_scenes.get(current_video_hash, [])

    if not (0 <= scene_index < len(scenes)):
        return "Not found", 404

    scene = scenes[scene_index]
    if scene.thumbnail_path and scene.thumbnail_path.exists():
        return send_file(str(scene.thumbnail_path), mimetype="image/jpeg")

    return "Not found", 404


# ============ Path API Endpoints ============

@app.route("/api/add_path", methods=["POST"])
def add_path() -> Response:
    """Add video file(s) by path without uploading. For local use only."""
    global video_files, video_hashes, analysis_status, current_video_hash

    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    path_str = data.get("path", "").strip()
    if not path_str:
        return jsonify({"success": False, "error": "No path provided"}), 400

    input_path = Path(path_str).expanduser()

    if not input_path.exists():
        return jsonify({"success": False, "error": f"Path does not exist: {path_str}"}), 400

    allowed_extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}

    # Collect video files from the path
    added_files: list[Path] = []
    if input_path.is_file():
        if input_path.suffix.lower() in allowed_extensions:
            added_files.append(input_path)
        else:
            return jsonify({
                "success": False,
                "error": f"Not a video file. Supported: {', '.join(allowed_extensions)}"
            }), 400
    else:
        # Scan directory for video files
        for ext in allowed_extensions:
            for file_path in input_path.glob(f"*{ext}"):
                # Skip _clean files
                if not file_path.stem.endswith("_clean"):
                    added_files.append(file_path)
        added_files.sort(key=lambda x: x.name.lower())

    if not added_files:
        return jsonify({"success": False, "error": "No video files found at path"}), 400

    # Add files to processing list
    added_count = 0
    for video_file in added_files:
        video_hash = get_video_hash(video_file)

        # Skip if already in list
        if video_hash in video_hashes:
            continue

        video_hashes[video_hash] = video_file
        video_files.append(video_file)
        analysis_status[video_hash] = {
            "status": "pending",
            "progress": 0,
            "error": None,
        }
        added_count += 1

        # Start background analysis
        thread = threading.Thread(
            target=_analyze_video,
            args=(video_file, video_hash),
            daemon=True,
        )
        thread.start()

    # Set first added video as current if none selected
    if current_video_hash is None and added_files:
        current_video_hash = get_video_hash(added_files[0])

    return jsonify({
        "success": True,
        "added_count": added_count,
        "total_found": len(added_files),
        "files": [f.name for f in added_files[:10]],  # First 10 filenames
    })


@app.route("/api/browse/files")
def browse_files() -> Response:
    """Open native file picker to select video files."""
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            paths = _browse_files_macos()
        elif system == "Windows":
            paths = _browse_files_windows()
        else:
            return jsonify({"error": "Unsupported platform", "paths": []}), 400

        return jsonify({"paths": paths})
    except Exception as e:
        return jsonify({"error": str(e), "paths": []}), 500


def _browse_folder_macos() -> str:
    """Open folder browser on macOS using osascript."""
    script = '''
    set theFolder to choose folder with prompt "Select Folder Containing Videos"
    return POSIX path of theFolder
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return ""


def _browse_folder_windows() -> str:
    """Open folder browser on Windows using PowerShell."""
    script = '''
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select Folder Containing Videos"
    if ($dialog.ShowDialog() -eq 'OK') {
        $dialog.SelectedPath
    }
    '''
    result = subprocess.run(
        ["powershell", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return ""


@app.route("/api/browse/folder")
def browse_folder() -> Response:
    """Open native folder picker."""
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            path = _browse_folder_macos()
        elif system == "Windows":
            path = _browse_folder_windows()
        else:
            return jsonify({"error": "Unsupported platform", "path": ""}), 400

        return jsonify({"path": path})
    except Exception as e:
        return jsonify({"error": str(e), "path": ""}), 500


# ============ Queue API Endpoints ============

@app.route("/api/queue")
def get_queue() -> Response:
    """Get the current queue status."""
    with queue_lock:
        items_data = []
        for i, item in enumerate(processing_queue.items):
            items_data.append({
                "index": i,
                "video_hash": item.video_hash,
                "video_name": item.video_name,
                "ad_scenes": item.ad_scenes,
                "ad_scene_count": len(item.ad_scenes),
                "output_path": item.output_path,
                "status": item.status,
                "error_message": item.error_message,
            })

        # Find next unqueued video
        queued_hashes = {item.video_hash for item in processing_queue.items}
        next_video_hash = None
        for vf in video_files:
            vh = get_video_hash(vf)
            if vh not in queued_hashes:
                next_video_hash = vh
                break

        return jsonify({
            "items": items_data,
            "is_processing": processing_queue.is_processing,
            "current_index": processing_queue.current_index,
            "progress": processing_queue.progress,
            "total": len(processing_queue.items),
            "next_video": next_video_hash,
        })


@app.route("/api/queue/add", methods=["POST"])
def add_to_queue() -> Response:
    """Add current video with selected scenes to the queue."""
    if not current_video_hash:
        return jsonify({"error": "No video selected"}), 400

    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    ad_scenes = data.get("ad_scenes", [])
    if not ad_scenes:
        return jsonify({"error": "No scenes selected"}), 400

    video_path = video_hashes.get(current_video_hash)
    if not video_path:
        return jsonify({"error": "Video not found"}), 404

    with queue_lock:
        # Check if already in queue
        for item in processing_queue.items:
            if item.video_hash == current_video_hash:
                # Update existing item
                item.ad_scenes = ad_scenes
                item.status = "pending"
                item.error_message = None
                return jsonify({
                    "success": True,
                    "updated": True,
                    "queue_length": len(processing_queue.items),
                })

        # Add new item
        item = QueueItem(
            video_hash=current_video_hash,
            video_name=video_path.name,
            ad_scenes=ad_scenes,
        )
        processing_queue.items.append(item)

    # Find next video to auto-select
    queued_hashes = {item.video_hash for item in processing_queue.items}
    next_video_hash = None
    for vf in video_files:
        vh = get_video_hash(vf)
        if vh not in queued_hashes:
            next_video_hash = vh
            break

    return jsonify({
        "success": True,
        "queue_length": len(processing_queue.items),
        "next_video": next_video_hash,
    })


@app.route("/api/queue/<int:index>", methods=["DELETE"])
def remove_from_queue(index: int) -> Response:
    """Remove an item from the queue."""
    with queue_lock:
        if 0 <= index < len(processing_queue.items):
            processing_queue.items.pop(index)
            return jsonify({"success": True, "queue_length": len(processing_queue.items)})
        return jsonify({"error": "Item not found"}), 404


@app.route("/api/queue/clear", methods=["POST"])
def clear_queue() -> Response:
    """Clear all items from the queue."""
    with queue_lock:
        processing_queue.clear()
    return jsonify({"success": True})


@app.route("/api/queue/start", methods=["POST"])
def start_queue() -> Response:
    """Start processing the queue."""
    with queue_lock:
        if processing_queue.is_processing:
            return jsonify({"error": "Queue is already processing"}), 400

        if not processing_queue.items:
            return jsonify({"error": "Queue is empty"}), 400

        processing_queue.is_processing = True
        processing_queue.current_index = 0
        processing_queue.progress = 0.0

        # Reset all items to pending
        for item in processing_queue.items:
            item.status = "pending"
            item.output_path = None
            item.error_message = None

    # Start processing in background thread
    thread = threading.Thread(target=_process_queue)
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "total": len(processing_queue.items)})


@app.route("/api/queue/status")
def get_queue_status() -> Response:
    """Get the current processing status."""
    with queue_lock:
        completed = sum(1 for item in processing_queue.items if item.status == "completed")
        errors = sum(1 for item in processing_queue.items if item.status == "error")

        return jsonify({
            "is_processing": processing_queue.is_processing,
            "current_index": processing_queue.current_index,
            "progress": processing_queue.progress,
            "total": len(processing_queue.items),
            "completed": completed,
            "errors": errors,
        })


def _process_queue() -> None:
    """Process all items in the queue (runs in background thread)."""
    global processing_queue

    while True:
        with queue_lock:
            if processing_queue.current_index >= len(processing_queue.items):
                # All done
                processing_queue.is_processing = False
                processing_queue.progress = 100.0
                break

            item = processing_queue.items[processing_queue.current_index]
            item.status = "processing"
            current_idx = processing_queue.current_index
            total = len(processing_queue.items)

        try:
            video_path = video_hashes.get(item.video_hash)
            if not video_path:
                raise ValueError("Video not found")

            scenes = video_scenes.get(item.video_hash, [])

            # Calculate segments to remove
            segments_to_remove: list[tuple[float, float]] = []
            for idx in item.ad_scenes:
                if 0 <= idx < len(scenes):
                    scene = scenes[idx]
                    segments_to_remove.append((scene.start_time, scene.end_time))

            # Generate output path (auto-increment if exists)
            output_path = str(get_unique_output_path(video_path))

            # Process video
            processor = VideoProcessor()
            processor.remove_segments(video_path, Path(output_path), segments_to_remove)

            with queue_lock:
                item.status = "completed"
                item.output_path = output_path
                processing_queue.progress = ((current_idx + 1) / total) * 100
                processing_queue.current_index += 1

        except Exception as e:
            with queue_lock:
                item.status = "error"
                item.error_message = str(e)
                processing_queue.current_index += 1
                processing_queue.progress = ((processing_queue.current_index) / len(processing_queue.items)) * 100


# ============ Server ============

def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    """Run the Flask development server."""
    app.run(host=host, port=port, debug=debug)
