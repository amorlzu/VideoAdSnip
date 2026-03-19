"""Scene detection module using video analysis."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from scenedetect import ContentDetector, detect, open_video


@dataclass
class Scene:
    """Represents a detected scene in a video."""

    index: int  # Scene number (0-indexed)
    start_time: float  # Start time in seconds
    end_time: float  # End time in seconds
    start_frame: int  # Start frame number
    end_frame: int  # End frame number
    thumbnail_path: Path | None = None  # Path to thumbnail image

    @property
    def duration(self) -> float:
        """Duration of the scene in seconds."""
        return self.end_time - self.start_time


@dataclass
class SceneDetectionResult:
    """Result of scene detection on a video file."""

    scenes: list[Scene]
    total_duration: float
    fps: float
    frame_count: int


class SceneDetector:
    """Detects scene changes in video files."""

    def __init__(
        self,
        threshold: float = 27.0,
        min_scene_len: int = 15,
    ) -> None:
        """
        Initialize the scene detector.

        Args:
            threshold: Content detection threshold (lower = more sensitive)
            min_scene_len: Minimum scene length in frames
        """
        self.threshold = threshold
        self.min_scene_len = min_scene_len

    def detect(
        self,
        video_path: Path,
        start_time: float = 0.0,
        end_time: float | None = None,
        audio_hints: list[float] | None = None,
    ) -> SceneDetectionResult:
        """
        Detect scenes in a video file.

        Args:
            video_path: Path to the video file
            start_time: Start time for detection (seconds)
            end_time: End time for detection (seconds, None for entire video)
            audio_hints: List of times where audio changes occur (to improve detection)

        Returns:
            SceneDetectionResult with detected scenes
        """
        # Use scenedetect.detect for simple scene detection
        detector = ContentDetector(threshold=self.threshold, min_scene_len=self.min_scene_len)

        # Get video info first
        video = open_video(str(video_path))
        fps = video.frame_rate
        total_frames = video.duration.get_frames()
        total_duration = total_frames / fps if fps > 0 else 0

        # Perform detection with time bounds
        scene_list = detect(
            str(video_path),
            detector,
            start_time=start_time if start_time > 0 else None,
            end_time=end_time,
            show_progress=False,
        )

        # Convert to our Scene objects
        scenes: list[Scene] = []
        for i, (start, end) in enumerate(scene_list):
            scene = Scene(
                index=i,
                start_time=start.get_seconds(),
                end_time=end.get_seconds(),
                start_frame=start.get_frames(),
                end_frame=end.get_frames(),
            )
            scenes.append(scene)

        # If no scenes detected, treat entire video as one scene
        if not scenes:
            scenes = [
                Scene(
                    index=0,
                    start_time=start_time,
                    end_time=end_time if end_time else total_duration,
                    start_frame=0,
                    end_frame=total_frames,
                )
            ]

        return SceneDetectionResult(
            scenes=scenes,
            total_duration=total_duration,
            fps=fps,
            frame_count=total_frames,
        )

    def detect_with_audio_hints(
        self,
        video_path: Path,
        audio_boundaries: list[float],
        threshold: float = 20.0,
    ) -> list[Scene]:
        """
        Detect scenes using audio boundaries as hints.

        This method first finds scene changes near audio boundaries,
        then fills in with regular scene detection.

        Args:
            video_path: Path to the video file
            audio_boundaries: Times where audio changes occur
            threshold: Detection threshold (lower near audio boundaries)

        Returns:
            List of detected scenes
        """
        # TODO: Implement smart detection using audio hints
        # For now, fall back to regular detection
        result = self.detect(video_path)
        return result.scenes

    def extract_thumbnails(
        self,
        video_path: Path,
        scenes: list[Scene],
        output_dir: Path,
    ) -> list[Scene]:
        """
        Extract thumbnail images for each scene.

        Args:
            video_path: Path to the video file
            scenes: List of scenes to extract thumbnails for
            output_dir: Directory to save thumbnail images

        Returns:
            Updated scenes with thumbnail_path set
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)

        for scene in scenes:
            # Extract frame from middle of scene
            mid_time = (scene.start_time + scene.end_time) / 2
            frame_num = int(mid_time * fps)

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()

            if ret:
                thumbnail_path = output_dir / f"scene_{scene.index:03d}.jpg"
                cv2.imwrite(str(thumbnail_path), frame)
                scene.thumbnail_path = thumbnail_path

        cap.release()
        return scenes

    def get_frame_at_time(self, video_path: Path, time_seconds: float) -> np.ndarray | None:
        """
        Get a single frame from the video at a specific time.

        Args:
            video_path: Path to the video file
            time_seconds: Time in seconds to get frame from

        Returns:
            Frame as numpy array, or None if failed
        """
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_num = int(time_seconds * fps)

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        cap.release()

        if ret:
            return frame
        return None
