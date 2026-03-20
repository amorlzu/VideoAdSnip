"""Command-line interface for VideoAdSnip."""

import argparse
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from videoadsnip.scene_detector import SceneDetector
from videoadsnip.processor import VideoProcessor

console = Console()

# Supported video extensions
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}


def scan_video_files(input_path: Path) -> list[Path]:
    """
    Scan for video files in a path.

    Args:
        input_path: File or directory path

    Returns:
        List of video file paths (excluding _clean files)
    """
    if input_path.is_file():
        return [input_path]

    video_files = []
    for ext in VIDEO_EXTENSIONS:
        for file_path in input_path.glob(f"*{ext}"):
            # Skip files ending with _clean before extension
            stem = file_path.stem
            if stem.endswith("_clean"):
                continue
            video_files.append(file_path)

    return sorted(video_files, key=lambda x: x.name.lower())


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="videoadsnip",
        description="Detect and remove ads from the beginning of videos",
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=None,
        help="Input video file or directory (optional - drag & drop in web UI if omitted)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file path (default: input_clean.mp4)",
    )
    parser.add_argument(
        "-w",
        "--window",
        type=float,
        default=120.0,
        help="Detection window in seconds from start (default: 120)",
    )
    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="Skip web UI, use auto-detection only",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for web UI (default: 5000)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open browser for web UI",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    console.print(f"[bold blue]VideoAdSnip[/bold blue] v{__import__('videoadsnip').__version__}")

    video_files = []

    # If input is provided, scan for videos
    if args.input:
        if not args.input.exists():
            console.print(f"[red]Error:[/red] Input path does not exist: {args.input}")
            return 1

        video_files = scan_video_files(args.input)

        if not video_files:
            console.print(f"[red]Error:[/red] No video files found in: {args.input}")
            return 1

        console.print(f"Found {len(video_files)} video(s)")

        if args.verbose:
            for vf in video_files:
                console.print(f"  - {vf}")

        console.print(f"Detection window: {args.window}s")
    else:
        console.print("No input provided. Enter file/folder paths in the web UI.")

    # Interactive mode: launch web UI
    console.print(f"\nLaunching web UI at [bold]http://127.0.0.1:{args.port}[/bold]")

    # Initialize and run web app with videos (can be empty list)
    from videoadsnip.web import init_app_with_videos, run_server

    init_app_with_videos(video_files, duration=args.window)

    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{args.port}")

    console.print("[dim]Press Ctrl+C to stop the server[/dim]\n")
    run_server(port=args.port)

    return 0


def _print_video_info(info: dict) -> None:
    """Print video information table."""
    table = Table(title="Video Information")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Duration", f"{info['duration']:.1f}s")
    table.add_row("Resolution", f"{info['video']['width']}x{info['video']['height']}")
    table.add_row("Video Codec", info['video']['codec'] or "Unknown")
    table.add_row("Audio Codec", info['audio']['codec'] or "Unknown")
    table.add_row("FPS", f"{info['video']['fps']:.2f}")

    console.print(table)


if __name__ == "__main__":
    sys.exit(main())
