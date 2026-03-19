"""Video processing utilities using ffmpeg."""

from pathlib import Path


class VideoProcessor:
    """Handles video processing operations using ffmpeg."""

    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        """
        Initialize the video processor.

        Args:
            ffmpeg_path: Path to ffmpeg executable
        """
        self.ffmpeg_path = ffmpeg_path

    def cut_segment(
        self,
        input_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
    ) -> None:
        """
        Cut a segment from a video.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            start_time: Start time in seconds
            end_time: End time in seconds
        """
        # TODO: Implement using ffmpeg-python
        raise NotImplementedError("Video cutting not yet implemented")

    def remove_segments(
        self,
        input_path: Path,
        output_path: Path,
        segments: list[tuple[float, float]],
    ) -> None:
        """
        Remove multiple segments from a video.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            segments: List of (start, end) time tuples to remove
        """
        # TODO: Implement segment removal
        raise NotImplementedError("Segment removal not yet implemented")
