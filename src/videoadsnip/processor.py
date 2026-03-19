"""Video processing utilities using ffmpeg."""

import subprocess
import tempfile
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

    def _get_keyframe_times(self, video_path: Path) -> list[float]:
        """
        Get all keyframe timestamps from a video file.

        Args:
            video_path: Path to video file

        Returns:
            List of keyframe timestamps in seconds
        """
        probe = ffmpeg.probe(
            str(video_path),
            select_streams="v",
            show_entries="packet=pts_time,flags",
            print_format="json",
        )

        keyframes = []
        for packet in probe.get("packets", []):
            flags = packet.get("flags", "")
            if "K" in flags:  # K indicates keyframe
                pts_time = packet.get("pts_time")
                if pts_time is not None:
                    keyframes.append(float(pts_time))

        return sorted(keyframes)

    def _find_next_keyframe(self, keyframes: list[float], time: float) -> float | None:
        """
        Find the first keyframe at or after the given time.

        Args:
            keyframes: List of keyframe timestamps
            time: Target time

        Returns:
            Keyframe time or None if not found
        """
        for kf in keyframes:
            if kf >= time:
                return kf
        return None

    def _is_at_keyframe(self, keyframes: list[float], time: float, tolerance: float = 0.001) -> bool:
        """Check if a time is exactly at a keyframe."""
        for kf in keyframes:
            if abs(kf - time) < tolerance:
                return True
        return False

    def _get_video_encoding_params(self, video_path: Path) -> dict:
        """Get encoding parameters from video for re-encoding."""
        probe = ffmpeg.probe(str(video_path))
        video_stream = None
        audio_stream = None

        for stream in probe["streams"]:
            if stream["codec_type"] == "video" and video_stream is None:
                video_stream = stream
            elif stream["codec_type"] == "audio" and audio_stream is None:
                audio_stream = stream

        params = {
            "vcodec": video_stream.get("codec_name", "libx264") if video_stream else "libx264",
            "acodec": audio_stream.get("codec_name", "aac") if audio_stream else "aac",
        }

        # Get video encoding details if available
        if video_stream:
            if "pix_fmt" in video_stream:
                params["pix_fmt"] = video_stream["pix_fmt"]
            if "width" in video_stream and "height" in video_stream:
                params["s"] = f"{video_stream['width']}x{video_stream['height']}"

        # Try to match original bitrate if available
        if video_stream and "bit_rate" in video_stream:
            try:
                params["video_bitrate"] = int(video_stream["bit_rate"])
            except (ValueError, TypeError):
                pass

        return params

    def _smart_cut_segment(
        self,
        input_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
        keyframes: list[float],
        encoding_params: dict,
    ) -> None:
        """
        Cut a segment using smart encoding - only re-encode the partial GOP at start.

        Args:
            input_path: Input video path
            output_path: Output path
            start_time: Start time in seconds
            end_time: End time in seconds
            keyframes: List of keyframe timestamps
            encoding_params: Video encoding parameters
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="videoadsnip_smart_"))
        segment_files = []

        try:
            # Check if start is exactly at a keyframe
            if self._is_at_keyframe(keyframes, start_time):
                # Perfect! Just stream copy the whole segment
                duration = end_time - start_time
                (
                    ffmpeg.input(str(input_path), ss=start_time, t=duration)
                    .output(str(output_path), codec="copy")
                    .overwrite_output()
                    .run(cmd=self.ffmpeg_path, capture_stdout=True, capture_stderr=True)
                )
                return

            # Find the next keyframe after start_time
            next_kf = self._find_next_keyframe(keyframes, start_time)

            if next_kf is None or next_kf >= end_time:
                # No keyframe in range, or segment is shorter than one GOP
                # Re-encode the entire segment
                duration = end_time - start_time
                (
                    ffmpeg.input(str(input_path), ss=start_time)
                    .output(
                        str(output_path),
                        t=duration,
                        vcodec=encoding_params.get("vcodec", "libx264"),
                        acodec=encoding_params.get("acodec", "aac"),
                    )
                    .overwrite_output()
                    .run(cmd=self.ffmpeg_path, capture_stdout=True, capture_stderr=True)
                )
                return

            # Smart cut: re-encode from start to next keyframe, then stream copy
            # Part 1: Re-encode partial GOP (start_time to next_kf)
            partial_duration = next_kf - start_time
            partial_file = temp_dir / "partial.ts"
            (
                ffmpeg.input(str(input_path), ss=start_time)
                .output(
                    str(partial_file),
                    t=partial_duration,
                    format="mpegts",
                    vcodec=encoding_params.get("vcodec", "libx264"),
                    acodec=encoding_params.get("acodec", "aac"),
                )
                .overwrite_output()
                .run(cmd=self.ffmpeg_path, capture_stdout=True, capture_stderr=True)
            )
            segment_files.append(partial_file)

            # Part 2: Stream copy from next keyframe to end (if there's content left)
            if next_kf < end_time:
                copy_duration = end_time - next_kf
                copy_file = temp_dir / "copy.ts"
                (
                    ffmpeg.input(str(input_path), ss=next_kf, t=copy_duration)
                    .output(str(copy_file), format="mpegts", codec="copy")
                    .overwrite_output()
                    .run(cmd=self.ffmpeg_path, capture_stdout=True, capture_stderr=True)
                )
                segment_files.append(copy_file)

            # Concatenate parts
            if len(segment_files) == 1:
                # Only the partial re-encoded part
                segment_files[0].rename(output_path)
            else:
                # Concatenate partial + copy
                self._concatenate_ts_files(segment_files, output_path)

        finally:
            # Cleanup temp files
            for f in segment_files:
                f.unlink(missing_ok=True)
            try:
                temp_dir.rmdir()
            except OSError:
                pass

    def _concatenate_ts_files(self, ts_files: list[Path], output_path: Path) -> None:
        """Concatenate TS files using concat protocol."""
        concat_file = Path(tempfile.mktemp(suffix=".txt", prefix="concat_"))

        try:
            with open(concat_file, "w") as f:
                for ts_file in ts_files:
                    f.write(f"file '{ts_file.absolute()}'\n")

            (
                ffmpeg.input(str(concat_file), format="concat", safe=0)
                .output(str(output_path), codec="copy")
                .overwrite_output()
                .run(cmd=self.ffmpeg_path, capture_stdout=True, capture_stderr=True)
            )
        finally:
            concat_file.unlink(missing_ok=True)

    def remove_segments(
        self,
        input_path: Path,
        output_path: Path,
        segments: list[tuple[float, float]],
    ) -> None:
        """
        Remove multiple segments from a video using smart encoding.

        Only re-encodes partial GOPs at cut points, uses stream copy elsewhere.

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

        # Get keyframe positions for smart cutting
        keyframes = self._get_keyframe_times(input_path)

        # Get encoding params to match original video
        encoding_params = self._get_video_encoding_params(input_path)

        if len(keep_segments) == 1:
            # Single segment: use smart cut directly to output
            start, end = keep_segments[0]
            self._smart_cut_segment(input_path, output_path, start, end, keyframes, encoding_params)
            return

        # Multiple segments: extract each with smart cut, then concatenate
        temp_dir = Path(tempfile.mkdtemp(prefix="videoadsnip_segments_"))
        segment_files = []

        try:
            for i, (start, end) in enumerate(keep_segments):
                seg_file = temp_dir / f"segment_{i:03d}.ts"
                self._smart_cut_segment(input_path, seg_file, start, end, keyframes, encoding_params)
                segment_files.append(seg_file)

            # Concatenate all segments
            self._concatenate_ts_files(segment_files, output_path)

        finally:
            # Cleanup
            for f in segment_files:
                f.unlink(missing_ok=True)
            try:
                temp_dir.rmdir()
            except OSError:
                pass

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
