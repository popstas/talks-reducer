from types import SimpleNamespace

import pytest

from talks_reducer import service_client


class DummyClient:
    def __init__(self, server_url: str) -> None:
        self.server_url = server_url
        self.predictions = []

    def predict(self, *args, **kwargs):  # pragma: no cover - replaced in tests
        raise NotImplementedError


def test_send_video_downloads_file(monkeypatch, tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")

    def fake_predict(file_arg, small_flag, api_name):
        assert api_name == "/process_video"
        assert small_flag is True
        client_instance.predictions.append((file_arg, small_flag, api_name))
        return (None, "log", "summary", str(server_file))

    client_instance.predict = fake_predict

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
    assert client_instance.predictions, "predict was not called"


def test_send_video_defaults_to_current_directory(monkeypatch, tmp_path, cwd_tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"input")
    server_file = tmp_path / "server_output.mp4"
    server_file.write_bytes(b"processed")

    client_instance = DummyClient("http://localhost:9005/")
    client_instance.predict = lambda *_, **__: (
        None,
        "log",
        "summary",
        str(server_file),
    )

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

    def fake_send_video(**kwargs):
        assert kwargs["small"] is False
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


@pytest.fixture
def cwd_tmp_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return tmp_path
