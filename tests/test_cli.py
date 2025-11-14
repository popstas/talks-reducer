"""Tests for the CLI entry point behaviour."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from talks_reducer import cli


def test_build_parser_includes_version_and_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The CLI parser should expose version info and default temp folder."""

    monkeypatch.setattr(cli, "resolve_version", lambda: "9.9.9")
    default_temp = tmp_path / "work"
    monkeypatch.setattr(cli, "default_temp_folder", lambda: default_temp)

    parser = cli._build_parser()

    args = parser.parse_args(["input.mp4"])
    assert args.input_file == ["input.mp4"]
    assert args.temp_folder == str(default_temp)
    assert args.video_codec == "hevc"
    assert args.prefer_global_ffmpeg is False
    assert args.add_codec_suffix is False

    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])

    out = capsys.readouterr().out
    assert "talks-reducer 9.9.9" in out

    codec_suffix_args = parser.parse_args(
        [
            "--add-codec-suffix",
            "input.mp4",
        ]
    )
    assert codec_suffix_args.add_codec_suffix is True


def test_gather_input_files_collects_valid_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Gathering should include individual files and directory members."""

    file_path = tmp_path / "video1.mp4"
    file_path.write_text("data")

    directory = tmp_path / "inputs"
    directory.mkdir()
    valid_child = directory / "clip.mp4"
    valid_child.write_text("data")
    (directory / "notes.txt").write_text("ignore")

    monkeypatch.setattr(
        cli.audio,
        "is_valid_video_file",
        lambda candidate: str(candidate).endswith(("video1.mp4", "clip.mp4")),
    )

    results = cli.gather_input_files([str(file_path), str(directory)])

    assert str(file_path.resolve()) in results
    assert str(valid_child) in results
    assert len(results) == 2


def test_print_total_time_formats_elapsed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The elapsed time helper should print hours, minutes, and seconds."""

    start_time = 10.0
    monkeypatch.setattr(cli.time, "time", lambda: start_time + 3661.5)

    cli._print_total_time(start_time)

    output = capsys.readouterr().out
    assert "Time: 1h 1m 1.50s" in output


def test_cli_application_builds_processing_options_and_runs_local_pipeline() -> None:
    """The CLI application should configure the local pipeline correctly."""

    parsed_args = SimpleNamespace(
        input_file=["input.mp4"],
        output_file="/tmp/output.mp4",
        temp_folder="/tmp/work",
        silent_threshold=0.2,
        silent_speed=5.0,
        sounded_speed=1.75,
        frame_spreadage=4,
        sample_rate=48000,
        optimize=True,
        small=True,
        keyframe_interval_seconds=1.5,
        video_codec="hevc",
        add_codec_suffix=True,
        server_url=None,
        host=None,
        prefer_global_ffmpeg=True,
    )

    gathered: list[list[str]] = []

    def gather_files(paths: list[str]) -> list[str]:
        gathered.append(list(paths))
        return ["/videos/input.mp4"]

    speed_calls: list[cli.ProcessingOptions] = []

    def fake_speed_up(options: cli.ProcessingOptions, reporter: object):
        speed_calls.append(options)
        return SimpleNamespace(
            output_file=Path("/videos/output.mp4"), time_ratio=0.5, size_ratio=0.25
        )

    logged_messages: list[str] = []

    class DummyReporter:
        def log(self, message: str) -> None:
            logged_messages.append(message)

    app = cli.CliApplication(
        gather_files=gather_files,
        send_video=None,
        speed_up=fake_speed_up,
        reporter_factory=DummyReporter,
    )

    exit_code, error_messages = app.run(parsed_args)

    assert exit_code == 0
    assert error_messages == []
    assert gathered == [["input.mp4"]]
    assert len(speed_calls) == 1
    options = speed_calls[0]
    assert options.input_file == Path("/videos/input.mp4")
    assert options.output_file == Path("/tmp/output.mp4")
    assert options.temp_folder == Path("/tmp/work")
    assert options.silent_threshold == pytest.approx(0.2)
    assert options.silent_speed == pytest.approx(5.0)
    assert options.sounded_speed == pytest.approx(1.75)
    assert options.frame_spreadage == 4
    assert options.sample_rate == 48000
    assert options.keyframe_interval_seconds == pytest.approx(1.5)
    assert options.video_codec == "hevc"
    assert options.optimize is True
    assert options.small is True
    assert options.add_codec_suffix is True
    assert options.prefer_global_ffmpeg is True
    # Check for output path with platform-agnostic separator
    assert any("Completed: /videos/output.mp4" in msg or "Completed: \\videos\\output.mp4" in msg for msg in logged_messages)
    assert any(message.startswith("Result: ") for message in logged_messages)


def test_cli_application_falls_back_to_local_after_remote_failure() -> None:
    """Remote processing errors should switch back to the local pipeline."""

    parsed_args = SimpleNamespace(
        input_file=["input.mp4"],
        output_file=None,
        temp_folder=None,
        silent_threshold=None,
        silent_speed=None,
        sounded_speed=None,
        frame_spreadage=None,
        sample_rate=None,
        keyframe_interval_seconds=None,
        video_codec="h264",
        optimize=True,
        small=False,
        server_url="http://localhost:9005",
        server_stream=False,
        host=None,
        prefer_global_ffmpeg=True,
    )

    def gather_files(_paths: list[str]) -> list[str]:
        return ["/videos/input.mp4"]

    def failing_send_video(**kwargs: object):
        assert kwargs.get("video_codec") == "h264"
        assert kwargs.get("prefer_global_ffmpeg") is True
        assert kwargs.get("add_codec_suffix") is None
        raise RuntimeError("boom")

    local_runs: list[cli.ProcessingOptions] = []

    def fake_speed_up(options: cli.ProcessingOptions, reporter: object):
        local_runs.append(options)
        return SimpleNamespace(output_file=Path("/videos/output.mp4"))

    logged_messages: list[str] = []

    class DummyReporter:
        def log(self, message: str) -> None:
            logged_messages.append(message)

    app = cli.CliApplication(
        gather_files=gather_files,
        send_video=failing_send_video,
        speed_up=fake_speed_up,
        reporter_factory=DummyReporter,
    )

    exit_code, error_messages = app.run(parsed_args)

    assert exit_code == 0
    assert error_messages == [
        "Failed to process input.mp4 via server: boom",
        "Falling back to local processing pipeline.",
    ]
    assert logged_messages[:2] == error_messages
    assert len(local_runs) == 1
    assert local_runs[0].optimize is True


def test_main_launches_gui_when_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """The GUI should be launched when no CLI arguments are provided."""

    launch_calls: list[list[str]] = []

    def fake_launch(argv: list[str]) -> bool:
        launch_calls.append(list(argv))
        return True

    def fail_build_parser() -> None:
        raise AssertionError("Parser should not be built when GUI launches")

    monkeypatch.setattr(cli, "_launch_gui", fake_launch)
    monkeypatch.setattr(cli, "_build_parser", fail_build_parser)

    cli.main([])

    assert launch_calls == [[]]


def test_main_runs_cli_with_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Providing CLI arguments should bypass the GUI and run the pipeline."""

    parsed_args = SimpleNamespace(
        input_file=["input.mp4"],
        output_file=None,
        temp_folder=None,
        silent_threshold=None,
        silent_speed=None,
        sounded_speed=None,
        frame_spreadage=None,
        sample_rate=None,
        keyframe_interval_seconds=None,
        small=False,
        server_url=None,
        video_codec="h264",
        host=None,
        prefer_global_ffmpeg=False,
    )

    parser_mock = mock.Mock()
    parser_mock.parse_args.return_value = parsed_args

    def fail_launch(_argv: list[str]) -> bool:
        raise AssertionError("GUI should not be launched when arguments exist")

    app_stub = mock.Mock()
    app_stub.run.return_value = (0, [])

    def build_app(**kwargs: object) -> mock.Mock:
        app_stub.dependencies = kwargs
        return app_stub

    monkeypatch.setattr(cli, "_build_parser", lambda: parser_mock)
    monkeypatch.setattr(cli, "CliApplication", build_app)
    monkeypatch.setattr(cli, "_launch_gui", fail_launch)

    cli.main(["input.mp4"])

    parser_mock.parse_args.assert_called_once_with(["input.mp4"])
    app_stub.run.assert_called_once_with(parsed_args)


def test_main_launches_server_tray_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The --server flag should launch the system tray helper."""

    tray_calls: list[list[str]] = []

    def fake_tray(argv: list[str]) -> bool:
        tray_calls.append(list(argv))
        return True

    def fail_build_parser() -> None:
        raise AssertionError("Parser should not be built when launching the tray")

    monkeypatch.setattr(cli, "_launch_server_tray", fake_tray)
    monkeypatch.setattr(cli, "_build_parser", fail_build_parser)
    monkeypatch.setattr(cli, "_launch_gui", lambda argv: False)

    cli.main(["--server", "--share", "--port", "9005"])

    assert tray_calls == [["--share", "--port", "9005"]]


def test_main_exits_when_server_tray_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tray startup failure should mimic a CLI error."""

    monkeypatch.setattr(cli, "_launch_server_tray", lambda argv: False)
    monkeypatch.setattr(cli, "_launch_gui", lambda argv: False)

    with pytest.raises(SystemExit):
        cli.main(["--server"])


def test_main_exits_when_server_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing Gradio server should raise SystemExit to mimic CLI failures."""

    monkeypatch.setattr(cli, "_launch_server", lambda argv: False)
    monkeypatch.setattr(cli, "_launch_gui", lambda argv: False)

    with pytest.raises(SystemExit):
        cli.main(["server"])


def test_cli_application_uses_remote_server_when_url_provided() -> None:
    """Remote processing should call the server client with the expected options."""

    parsed_args = SimpleNamespace(
        input_file=["input.mp4"],
        output_file=None,
        temp_folder=None,
        silent_threshold=0.25,
        silent_speed=5.0,
        sounded_speed=1.75,
        frame_spreadage=None,
        sample_rate=None,
        keyframe_interval_seconds=None,
        optimize=True,
        small=True,
        server_url="http://localhost:9005/",
        server_stream=False,
        host=None,
        video_codec="h264",
        prefer_global_ffmpeg=False,
    )

    send_calls: list[dict[str, object]] = []

    def fake_send_video(**kwargs: object):
        send_calls.append(dict(kwargs))
        return Path("/tmp/result.mp4"), "Summary", "Log"

    def fail_speed_up(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Local pipeline should not run when remote succeeds")

    reporter_factory = mock.Mock(
        side_effect=AssertionError(
            "Reporter should not be constructed on remote success"
        )
    )

    app = cli.CliApplication(
        gather_files=lambda paths: ["/tmp/input.mp4"],
        send_video=fake_send_video,
        speed_up=fail_speed_up,
        reporter_factory=reporter_factory,
    )

    exit_code, error_messages = app.run(parsed_args)

    assert exit_code == 0
    assert error_messages == []
    assert len(send_calls) == 1
    call = send_calls[0]
    assert call["input_path"] == Path("/tmp/input.mp4")
    assert call["output_path"] is None
    assert call["server_url"] == "http://localhost:9005/"
    assert call["small"] is True
    assert call["silent_threshold"] == 0.25
    assert call["silent_speed"] == 5.0
    assert call["sounded_speed"] == 1.75
    assert call["log_callback"] is not None
    assert call["stream_updates"] is False
    assert call["progress_callback"] is None


def test_launch_server_tray_prefers_external_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The packaged binary should be used when available."""

    binary_path = Path("/tmp/talks-reducer-server-tray")
    monkeypatch.setattr(cli, "_find_server_tray_binary", lambda: binary_path)

    run_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        run_calls.append((list(args), dict(kwargs)))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli._launch_server_tray_binary(["--foo"]) is True
    assert run_calls[0][0] == [str(binary_path), "--foo"]


def test_launch_server_tray_binary_hides_console_without_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows launches should hide the console when detached."""

    binary_path = Path("C:/tray.exe")
    monkeypatch.setattr(cli, "_find_server_tray_binary", lambda: binary_path)
    monkeypatch.setattr(cli, "_should_hide_subprocess_console", lambda: True)
    monkeypatch.setattr(cli, "sys", SimpleNamespace(platform="win32"))

    calls: list[dict[str, object]] = []

    class DummySubprocess:
        CREATE_NO_WINDOW = 0x08000000

        @staticmethod
        def run(args: list[str], **kwargs: object) -> SimpleNamespace:
            calls.append(dict(kwargs))
            return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, "subprocess", DummySubprocess)

    assert cli._launch_server_tray_binary([]) is True
    assert calls and calls[0].get("creationflags") == DummySubprocess.CREATE_NO_WINDOW


def test_should_hide_subprocess_console_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-Windows platforms should never request a hidden console."""

    monkeypatch.setattr(cli.sys, "platform", "linux")

    assert cli._should_hide_subprocess_console() is False


def test_launch_server_tray_binary_handles_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing executable should fall back to the Python module."""

    monkeypatch.setattr(cli, "_find_server_tray_binary", lambda: None)

    assert cli._launch_server_tray_binary([]) is False


def test_launch_server_tray_falls_back_to_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the binary is unavailable, the module entry point is invoked."""

    monkeypatch.setattr(cli, "_launch_server_tray_binary", lambda argv: False)

    calls: list[list[str]] = []

    class DummyModule:
        @staticmethod
        def main(argv: list[str]) -> None:
            calls.append(list(argv))

    monkeypatch.setattr(cli, "import_module", lambda name, package=None: DummyModule)

    assert cli._launch_server_tray(["--bar"]) is True
    assert calls == [["--bar"]]


def test_main_launches_server_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server subcommand should dispatch to the Gradio launcher."""

    server_calls: list[list[str]] = []

    def fake_server(argv: list[str]) -> bool:
        server_calls.append(list(argv))
        return True

    monkeypatch.setattr(cli, "_launch_server", fake_server)
    monkeypatch.setattr(cli, "_launch_gui", lambda argv: False)

    cli.main(["server", "--share"])

    assert server_calls == [["--share"]]


def test_gather_input_files_returns_only_valid_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only valid files should be returned when gathering inputs."""

    valid_file = tmp_path / "video_valid.mp4"
    valid_file.write_text("data")
    invalid_file = tmp_path / "video_invalid.mp4"
    invalid_file.write_text("data")

    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_valid = nested_dir / "clip_keep.mp4"
    nested_valid.write_text("data")
    (nested_dir / "clip_skip.txt").write_text("data")

    monkeypatch.setattr(
        cli.audio,
        "is_valid_video_file",
        lambda path: Path(path).name in {"video_valid.mp4", "clip_keep.mp4"},
    )

    gathered = cli.gather_input_files(
        [str(valid_file), str(nested_dir), str(tmp_path / "nonexistent.mp4")]
    )

    assert str(valid_file.resolve()) in gathered
    assert str(nested_valid) in gathered
    assert all("invalid" not in path for path in gathered)


def test_process_via_server_handles_multiple_files_and_warnings(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Server runs should warn about ignored options and stream progress."""

    files = ["/videos/first.mp4", "/videos/second.mp4"]

    parsed_args = SimpleNamespace(
        input_file=list(files),
        output_file="~/result.mp4",
        temp_folder="/tmp/work",
        silent_threshold=0.15,
        silent_speed=4.0,
        sounded_speed=1.2,
        frame_spreadage=3,
        sample_rate=44100,
        keyframe_interval_seconds=2.5,
        optimize=True,
        small=False,
        server_url="http://localhost:9005",
        server_stream=True,
        video_codec="h264",
        host=None,
        prefer_global_ffmpeg=False,
    )

    send_calls: list[dict[str, object]] = []

    def fake_send_video(**kwargs: object):
        send_calls.append(dict(kwargs))
        log_callback = kwargs.get("log_callback")
        if callable(log_callback):
            log_callback("line 1")
            log_callback("line 2")
        progress_callback = kwargs.get("progress_callback")
        if callable(progress_callback):
            progress_callback("Upload", 1, 2, "files")
            progress_callback("Upload", 1, 2, "files")  # duplicate should be ignored
            progress_callback("Transcode", None, None, "frames")
        return Path("/tmp/server-result.mp4"), "Summary text", "Server log tail"

    monkeypatch.setattr(cli, "_print_total_time", lambda start_time: print("TOTAL"))

    app = cli.CliApplication(
        gather_files=lambda inputs: list(inputs),
        send_video=fake_send_video,
        speed_up=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
        reporter_factory=lambda: None,
    )

    success, errors, logs = app._process_via_server(files, parsed_args, start_time=0.0)

    captured = capsys.readouterr()

    assert success is True
    assert errors == []
    assert logs == []
    assert "Processing file 1/2 'first.mp4' via server" in captured.out
    assert "Server log:" in captured.out
    assert captured.out.count("Upload: 1/2 50.0% files") == len(files)
    assert "Transcode: frames" in captured.out
    assert "Summary text" in captured.out
    assert "Server log tail" not in captured.out  # printed with header already
    assert "TOTAL" in captured.out

    assert "Warning: --output is ignored" in captured.err
    assert "Warning: the following options are ignored" in captured.err
    assert "--keyframe-interval-seconds" in captured.err

    assert len(send_calls) == 2
    for call, file in zip(send_calls, files):
        assert call["input_path"] == Path(file)
        assert call["output_path"] is None
        assert call["server_url"] == "http://localhost:9005"
        assert call["small"] is False
        assert call["silent_threshold"] == 0.15
        assert call["silent_speed"] == 4.0
        assert call["sounded_speed"] == 1.2
        assert call["stream_updates"] is True
        assert callable(call["log_callback"])
        assert callable(call["progress_callback"])


def test_print_total_time_formats_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Elapsed time should be formatted into hours, minutes, and seconds."""

    monkeypatch.setattr(cli.time, "time", lambda: 3700.25)

    cli._print_total_time(start_time=100.0)

    captured = capsys.readouterr()
    assert "Time: 1h 0m 0.25s" in captured.out


def test_process_via_server_handles_missing_remote_support() -> None:
    """Remote processing should surface dependency errors and fall back locally."""

    parsed_args = SimpleNamespace(
        server_url="http://localhost:9005",
        output_file=None,
        silent_threshold=None,
        silent_speed=None,
        sounded_speed=None,
        frame_spreadage=None,
        sample_rate=None,
        temp_folder=None,
        keyframe_interval_seconds=None,
        optimize=True,
        small=False,
        server_stream=False,
        video_codec="h264",
        host=None,
        prefer_global_ffmpeg=False,
    )

    app = cli.CliApplication(
        gather_files=lambda paths: list(paths),
        send_video=None,
        speed_up=lambda *_args, **_kwargs: None,
        reporter_factory=lambda: None,
        remote_error_message="Server mode requires the gradio_client dependency. (missing)",
    )

    success, errors, logs = app._process_via_server(
        ["/videos/example.mp4"], parsed_args, 0.0
    )

    assert success is False
    assert errors == [
        "Server mode requires the gradio_client dependency. (missing)",
        "Falling back to local processing pipeline.",
    ]
    assert logs == errors


def test_find_server_tray_binary_prefers_executable_in_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The search helper should prioritise executables discovered via PATH."""

    binary_path = tmp_path / "talks-reducer-server-tray"
    binary_path.write_text("#!/bin/sh\n")
    binary_path.chmod(0o755)

    monkeypatch.setattr(cli.shutil, "which", lambda name: str(binary_path))
    monkeypatch.setattr(cli.sys, "argv", ["cli.py"])

    found = cli._find_server_tray_binary()

    assert found == binary_path


def test_find_server_tray_binary_uses_launcher_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When PATH lookup fails the helper should inspect the launcher directory."""

    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    launcher_path = tmp_path / "bin" / "launcher.py"
    launcher_path.parent.mkdir()
    launcher_path.write_text("print('hello')")
    bundled = launcher_path.parent / "talks-reducer-server-tray"
    bundled.write_text("#!/bin/sh\n")
    bundled.chmod(0o755)

    monkeypatch.setattr(cli.sys, "argv", [str(launcher_path)])

    found = cli._find_server_tray_binary()

    assert found == bundled


def test_should_hide_subprocess_console_detects_detached_windows_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The console hiding helper should return True when no console window is attached."""

    kernel32 = SimpleNamespace(GetConsoleWindow=lambda: 0)
    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(kernel32=kernel32))

    monkeypatch.setattr(cli, "sys", SimpleNamespace(platform="win32", argv=sys.argv))
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert cli._should_hide_subprocess_console() is True


def test_should_hide_subprocess_console_returns_false_for_attached_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a console window is attached the helper should keep the default visibility."""

    kernel32 = SimpleNamespace(GetConsoleWindow=lambda: 100)
    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(kernel32=kernel32))

    monkeypatch.setattr(cli, "sys", SimpleNamespace(platform="win32", argv=sys.argv))
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert cli._should_hide_subprocess_console() is False
