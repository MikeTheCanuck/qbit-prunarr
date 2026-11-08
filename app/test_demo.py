"""The demo has to keep showing every group, or the README screenshots
drift from what the app does. Runs the real scan against the fake services."""
import os
import socket
import threading
import time

import pytest
import uvicorn

import demo
import main


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def demo_stack(tmp_path, monkeypatch):
    saved = dict(os.environ)
    monkeypatch.setattr(demo, "FAKE_PORT", _free_port())
    root = str(tmp_path / "lib")
    demo.build_library(root)
    demo.configure_env(root)
    server = uvicorn.Server(uvicorn.Config(demo.make_services(root), host="127.0.0.1",
                                           port=demo.FAKE_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    yield root
    server.should_exit = True
    os.environ.clear()
    os.environ.update(saved)


def test_demo_scan_fills_every_group(demo_stack):
    candidates, statuses = main.run_scan()

    assert set(statuses.values()) == {"ok"}
    verdicts = {c.verdict.kind for c in candidates if c.category == "orphaned media"}
    assert verdicts == {"junk", "wanted", "plex", "identify", "call"}
    assert len(main._extras_cache) == 2
    downloads = [p for c in candidates if c.category == "unlinked download" for p in c.paths]
    assert any("Metropolis" in p for p in downloads)
    # Radarr's queue still claims The Kid, so it must never be offered for deletion.
    assert not any("The.Kid" in p for p in downloads)
