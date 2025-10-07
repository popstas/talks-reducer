"""Command-line helper for sending videos to the Talks Reducer server."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Optional, Sequence, Tuple

from gradio_client import Client
from gradio_client import file as gradio_file


def send_video(
    input_path: Path,
    output_path: Optional[Path],
    server_url: str,
    small: bool = False,
) -> Tuple[Path, str, str]:
    """Upload *input_path* to the Gradio server and download the processed video."""

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    client = Client(server_url)
    prediction = client.predict(
        gradio_file(str(input_path)),
        bool(small),
        api_name="/process_video",
    )

    try:
        _, log_text, summary, download_path = prediction
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise RuntimeError("Unexpected response from server") from exc

    if not download_path:
        raise RuntimeError("Server did not return a processed file")

    download_source = Path(str(download_path))
    if output_path is None:
        destination = Path.cwd() / download_source.name
    else:
        destination = output_path
        if destination.is_dir():
            destination = destination / download_source.name

    destination.parent.mkdir(parents=True, exist_ok=True)
    if download_source.resolve() != destination.resolve():
        shutil.copy2(download_source, destination)

    return destination, summary, log_text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send a video to a running talks-reducer server and download the result.",
    )
    parser.add_argument("input", type=Path, help="Path to the video file to upload.")
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:9005/",
        help="Base URL for the talks-reducer server (default: http://127.0.0.1:9005/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Where to store the processed video. Defaults to the working directory.",
    )
    parser.add_argument(
        "--small",
        action="store_true",
        help="Toggle the 'Small video' preset before processing.",
    )
    parser.add_argument(
        "--print-log",
        action="store_true",
        help="Print the server log after processing completes.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    destination, summary, log_text = send_video(
        input_path=args.input.expanduser(),
        output_path=args.output.expanduser() if args.output else None,
        server_url=args.server,
        small=args.small,
    )

    print(summary)
    print(f"Saved processed video to {destination}")
    if args.print_log:
        print("\nServer log:\n" + log_text)


if __name__ == "__main__":  # pragma: no cover
    main()
