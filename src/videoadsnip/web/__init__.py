"""Flask web application for VideoAdSnip scene selection UI."""

import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file

from videoadsnip.audio_analyzer import AudioAnalyzer
from videoadsnip.scene_detector import Scene, SceneDetector

app = Flask(__name__)

# Global state (per session in production)
video_path: Path | None = None
scenes: list[Scene] = []
detection_window: tuple[float, float] = (0.0, 0.0)
audio_hints: list[float] = []
thumbnail_dir: Path | None = None


def init_app(video_file: Path, max_duration: float | None = None) -> None:
    """
    Initialize the web app with video data.

    Args:
        video_file: Path to the video file
        max_duration: Maximum duration to analyze (for ad detection window)
    """
    global video_path, scenes, detection_window, audio_hints, thumbnail_dir

    video_path = video_file

    # Run audio analysis first
    audio_analyzer = AudioAnalyzer()
    audio_result = audio_analyzer.analyze(video_file, max_duration=max_duration)
    audio_hints = audio_result.silence_boundaries

    # Detect scenes
    scene_detector = SceneDetector()
    detection_result = scene_detector.detect(
        video_file,
        start_time=0.0,
        end_time=max_duration,
    )
    scenes = detection_result.scenes

    # Extract thumbnails
    thumbnail_dir = Path(tempfile.mkdtemp(prefix="videoadsnip_thumbs_"))
    scene_detector.extract_thumbnails(video_file, scenes, thumbnail_dir)

    detection_window = (0.0, detection_result.total_duration)


@app.route("/")
def index() -> str:
    """Render the main page."""
    return render_template("index.html")


@app.route("/api/scenes")
def get_scenes() -> Response:
    """Get detected scenes as JSON."""
    scenes_data = []
    for scene in scenes:
        scene_dict = asdict(scene)
        if scene.thumbnail_path:
            scene_dict["thumbnail_url"] = f"/thumbnails/{scene.index}"
        scenes_data.append(scene_dict)

    return jsonify(
        {
            "scenes": scenes_data,
            "video_path": str(video_path) if video_path else None,
            "detection_window": detection_window,
            "audio_hints": audio_hints[:50],  # Limit hints
        }
    )


@app.route("/thumbnails/<int:scene_index>")
def get_thumbnail(scene_index: int) -> Response:
    """Serve a thumbnail image."""
    if 0 <= scene_index < len(scenes):
        scene = scenes[scene_index]
        if scene.thumbnail_path and scene.thumbnail_path.exists():
            return send_file(str(scene.thumbnail_path), mimetype="image/jpeg")

    return "Not found", 404


@app.route("/api/process", methods=["POST"])
def process_selections() -> Response:
    """Process user selections and create output video."""
    from videoadsnip.processor import VideoProcessor

    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    ad_scenes = data.get("ad_scenes", [])
    output_path = data.get("output_path")

    if not video_path:
        return jsonify({"error": "No video loaded"}), 400

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
    if not video_path or not (0 <= scene_index < len(scenes)):
        return "Not found", 404

    scene = scenes[scene_index]

    # For now, return the thumbnail as preview
    # TODO: Generate actual video preview segment
    if scene.thumbnail_path and scene.thumbnail_path.exists():
        return send_file(str(scene.thumbnail_path), mimetype="image/jpeg")

    return "Not found", 404


def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    """Run the Flask development server."""
    app.run(host=host, port=port, debug=debug)
