import asyncio
import time

from fastapi.testclient import TestClient

from app.controller import Controller
from app.main import create_app
from tests.test_controller import FakeBrowser, FakeModel, FakeProvider


def test_local_ui_and_complete_api_flow(settings):
    def factory(s, store):
        return Controller(s, store, FakeProvider, FakeModel, FakeBrowser)
    with TestClient(create_app(settings, factory)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.post("/api/runs", json={"url": "https://evil.org/"}).status_code == 422
        response = client.post("/api/runs", json={"url": "https://www.linkedin.com/jobs/view/4427787182/"})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}").json()
            if run["status"] == "succeeded":
                break
            time.sleep(.01)
        assert run["status"] == "succeeded"
        assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "succeeded"
        assert client.get("/api/runs/not-a-run").status_code == 404
        assert client.get(f"/api/runs/{run_id}/artifacts/not-allowed.txt").status_code == 404


def test_shutdown_cancels_active_run_without_hanging(settings):
    class SlowProvider(FakeProvider):
        async def extract(self, url):
            await asyncio.sleep(30)
    def factory(s, store):
        return Controller(s, store, SlowProvider, FakeModel, FakeBrowser)
    started = time.monotonic()
    with TestClient(create_app(settings, factory)) as client:
        run_id = client.post("/api/runs", json={"url": "https://www.linkedin.com/jobs/view/4427787182/"}).json()["run_id"]
        for _ in range(100):
            if client.get(f"/api/runs/{run_id}").json()["status"] == "running":
                break
            time.sleep(.01)
    assert time.monotonic() - started < 5
