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


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="videoadsnip",
        description="Detect and remove ads from the beginning of videos",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input video file",
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

    if not args.input.exists():
        console.print(f"[red]Error:[/red] Input file does not exist: {args.input}")
        return 1

    if not args.input.is_file():
        console.print(f"[red]Error:[/red] Input must be a file: {args.input}")
        return 1

    console.print(f"[bold blue]VideoAdSnip[/bold blue] v{__import__('videoadsnip').__version__}")
    console.print(f"Input: {args.input}")
    console.print(f"Detection window: {args.window}s")

    # Determine output path
    output_path = args.output or args.input.with_stem(args.input.stem + "_clean")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Step 1: Get video info
        task1 = progress.add_task("Analyzing video file...", total=None)
        processor = VideoProcessor()
        try:
            video_info = processor.get_video_info(args.input)
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to read video: {e}")
            return 1
        progress.update(task1, completed=True)

        if args.verbose:
            _print_video_info(video_info)

        # Step 2: Scene detection
        task2 = progress.add_task("Detecting scenes...", total=None)
        scene_detector = SceneDetector()
        try:
            detection_result = scene_detector.detect(
                args.input,
                start_time=0.0,
                end_time=args.window,
            )
        except Exception as e:
            console.print(f"[red]Error:[/red] Scene detection failed: {e}")
            return 1
        progress.update(task2, completed=True)

        console.print(f"  Detected [bold]{len(detection_result.scenes)}[/bold] scenes")

    if args.no_ui:
        # Auto mode: select first scene as ad (simple heuristic)
        console.print("\n[yellow]Auto-detection mode:[/yellow]")
        ad_scenes = detection_result.scenes[:1] if detection_result.scenes else []

        if not ad_scenes:
            console.print("[yellow]No ads detected automatically.[/yellow]")
            console.print("Try using the web UI mode for manual selection.")
            return 0

        console.print(f"Auto-detected {len(ad_scenes)} ad scenes:")
        for scene in ad_scenes:
            console.print(f"  - Scene {scene.index + 1}: {scene.start_time:.1f}s - {scene.end_time:.1f}s")

        # Process video
        segments_to_remove = [(s.start_time, s.end_time) for s in ad_scenes]
        console.print(f"\nProcessing video...")
        processor.remove_segments(args.input, output_path, segments_to_remove)
        console.print(f"[green]Success![/green] Output saved to: {output_path}")

    else:
        # Interactive mode: launch web UI
        console.print(f"\nLaunching web UI at [bold]http://127.0.0.1:{args.port}[/bold]")

        # Extract thumbnails
        import tempfile
        thumbnail_dir = Path(tempfile.mkdtemp(prefix="videoadsnip_thumbs_"))
        scene_detector.extract_thumbnails(args.input, detection_result.scenes, thumbnail_dir)

        # Initialize and run web app
        from videoadsnip.web import init_app, run_server

        init_app(args.input, max_duration=args.window)

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
