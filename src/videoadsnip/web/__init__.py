"""Flask web application for VideoAdSnip scene selection UI."""

import tempfile
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from videoadsnip.scene_detector import Scene, SceneDetector
from videoadsnip.processor import VideoProcessor

app = Flask(__name__)

# Global state
video_files: list[Path] = []
current_video: Path | None = None
video_scenes: dict[str, list[Scene]] = {}
video_thumbnails: dict[str, Path] = {}
max_duration: float = 120.0


def init_app_with_videos(files: list[Path], duration: float | None = None) -> None:
    """
    Initialize the web app with multiple video files.

    Args:
        files: List of video file paths
        duration: Maximum duration to analyze per video
    """
    global video_files, current_video, video_scenes, video_thumbnails, max_duration

    video_files = files
    max_duration = duration or 120.0

    # Detect scenes for all videos
    scene_detector = SceneDetector()
    for video_file in files:
        video_id = str(video_file)
        detection_result = scene_detector.detect(
            video_file,
            start_time=0.0,
            end_time=max_duration,
        )
        video_scenes[video_id] = detection_result.scenes

        # Extract thumbnails
        thumbnail_dir = Path(tempfile.mkdtemp(prefix=f"videoadsnip_thumbs_"))
        scene_detector.extract_thumbnails(video_file, detection_result.scenes, thumbnail_dir)
        video_thumbnails[video_id] = thumbnail_dir

    # Set first video as current
    if files:
        current_video = files[0]


@app.route("/")
def index() -> str:
    """Render the main page."""
    return render_template("index.html")


@app.route("/api/videos")
def get_videos() -> Response:
    """Get list of available videos."""
    videos_data = []
    for vf in video_files:
        video_id = str(vf)
        processor = VideoProcessor()
        try:
            info = processor.get_video_info(vf)
            videos_data.append({
                "id": video_id,
                "name": vf.name,
                "path": str(vf),
                "duration": info["duration"],
                "resolution": f"{info['video']['width']}x{info['video']['height']}",
                "scene_count": len(video_scenes.get(video_id, [])),
            })
        except Exception:
            videos_data.append({
                "id": video_id,
                "name": vf.name,
                "path": str(vf),
                "error": True,
            })
    return jsonify({"videos": videos_data, "current": str(current_video) if current_video else None})


@app.route("/api/select/<path:video_id>", methods=["POST"])
def select_video(video_id: str) -> Response:
    """Select a video to work with."""
    global current_video
    video_path = Path(video_id)
    if video_path not in video_files:
        return jsonify({"error": "Video not found"}), 404
    current_video = video_path
    return jsonify({"success": True, "video": video_id})


@app.route("/api/scenes")
def get_scenes() -> Response:
    """Get detected scenes as JSON."""
    if not current_video:
        return jsonify({"error": "No video selected"}), 400

    video_id = str(current_video)
    scenes = video_scenes.get(video_id, [])

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
            scene_dict["thumbnail_url"] = f"/thumbnails/{video_id}/{scene.index}"
        scenes_data.append(scene_dict)

    processor = VideoProcessor()
    info = processor.get_video_info(current_video)

    return jsonify({
        "scenes": scenes_data,
        "video_path": str(current_video),
        "video_name": current_video.name,
        "duration": info["duration"],
    })


@app.route("/thumbnails/<path:video_id>/<int:scene_index>")
def get_thumbnail(video_id: str, scene_index: int) -> Response:
    """Serve a thumbnail image."""
    scenes = video_scenes.get(video_id, [])
    if 0 <= scene_index < len(scenes):
        scene = scenes[scene_index]
        if scene.thumbnail_path and scene.thumbnail_path.exists():
            return send_file(str(scene.thumbnail_path), mimetype="image/jpeg")
    return "Not found", 404


@app.route("/api/process", methods=["POST"])
def process_selections() -> Response:
    """Process user selections and create output video."""
    if not current_video:
        return jsonify({"error": "No video selected"}), 400

    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    ad_scenes = data.get("ad_scenes", [])
    output_path = data.get("output_path")

    video_id = str(current_video)
    scenes = video_scenes.get(video_id, [])

    # Calculate ad segments based on selected scene indices
    segments_to_remove: list[tuple[float, float]] = []
    for idx in ad_scenes:
        if 0 <= idx < len(scenes):
            scene = scenes[idx]
            segments_to_remove.append((scene.start_time, scene.end_time))

    if not output_path:
        # Default output path
        output_path = str(current_video.with_stem(current_video.stem + "_clean"))

    try:
        processor = VideoProcessor()
        processor.remove_segments(current_video, Path(output_path), segments_to_remove)
        return jsonify({"success": True, "output_path": output_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/preview/<int:scene_index>")
def preview_scene(scene_index: int) -> Response:
    """Get a video preview for a specific scene."""
    if not current_video:
        return "Not found", 404

    video_id = str(current_video)
    scenes = video_scenes.get(video_id, [])

    if not (0 <= scene_index < len(scenes)):
        return "Not found", 404

    scene = scenes[scene_index]
    if scene.thumbnail_path and scene.thumbnail_path.exists():
        return send_file(str(scene.thumbnail_path), mimetype="image/jpeg")

    return "Not found", 404


def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    """Run the Flask development server."""
    app.run(host=host, port=port, debug=debug)
