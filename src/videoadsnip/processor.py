"""Video processing utilities using ffmpeg."""

import subprocess
from pathlib import Path

import ffmpeg


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
        duration = end_time - start_time

        (
            ffmpeg.input(str(input_path), ss=start_time, t=duration)
            .output(str(output_path), codec="copy")
            .overwrite_output()
            .run(cmd=self.ffmpeg_path, capture_stdout=True, capture_stderr=True)
        )

    def remove_segments(
        self,
        input_path: Path,
        output_path: Path,
        segments: list[tuple[float, float]],
    ) -> None:
        """
        Remove multiple segments from a video.

        This method extracts all non-ad segments and concatenates them.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            segments: List of (start, end) time tuples to REMOVE
        """
        # Sort segments by start time
        segments = sorted(segments, key=lambda x: x[0])

        # Calculate segments to KEEP
        video_duration = self._get_duration(input_path)
        keep_segments = self._calculate_keep_segments(segments, video_duration)

        if not keep_segments:
            raise ValueError("No segments to keep after removing ads")

        if len(keep_segments) == 1:
            # Simple case: just cut to the single segment
            start, end = keep_segments[0]
            self.cut_segment(input_path, output_path, start, end)
            return

        # Multiple segments: create temporary files and concatenate
        temp_files = self._extract_segments_to_temp(input_path, keep_segments)
        self._concatenate_segments(temp_files, output_path)

    def _get_duration(self, video_path: Path) -> float:
        """Get the duration of a video file in seconds."""
        probe = ffmpeg.probe(str(video_path))
        duration = float(probe["format"]["duration"])
        return duration

    def _calculate_keep_segments(
        self,
        remove_segments: list[tuple[float, float]],
        total_duration: float,
    ) -> list[tuple[float, float]]:
        """
        Calculate which segments to keep based on segments to remove.

        Args:
            remove_segments: Segments to remove (start, end)
            total_duration: Total video duration

        Returns:
            List of segments to keep (start, end)
        """
        keep_segments: list[tuple[float, float]] = []
        current_pos = 0.0

        for remove_start, remove_end in remove_segments:
            if remove_start > current_pos:
                # Keep the segment before this removal
                keep_segments.append((current_pos, remove_start))
            current_pos = max(current_pos, remove_end)

        # Keep the final segment if there's content after the last removal
        if current_pos < total_duration:
            keep_segments.append((current_pos, total_duration))

        return keep_segments

    def _extract_segments_to_temp(
        self,
        input_path: Path,
        segments: list[tuple[float, float]],
    ) -> list[Path]:
        """
        Extract segments to temporary files.

        Args:
            input_path: Input video path
            segments: Segments to extract (start, end)

        Returns:
            List of paths to temporary segment files
        """
        import tempfile

        temp_dir = Path(tempfile.mkdtemp(prefix="videoadsnip_"))
        temp_files: list[Path] = []

        for i, (start, end) in enumerate(segments):
            temp_file = temp_dir / f"segment_{i:03d}.ts"  # Use .ts for concatenation
            duration = end - start

            (
                ffmpeg.input(str(input_path), ss=start, t=duration)
                .output(
                    str(temp_file),
                    format="mpegts",
                    vcodec="libx264",
                    acodec="aac",
                )
                .overwrite_output()
                .run(cmd=self.ffmpeg_path, capture_stdout=True, capture_stderr=True)
            )
            temp_files.append(temp_file)

        return temp_files

    def _concatenate_segments(
        self,
        segment_files: list[Path],
        output_path: Path,
    ) -> None:
        """
        Concatenate multiple video segments into one file.

        Args:
            segment_files: List of paths to segment files
            output_path: Output file path
        """
        # Create concat file for ffmpeg
        import tempfile

        concat_file = Path(tempfile.mktemp(suffix=".txt", prefix="concat_"))

        with open(concat_file, "w") as f:
            for seg_file in segment_files:
                f.write(f"file '{seg_file.absolute()}'\n")

        try:
            (
                ffmpeg.input(str(concat_file), format="concat", safe=0)
                .output(str(output_path), vcodec="copy", acodec="copy")
                .overwrite_output()
                .run(cmd=self.ffmpeg_path, capture_stdout=True, capture_stderr=True)
            )
        finally:
            # Cleanup
            concat_file.unlink(missing_ok=True)
            for seg_file in segment_files:
                seg_file.unlink(missing_ok=True)
                # Also try to remove parent dir if empty
                try:
                    seg_file.parent.rmdir()
                except OSError:
                    pass

    def get_video_info(self, video_path: Path) -> dict:
        """
        Get information about a video file.

        Args:
            video_path: Path to video file

        Returns:
            Dictionary with video information
        """
        probe = ffmpeg.probe(str(video_path))

        video_stream = None
        audio_stream = None

        for stream in probe["streams"]:
            if stream["codec_type"] == "video" and video_stream is None:
                video_stream = stream
            elif stream["codec_type"] == "audio" and audio_stream is None:
                audio_stream = stream

        return {
            "duration": float(probe["format"]["duration"]),
            "size": int(probe["format"]["size"]),
            "bitrate": int(probe["format"]["bit_rate"]),
            "video": {
                "width": int(video_stream["width"]) if video_stream else 0,
                "height": int(video_stream["height"]) if video_stream else 0,
                "codec": video_stream["codec_name"] if video_stream else None,
                "fps": eval(video_stream["r_frame_rate"]) if video_stream else 0,
            },
            "audio": {
                "codec": audio_stream["codec_name"] if audio_stream else None,
                "sample_rate": int(audio_stream["sample_rate"]) if audio_stream else 0,
                "channels": int(audio_stream["channels"]) if audio_stream else 0,
            },
        }
