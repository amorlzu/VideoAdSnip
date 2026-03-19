"""Command-line interface for VideoAdSnip."""

import argparse
import sys
from pathlib import Path

from rich.console import Console

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
        help="Input video file or directory",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file or directory (default: overwrite input)",
    )
    parser.add_argument(
        "-d",
        "--detect-only",
        action="store_true",
        help="Only detect ads, don't remove them",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    if not args.input.exists():
        console.print(f"[red]Error:[/red] Input path does not exist: {args.input}")
        return 1

    console.print(f"[blue]VideoAdSnip[/blue] v{__import__('videoadsnip').__version__}")
    console.print(f"Processing: {args.input}")

    # TODO: Implement ad detection and removal
    console.print("[yellow]Warning:[/yellow] Core functionality not yet implemented")

    return 0


if __name__ == "__main__":
    sys.exit(main())
