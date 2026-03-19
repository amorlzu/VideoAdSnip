"""Audio analysis module for detecting ad segments."""

from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
from numpy.typing import NDArray


@dataclass
class AudioSegment:
    """Represents a segment of audio with analysis data."""

    start_time: float  # Start time in seconds
    end_time: float  # End time in seconds
    energy: float  # Average energy (RMS) in this segment
    is_silence: bool  # Whether this segment is below silence threshold
    is_loud: bool  # Whether this segment is above loud threshold


@dataclass
class AudioAnalysisResult:
    """Result of audio analysis on a video file."""

    duration: float  # Total audio duration in seconds
    sample_rate: int  # Audio sample rate
    segments: list[AudioSegment]  # Analyzed segments
    silence_boundaries: list[float]  # Times where silence occurs (potential cuts)
    loud_segments: list[tuple[float, float]]  # (start, end) of loud segments


class AudioAnalyzer:
    """Analyzes audio tracks to detect ad patterns."""

    def __init__(
        self,
        silence_threshold_db: float = -40.0,
        loud_threshold_db: float = -10.0,
        min_silence_duration: float = 0.3,
        segment_duration: float = 0.5,
    ) -> None:
        """
        Initialize the audio analyzer.

        Args:
            silence_threshold_db: Threshold below which audio is considered silence
            loud_threshold_db: Threshold above which audio is considered loud (ads)
            min_silence_duration: Minimum duration of silence to be significant
            segment_duration: Duration of analysis segments in seconds
        """
        self.silence_threshold_db = silence_threshold_db
        self.loud_threshold_db = loud_threshold_db
        self.min_silence_duration = min_silence_duration
        self.segment_duration = segment_duration

        # Convert dB to linear scale
        self.silence_threshold = 10 ** (silence_threshold_db / 20)
        self.loud_threshold = 10 ** (loud_threshold_db / 20)

    def analyze(self, video_path: Path, max_duration: float | None = None) -> AudioAnalysisResult:
        """
        Analyze the audio track of a video file.

        Args:
            video_path: Path to the video file
            max_duration: Maximum duration to analyze (None for entire video)

        Returns:
            AudioAnalysisResult with detected segments and boundaries
        """
        # Load audio from video file using librosa
        # librosa can extract audio directly from video via ffmpeg
        y, sr = librosa.load(str(video_path), sr=None, mono=True, duration=max_duration)

        duration = len(y) / sr
        samples_per_segment = int(self.segment_duration * sr)

        segments: list[AudioSegment] = []
        silence_boundaries: list[float] = []
        loud_segments: list[tuple[float, float]] = []

        # Calculate RMS energy for each segment
        for i in range(0, len(y), samples_per_segment):
            segment_samples = y[i : i + samples_per_segment]
            if len(segment_samples) == 0:
                continue

            start_time = i / sr
            end_time = min((i + samples_per_segment) / sr, duration)

            # Calculate RMS energy
            rms = np.sqrt(np.mean(segment_samples**2))

            is_silence = rms < self.silence_threshold
            is_loud = rms > self.loud_threshold

            segment = AudioSegment(
                start_time=start_time,
                end_time=end_time,
                energy=rms,
                is_silence=is_silence,
                is_loud=is_loud,
            )
            segments.append(segment)

            # Track silence boundaries for potential cuts
            if is_silence:
                silence_boundaries.append(start_time)

        # Find continuous loud segments (likely ads)
        loud_segments = self._find_loud_segments(segments)

        return AudioAnalysisResult(
            duration=duration,
            sample_rate=sr,
            segments=segments,
            silence_boundaries=silence_boundaries,
            loud_segments=loud_segments,
        )

    def _find_loud_segments(
        self, segments: list[AudioSegment], min_gap: float = 1.0
    ) -> list[tuple[float, float]]:
        """
        Find continuous loud segments, merging nearby ones.

        Args:
            segments: List of analyzed audio segments
            min_gap: Minimum gap between segments to consider them separate

        Returns:
            List of (start_time, end_time) tuples for loud segments
        """
        loud_segments: list[tuple[float, float]] = []
        current_start: float | None = None
        current_end: float | None = None

        for seg in segments:
            if seg.is_loud:
                if current_start is None:
                    current_start = seg.start_time
                current_end = seg.end_time
            elif current_start is not None:
                # End of loud segment
                if current_end is not None:
                    loud_segments.append((current_start, current_end))
                current_start = None
                current_end = None

        # Don't forget the last segment
        if current_start is not None and current_end is not None:
            loud_segments.append((current_start, current_end))

        # Merge nearby segments
        merged = self._merge_segments(loud_segments, min_gap)

        return merged

    def _merge_segments(
        self, segments: list[tuple[float, float]], min_gap: float
    ) -> list[tuple[float, float]]:
        """Merge segments that are close together."""
        if not segments:
            return []

        segments = sorted(segments, key=lambda x: x[0])
        merged: list[tuple[float, float]] = [segments[0]]

        for start, end in segments[1:]:
            last_start, last_end = merged[-1]
            if start - last_end <= min_gap:
                # Merge with previous segment
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))

        return merged

    def get_energy_curve(self, video_path: Path, max_duration: float | None = None) -> tuple[NDArray[np.float64], float]:
        """
        Get the energy curve for visualization.

        Args:
            video_path: Path to the video file
            max_duration: Maximum duration to analyze

        Returns:
            Tuple of (energy_array, duration)
        """
        y, sr = librosa.load(str(video_path), sr=None, mono=True, duration=max_duration)
        duration = len(y) / sr

        # Calculate RMS energy in short windows
        hop_length = int(0.01 * sr)  # 10ms hops
        frame_length = int(0.05 * sr)  # 50ms frames

        rms = librosa.feature.rms(y=y, hop_length=hop_length, frame_length=frame_length)[0]

        return rms, duration
