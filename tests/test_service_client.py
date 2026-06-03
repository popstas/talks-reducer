import asyncio
import io
from types import SimpleNamespace
from typing import Optional

import pytest

from talks_reducer import service_client


class DummyJob:
    communicator = None

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self._index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._index >= max(len(self._outputs) - 1, 0):
            raise StopIteration()
        value = self._outputs[self._index]
        self._index += 1
        return value

    def result(self):
        return self._outputs[-1]


class StreamingDummyJob:
    def __init__(self, updates, outputs, result):
        self.communicator = object()
        self._updates = list(updates)
        self._outputs = list(outputs)
        self._result = result
        self.cancelled = False

    def __aiter__(self):
        async def generator():
            for update in self._updates:
                yield update

        return generator()

    def __iter__(self):
        return iter(self._outputs)

    def cancel(self):
        self.cancelled = True

    def result(self):
        return self._result

    def status(self):
        return self._updates[-1] if self._updates else None

    def outputs(self):
        return self._outputs

    def done(self):
        return True


class DummyClient:
    def __init__(self, server_url: str) -> None:
        self.server_url = server_url
        self.submissions = []
        self.job_outputs = []

    def submit(self, *args, **kwargs):
        self.submissions.append((args, kwargs))
        return DummyJob(self.job_outputs)


def test_pump_job_updates_emits_logs_and_progress():
    status_update = SimpleNamespace(
        type="status",
        log=("status log",),
        progress_data=[
            {"desc": "Encode", "length": 8, "index": 4, "progress": 4, "unit": "frames"}
        ],
        code=service_client.Status.PROCESSING,
    )
    output_update = SimpleNamespace(
        type="output",
        outputs=("path", "final log", "summary", "download"),
        final=True,
    )
    job = StreamingDummyJob(
        [status_update, output_update],
        [("path", "final log", "summary", "download")],
        ("path", "final log", "summary", "download"),
    )

    logs: list[str] = []
    progress_events: list[tuple[str, Optional[int], Optional[int], str]] = []

    asyncio.run(
        service_client._pump_job_updates(
            service_client.StreamingJob(job),
            logs.append,
            lambda desc, progress, total, unit: progress_events.append(
                (desc, progress, total, unit)
            ),
        )
    )

    assert logs == ["status log", "final log"]
    assert progress_events == [("Encode", 4, 8, "frames")]


def test_emit_progress_update_uses_normalized_index():
    """An ``index`` field should win over the raw ``progress`` value."""

    events: list[tuple[str, Optional[int], Optional[int], str]] = []
    service_client._emit_progress_update(
        lambda *args: events.append(args),
        {"desc": "Encode", "length": 8, "index": 4, "progress": 0.5, "unit": "frames"},
    )

    assert events == [("Encode", 4, 8, "frames")]


def test_emit_progress_update_uses_raw_count_progress():
    """A raw count in ``progress`` should be forwarded as the current value."""

    events: list[tuple[str, Optional[int], Optional[int], str]] = []
    service_client._emit_progress_update(
        lambda *args: events.append(args),
        {"desc": "Encode", "length": 8, "progress": 4, "unit": "frames"},
    )

    assert events == [("Encode", 4, 8, "frames")]


def test_emit_progress_update_uses_fractional_progress():
    """A fractional ``progress`` value should be scaled by ``length``."""

    events: list[tuple[str, Optional[int], Optional[int], str]] = []
    service_client._emit_progress_update(
        lambda *args: events.append(args),
        {"desc": "Encode", "length": 8, "progress": 0.5, "unit": "frames"},
    )

    assert events == [("Encode", 4, 8, "frames")]


def test_send_video_emits_upload_progress(monkeypatch, tmp_path):
    """``send_video`` should emit start/complete ``Uploading:`` progress events."""

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input-bytes")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.job_outputs = [
        (str(server_file), "log", "summary", str(server_file))
    ]

    monkeypatch.setattr(service_client, "Client", lambda url: client_instance)
    monkeypatch.setattr(
        service_client, "gradio_file", lambda path: SimpleNamespace(path=path)
    )

    progress_events: list[tuple[str, Optional[int], Optional[int], str]] = []
    service_client.send_video(
        input_path=input_file,
        output_path=tmp_path / "output.mp4",
        server_url="http://localhost:9005/",
        progress_callback=lambda *args: progress_events.append(args),
    )

    upload_total = input_file.stat().st_size
    assert progress_events[0] == ("Uploading:", 0, upload_total, "bytes")
    assert ("Uploading:", upload_total, upload_total, "bytes") in progress_events


def test_send_video_without_callback_skips_upload_progress(monkeypatch, tmp_path):
    """Callers without a ``progress_callback`` should behave exactly as before."""

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input-bytes")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.job_outputs = [
        (str(server_file), "log", "summary", str(server_file))
    ]

    monkeypatch.setattr(service_client, "Client", lambda url: client_instance)
    monkeypatch.setattr(
        service_client, "gradio_file", lambda path: SimpleNamespace(path=path)
    )

    destination, summary, log_text = service_client.send_video(
        input_path=input_file,
        output_path=tmp_path / "output.mp4",
        server_url="http://localhost:9005/",
    )

    assert destination == tmp_path / "output.mp4"
    assert summary == "summary"
    assert log_text == "log"


def test_send_video_stream_updates_cancel(monkeypatch, tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"output")

    final_result = (
        str(server_file),
        "log",
        "summary",
        str(server_file),
    )
    updates = [
        SimpleNamespace(
            type="status",
            log=("status",),
            progress_data=None,
            code=service_client.Status.PROCESSING,
        )
    ]

    job_holder: dict[str, StreamingDummyJob] = {}

    def job_factory(client, args, kwargs):
        job = StreamingDummyJob(updates, [final_result], final_result)
        job_holder["job"] = job
        return job

    cancel_calls = {"count": 0}

    def should_cancel() -> bool:
        cancel_calls["count"] += 1
        return True

    monkeypatch.setattr(
        service_client,
        "gradio_file",
        lambda path: SimpleNamespace(path=path),
    )

    with pytest.raises(service_client.ProcessingAborted):
        service_client.send_video(
            input_path=input_file,
            output_path=None,
            server_url="http://localhost:9005/",
            stream_updates=True,
            should_cancel=should_cancel,
            client_factory=lambda url: DummyClient(url),
            job_factory=job_factory,
        )

    assert cancel_calls["count"] >= 1
    assert job_holder["job"].cancelled is True


def test_stream_job_updates_fallback_to_poll_on_runtime_error(monkeypatch):
    job = StreamingDummyJob([], [], (None, None, None, None))
    streaming_job = service_client.StreamingJob(job)

    logs: list[str] = []
    progress_events: list[tuple[str, Optional[int], Optional[int], str]] = []

    def fake_asyncio_run(coro, *args, **kwargs):
        try:
            coro.close()
        finally:
            raise RuntimeError("loop is closed")

    monkeypatch.setattr(service_client.asyncio, "run", fake_asyncio_run)

    captured: dict[str, object] = {}

    def fake_poll(
        job_arg,
        emit_log,
        progress_callback,
        *,
        cancel_callback=None,
        interval: float = 0.25,
    ) -> None:
        captured["job"] = job_arg
        emit_log("polled")
        if progress_callback is not None:
            progress_callback("Polled", 1, 2, "steps")

    monkeypatch.setattr(service_client, "_poll_job_updates", fake_poll)

    result = service_client._stream_job_updates(
        streaming_job,
        logs.append,
        progress_callback=lambda *args: progress_events.append(args),
    )

    assert result is True
    assert logs == ["polled"]
    assert progress_events == [("Polled", 1, 2, "steps")]
    assert captured["job"] is streaming_job


def test_stream_job_updates_propagates_cancellation(monkeypatch):
    """A cancellation raised during async streaming must not restart polling."""

    job = StreamingDummyJob([], [], (None, None, None, None))
    streaming_job = service_client.StreamingJob(job)

    def fake_asyncio_run(coro, *args, **kwargs):
        try:
            coro.close()
        finally:
            raise service_client.ProcessingAborted("cancelled")

    monkeypatch.setattr(service_client.asyncio, "run", fake_asyncio_run)

    def fail_poll(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("polling fallback should not run on cancellation")

    monkeypatch.setattr(service_client, "_poll_job_updates", fail_poll)

    with pytest.raises(service_client.ProcessingAborted):
        service_client._stream_job_updates(streaming_job, lambda _msg: None)


def test_send_video_downloads_file(monkeypatch, tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.job_outputs = [
        (str(server_file), "log", "summary", str(server_file))
    ]

    monkeypatch.setattr(service_client, "Client", lambda url: client_instance)
    monkeypatch.setattr(
        service_client, "gradio_file", lambda path: SimpleNamespace(path=path)
    )

    destination, summary, log_text = service_client.send_video(
        input_path=input_file,
        output_path=tmp_path / "output.mp4",
        server_url="http://localhost:9005/",
        small=True,
    )

    assert destination == tmp_path / "output.mp4"
    assert destination.read_bytes() == server_file.read_bytes()
    assert summary == "summary"
    assert log_text == "log"
    assert client_instance.submissions, "submit was not called"
    submission_args, submission_kwargs = client_instance.submissions[0]
    assert submission_args[1] is True
    assert submission_args[2] is False
    assert submission_args[3] is True
    assert submission_args[4] == "hevc"
    assert submission_args[5] is False
    assert submission_args[6] is False
    assert submission_args[7:10] == (None, None, None)
    assert submission_kwargs.get("api_name") == "/process_video"


def test_send_video_streams_logs(monkeypatch, tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.job_outputs = [
        (None, "first", None, None),
        (None, "first\nsecond", None, None),
        (str(server_file), "first\nsecond\nthird", "summary", str(server_file)),
    ]

    monkeypatch.setattr(service_client, "Client", lambda url: client_instance)
    monkeypatch.setattr(
        service_client, "gradio_file", lambda path: SimpleNamespace(path=path)
    )

    streamed_lines = []
    destination, summary, log_text = service_client.send_video(
        input_path=input_file,
        output_path=None,
        server_url="http://localhost:9005/",
        log_callback=streamed_lines.append,
    )

    assert streamed_lines == ["first", "second", "third"]
    assert summary == "summary"
    assert log_text == "first\nsecond\nthird"
    assert destination.name == server_file.name


def test_send_video_stream_flag(monkeypatch, tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.job_outputs = [
        (str(server_file), "first\nsecond", "summary", str(server_file))
    ]

    monkeypatch.setattr(service_client, "Client", lambda url: client_instance)
    monkeypatch.setattr(
        service_client, "gradio_file", lambda path: SimpleNamespace(path=path)
    )

    stream_calls = []

    def _fake_stream(job, emit_log, *, progress_callback=None):
        stream_calls.append((job, progress_callback))
        emit_log("first")
        if progress_callback is not None:
            progress_callback("Processing", 1, 4, "frames")
        return True

    monkeypatch.setattr(service_client, "_stream_job_updates", _fake_stream)

    streamed_lines: list[str] = []
    progress_events: list[tuple[str, Optional[int], Optional[int], str]] = []

    destination, summary, log_text = service_client.send_video(
        input_path=input_file,
        output_path=None,
        server_url="http://localhost:9005/",
        log_callback=streamed_lines.append,
        stream_updates=True,
        progress_callback=lambda *args: progress_events.append(args),
    )

    assert stream_calls, "stream helper was not invoked"
    assert streamed_lines == ["first", "second"]
    upload_total = input_file.stat().st_size
    assert progress_events == [
        ("Uploading:", 0, upload_total, "bytes"),
        ("Uploading:", upload_total, upload_total, "bytes"),
        ("Processing", 1, 4, "frames"),
    ]
    assert summary == "summary"
    assert log_text == "first\nsecond"
    assert destination.name == server_file.name


@pytest.mark.parametrize("codec", ["av1", "hevc"])
def test_send_video_forwards_custom_options(monkeypatch, tmp_path, codec):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.job_outputs = [
        (str(server_file), "log", "summary", str(server_file))
    ]

    monkeypatch.setattr(service_client, "Client", lambda url: client_instance)
    monkeypatch.setattr(
        service_client, "gradio_file", lambda path: SimpleNamespace(path=path)
    )

    destination, summary, log_text = service_client.send_video(
        input_path=input_file,
        output_path=None,
        server_url="http://localhost:9005/",
        video_codec=codec,
        prefer_global_ffmpeg=True,
        silent_threshold=0.12,
        sounded_speed=1.5,
        silent_speed=6.0,
    )

    assert destination.name == server_file.name
    assert summary == "summary"
    assert log_text == "log"
    submission_args, _ = client_instance.submissions[0]
    assert submission_args[2] is False
    assert submission_args[3] is True
    assert submission_args[4] == codec
    assert submission_args[5] is False
    assert submission_args[6] is True
    assert submission_args[7:10] == (0.12, 1.5, 6.0)


def test_send_video_honors_add_codec_suffix(monkeypatch, tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.job_outputs = [
        (str(server_file), "log", "summary", str(server_file))
    ]

    monkeypatch.setattr(service_client, "Client", lambda url: client_instance)
    monkeypatch.setattr(
        service_client, "gradio_file", lambda path: SimpleNamespace(path=path)
    )

    destination, *_ = service_client.send_video(
        input_path=input_file,
        output_path=None,
        server_url="http://localhost:9005/",
        add_codec_suffix=True,
    )

    assert destination.name == server_file.name
    submission_args, _ = client_instance.submissions[0]
    assert submission_args[3] is True
    assert submission_args[5] is True


def test_send_video_defaults_to_current_directory(monkeypatch, tmp_path, cwd_tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.job_outputs = [
        (str(server_file), "log", "summary", str(server_file))
    ]

    monkeypatch.setattr(service_client, "Client", lambda url: client_instance)
    monkeypatch.setattr(
        service_client, "gradio_file", lambda path: SimpleNamespace(path=path)
    )

    destination, _, _ = service_client.send_video(
        input_path=input_file,
        output_path=None,
        server_url="http://localhost:9005/",
    )

    assert destination.parent == cwd_tmp_path
    assert destination.name == server_file.name
    assert destination.read_bytes() == server_file.read_bytes()


def test_main_prints_summary(monkeypatch, tmp_path, capsys):
    input_file = tmp_path / "input.mp4"
    destination_file = tmp_path / "output.mp4"

    def fake_send_video(*, log_callback=None, **kwargs):
        assert kwargs["small"] is False
        assert kwargs["small_480"] is False
        assert kwargs["stream_updates"] is False
        assert kwargs["video_codec"] == "hevc"
        if log_callback is not None:
            log_callback("log")
        return destination_file, "summary", "log"

    monkeypatch.setattr(
        service_client, "send_video", lambda **kwargs: fake_send_video(**kwargs)
    )

    service_client.main(
        [
            str(input_file),
            "--server",
            "http://localhost:9005/",
            "--output",
            str(destination_file),
        ]
    )

    captured = capsys.readouterr()
    assert "summary" in captured.out
    assert str(destination_file) in captured.out


def test_main_stream_option(monkeypatch, tmp_path, capsys):
    input_file = tmp_path / "input.mp4"
    destination_file = tmp_path / "output.mp4"

    def fake_send_video(*, progress_callback=None, **kwargs):
        assert kwargs["stream_updates"] is True
        assert kwargs["small_480"] is False
        assert kwargs["video_codec"] == "hevc"
        assert callable(progress_callback)
        if progress_callback is not None:
            progress_callback("Processing", 2, 4, "frames")
        return destination_file, "summary", "log"

    monkeypatch.setattr(service_client, "send_video", fake_send_video)

    service_client.main(
        [
            str(input_file),
            "--server",
            "http://localhost:9005/",
            "--output",
            str(destination_file),
            "--stream",
        ]
    )

    captured = capsys.readouterr()
    assert "Processing: 2/4 50.0% frames" in captured.out


def test_main_small_480_option(monkeypatch, tmp_path, capsys):
    input_file = tmp_path / "input.mp4"
    destination_file = tmp_path / "output.mp4"

    def fake_send_video(**kwargs):
        assert kwargs["small"] is True
        assert kwargs["small_480"] is True
        assert kwargs["video_codec"] == "hevc"
        return destination_file, "summary", "log"

    monkeypatch.setattr(service_client, "send_video", fake_send_video)

    service_client.main(
        [
            str(input_file),
            "--server",
            "http://localhost:9005/",
            "--output",
            str(destination_file),
            "--small",
            "--480",
        ]
    )

    captured = capsys.readouterr()
    assert "summary" in captured.out
    assert str(destination_file) in captured.out


def test_main_warns_when_480_without_small(monkeypatch, tmp_path, capsys):
    input_file = tmp_path / "input.mp4"
    destination_file = tmp_path / "output.mp4"

    def fake_send_video(**kwargs):
        assert kwargs["small"] is False
        assert kwargs["small_480"] is False
        assert kwargs["video_codec"] == "hevc"
        return destination_file, "summary", "log"

    monkeypatch.setattr(service_client, "send_video", fake_send_video)

    service_client.main(
        [
            str(input_file),
            "--server",
            "http://localhost:9005/",
            "--output",
            str(destination_file),
            "--480",
        ]
    )

    captured = capsys.readouterr()
    assert "Warning: --480 has no effect" in captured.err


@pytest.mark.parametrize("codec", ["av1", "hevc"])
def test_main_video_codec_option(monkeypatch, tmp_path, capsys, codec):
    input_file = tmp_path / "input.mp4"
    destination_file = tmp_path / "output.mp4"

    input_file.write_bytes(b"input")

    def fake_send_video(**kwargs):
        assert kwargs["video_codec"] == codec
        return destination_file, "summary", "log"

    monkeypatch.setattr(service_client, "send_video", fake_send_video)

    service_client.main(
        [
            str(input_file),
            "--server",
            "http://localhost:9005/",
            "--output",
            str(destination_file),
            "--video-codec",
            codec,
        ]
    )

    captured = capsys.readouterr()
    assert "summary" in captured.out
    assert str(destination_file) in captured.out


def test_main_prefer_global_ffmpeg_option(monkeypatch, tmp_path, capsys):
    input_file = tmp_path / "input.mp4"
    destination_file = tmp_path / "output.mp4"

    input_file.write_bytes(b"input")

    def fake_send_video(**kwargs):
        assert kwargs["prefer_global_ffmpeg"] is True
        return destination_file, "summary", "log"

    monkeypatch.setattr(service_client, "send_video", fake_send_video)

    service_client.main(
        [
            str(input_file),
            "--server",
            "http://localhost:9005/",
            "--output",
            str(destination_file),
            "--prefer-global-ffmpeg",
        ]
    )

    captured = capsys.readouterr()
    assert "summary" in captured.out
    assert str(destination_file) in captured.out


def test_progress_file_reader_reports_each_chunk():
    """The reader proxies the file and forwards the size of every chunk read."""

    counts: list[int] = []
    reader = service_client._ProgressFileReader(
        io.BytesIO(b"abcdefghij"), counts.append
    )

    assert reader.read(4) == b"abcd"
    assert reader.read(4) == b"efgh"
    assert reader.read(4) == b"ij"
    assert reader.read(4) == b""  # exhausted; no extra event

    assert counts == [4, 4, 2]


def test_wrap_upload_files_wraps_only_file_objects():
    counts: list[int] = []
    fileobj = io.BytesIO(b"payload")
    files = [("files", ("clip.mp4", fileobj))]

    wrapped = service_client._wrap_upload_files(files, counts.append)

    field, spec = wrapped[0]
    assert field == "files"
    assert spec[0] == "clip.mp4"
    assert isinstance(spec[1], service_client._ProgressFileReader)
    assert spec[1].read() == b"payload"
    assert counts == [7]


def test_progress_response_emits_download_events():
    response = SimpleNamespace(
        headers={"content-length": "6"},
        iter_bytes=lambda: iter([b"abc", b"def"]),
    )
    events: list[tuple[str, Optional[int], Optional[int], str]] = []

    proxy = service_client._ProgressResponse(
        response, lambda *args: events.append(args)
    )
    chunks = list(proxy.iter_bytes())

    assert chunks == [b"abc", b"def"]
    assert events == [
        ("Downloading:", 0, 6, "bytes"),
        ("Downloading:", 3, 6, "bytes"),
        ("Downloading:", 6, 6, "bytes"),
    ]


def test_install_transfer_progress_streams_upload_and_download(monkeypatch, tmp_path):
    """Patched endpoint reports byte-level upload and download progress."""

    upload_file = tmp_path / "input.mp4"
    upload_file.write_bytes(b"0123456789")

    class FakeEndpoint:
        def _upload_file(self, file_obj, data_index=0):
            # Mirror gradio's real upload: open the file and POST it via httpx.
            with open(file_obj["path"], "rb") as handle:
                service_client_module.httpx.post(
                    "http://server/upload",
                    files=[("files", ("input.mp4", handle))],
                )
            return {"path": "/server/input.mp4"}

        def _download_file(self, payload):
            with service_client_module.httpx.stream(
                "GET", "http://server/file"
            ) as response:
                return b"".join(response.iter_bytes())

    class FakeClient:
        def __init__(self):
            self.endpoints = {0: FakeEndpoint()}

        def _infer_fn_index(self, api_name, fn_index):
            return 0

    import gradio_client.client as service_client_module

    def fake_post(url, *args, files=None, **kwargs):
        # httpx reads the wrapped file in chunks while streaming the body.
        for _field, spec in files:
            handle = spec[1]
            while handle.read(4):
                pass
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: ["/x"])

    def fake_stream(method, url, *args, **kwargs):
        class _CM:
            def __enter__(self):
                return SimpleNamespace(
                    headers={"content-length": "8"},
                    iter_bytes=lambda *a, **k: iter([b"abcd", b"efgh"]),
                    raise_for_status=lambda: None,
                )

            def __exit__(self, *exc):
                return False

        return _CM()

    monkeypatch.setattr(service_client_module.httpx, "post", fake_post)
    monkeypatch.setattr(service_client_module.httpx, "stream", fake_stream)

    client = FakeClient()
    events: list[tuple[str, Optional[int], Optional[int], str]] = []

    installed = service_client._install_transfer_progress(
        client,
        "/process_video",
        upload_file.stat().st_size,
        lambda *args: events.append(args),
    )

    assert installed is True

    endpoint = client.endpoints[0]
    endpoint._upload_file({"path": str(upload_file)})

    upload_events = [event for event in events if event[0] == "Uploading:"]
    assert ("Uploading:", 4, 10, "bytes") in upload_events
    assert upload_events[-1] == ("Uploading:", 10, 10, "bytes")
    # The original httpx.post must be restored after the upload.
    assert service_client_module.httpx.post is fake_post

    events.clear()
    endpoint._download_file({"path": "/server/input.mp4"})
    download_events = [event for event in events if event[0] == "Downloading:"]
    assert download_events[0] == ("Downloading:", 0, 8, "bytes")
    assert download_events[-1] == ("Downloading:", 8, 8, "bytes")
    assert service_client_module.httpx.stream is fake_stream


def test_install_transfer_progress_restores_httpx_on_error(monkeypatch, tmp_path):
    """A failing upload/download still restores the patched httpx globals."""

    upload_file = tmp_path / "input.mp4"
    upload_file.write_bytes(b"0123456789")

    class FakeEndpoint:
        def _upload_file(self, file_obj, data_index=0):
            raise RuntimeError("upload boom")

        def _download_file(self, payload):
            raise RuntimeError("download boom")

    class FakeClient:
        def __init__(self):
            self.endpoints = {0: FakeEndpoint()}

        def _infer_fn_index(self, api_name, fn_index):
            return 0

    import gradio_client.client as service_client_module

    sentinel_post = object()
    sentinel_stream = object()
    monkeypatch.setattr(service_client_module.httpx, "post", sentinel_post)
    monkeypatch.setattr(service_client_module.httpx, "stream", sentinel_stream)

    client = FakeClient()
    installed = service_client._install_transfer_progress(
        client, "/process_video", upload_file.stat().st_size, lambda *args: None
    )
    assert installed is True

    # Invoking the patched endpoint methods raises, but the ``finally`` blocks
    # must restore the module-global httpx hooks so a later transfer is not
    # corrupted by a leaked monkeypatch.
    endpoint = client.endpoints[0]

    with pytest.raises(RuntimeError, match="upload boom"):
        endpoint._upload_file({"path": str(upload_file)})
    assert service_client_module.httpx.post is sentinel_post

    with pytest.raises(RuntimeError, match="download boom"):
        endpoint._download_file({"path": "/server/input.mp4"})
    assert service_client_module.httpx.stream is sentinel_stream


def test_install_transfer_progress_skips_completion_on_upload_error(
    monkeypatch, tmp_path
):
    """A failing upload must not emit a misleading 100% completion event."""

    upload_file = tmp_path / "input.mp4"
    upload_file.write_bytes(b"0123456789")

    class FakeEndpoint:
        def _upload_file(self, file_obj, data_index=0):
            raise RuntimeError("upload boom")

        def _download_file(self, payload):  # pragma: no cover - unused here
            return payload

    class FakeClient:
        def __init__(self):
            self.endpoints = {0: FakeEndpoint()}

        def _infer_fn_index(self, api_name, fn_index):
            return 0

    import gradio_client.client as service_client_module

    monkeypatch.setattr(service_client_module.httpx, "post", object())

    client = FakeClient()
    events: list[tuple[str, Optional[int], Optional[int], str]] = []

    installed = service_client._install_transfer_progress(
        client,
        "/process_video",
        upload_file.stat().st_size,
        lambda *args: events.append(args),
    )
    assert installed is True

    with pytest.raises(RuntimeError, match="upload boom"):
        client.endpoints[0]._upload_file({"path": str(upload_file)})

    completion = ("Uploading:", 10, 10, "bytes")
    assert completion not in events


def test_install_transfer_progress_returns_false_for_stub_client():
    class StubClient:
        pass

    installed = service_client._install_transfer_progress(
        StubClient(), "/process_video", 10, lambda *args: None
    )

    assert installed is False


@pytest.fixture
def cwd_tmp_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return tmp_path
