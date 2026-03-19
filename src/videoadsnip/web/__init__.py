"""Flask web application for VideoAdSnip scene selection UI."""

import hashlib
import tempfile
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from videoadsnip.scene_detector import Scene, SceneDetector
from videoadsnip.processor import VideoProcessor

app = Flask(__name__)

# Global state
video_files: list[Path] = []
current_video_hash: str | None = None
video_hashes: dict[str, Path] = {}  # hash -> Path mapping
video_scenes: dict[str, list[Scene]] = {}  # hash -> scenes
video_thumbnails: dict[str, Path] = {}  # hash -> thumbnail dir
max_duration: float = 120.0


def get_video_hash(video_path: Path) -> str:
    """Generate a short hash for a video file path."""
    return hashlib.md5(str(video_path).encode('utf-8')).hexdigest()[:12]


def init_app_with_videos(files: list[Path], duration: float | None = None) -> None:
    """
    Initialize the web app with multiple video files.

    Args:
        files: List of video file paths
        duration: Maximum duration to analyze per video
    """
    global video_files, current_video_hash, video_hashes, video_scenes, video_thumbnails, max_duration

    video_files = files
    max_duration = duration or 120.0

    # Detect scenes for all videos
    scene_detector = SceneDetector()
    for video_file in files:
        video_hash = get_video_hash(video_file)
        video_hashes[video_hash] = video_file

        detection_result = scene_detector.detect(
            video_file,
            start_time=0.0,
            end_time=max_duration,
        )

        # Extract thumbnails and update scenes with thumbnail paths
        thumbnail_dir = Path(tempfile.mkdtemp(prefix=f"videoadsnip_thumbs_"))
        updated_scenes = scene_detector.extract_thumbnails(video_file, detection_result.scenes, thumbnail_dir)

        video_scenes[video_hash] = updated_scenes
        video_thumbnails[video_hash] = thumbnail_dir

    # Set first video as current
    if files:
        current_video_hash = get_video_hash(files[0])


@app.route("/")
def index() -> str:
    """Render the main page."""
    return render_template("index.html")


@app.route("/api/videos")
def get_videos() -> Response:
    """Get list of available videos."""
    videos_data = []
    for vf in video_files:
        video_hash = get_video_hash(vf)
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
            })
        except Exception:
            videos_data.append({
                "id": video_hash,
                "name": vf.name,
                "path": str(vf),
                "error": True,
            })
    return jsonify({"videos": videos_data, "current": current_video_hash})


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
        # Default output path
        output_path = str(video_path.with_stem(video_path.stem + "_clean"))

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


def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    """Run the Flask development server."""
    app.run(host=host, port=port, debug=debug)
