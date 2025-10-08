"""Command-line helper for sending videos to the Talks Reducer server."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from gradio_client import Client
from gradio_client import file as gradio_file


def send_video(
    input_path: Path,
    output_path: Optional[Path],
    server_url: str,
    small: bool = False,
    *,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[Path, str, str]:
    """Upload *input_path* to the Gradio server and download the processed video."""

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    client = Client(server_url)
    job = client.submit(
        gradio_file(str(input_path)),
        bool(small),
        api_name="/process_video",
    )

    printed_lines = 0

    def _emit_new_lines(log_text: str) -> None:
        nonlocal printed_lines
        if log_callback is None or not log_text:
            return
        lines = log_text.splitlines()
        if printed_lines < len(lines):
            for line in lines[printed_lines:]:
                log_callback(line)
            printed_lines = len(lines)

    for output in job:
        if not isinstance(output, (list, tuple)) or len(output) != 4:
            continue
        log_text_candidate = output[1] or ""
        if isinstance(log_text_candidate, str):
            _emit_new_lines(log_text_candidate)

    prediction = job.result()

    try:
        video_path, log_text, summary, download_path = prediction
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise RuntimeError("Unexpected response from server") from exc

    if isinstance(log_text, str):
        _emit_new_lines(log_text)
    else:
        log_text = ""

    if not download_path:
        download_path = video_path

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

    if not isinstance(summary, str):
        summary = ""
    if not isinstance(log_text, str):
        log_text = ""

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

    printed_log_header = False

    def _stream(line: str) -> None:
        nonlocal printed_log_header
        if not printed_log_header:
            print("\nServer log:", flush=True)
            printed_log_header = True
        print(line, flush=True)

    destination, summary, log_text = send_video(
        input_path=args.input.expanduser(),
        output_path=args.output.expanduser() if args.output else None,
        server_url=args.server,
        small=args.small,
        log_callback=_stream if args.print_log else None,
    )

    print(summary)
    print(f"Saved processed video to {destination}")
    if args.print_log and log_text.strip() and not printed_log_header:
        print("\nServer log:\n" + log_text)


if __name__ == "__main__":  # pragma: no cover
    main()
