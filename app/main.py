import asyncio
import hashlib
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings
from app.controller import Controller
from app.schemas import TERMINAL, DiscoveryError, Run, now
from app.storage import Store
from app.urls import normalize_job_url

STATIC = Path(__file__).parent / "static"


class RevalidatingStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class Submission(BaseModel):
    url: str = Field(max_length=2048)


def create_app(settings: Settings | None = None, controller_factory=Controller):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        store = Store(settings.data_dir / "runs.sqlite3")
        store.interrupt_pending()
        queue = asyncio.Queue(maxsize=settings.max_queue_size)
        app.state.store, app.state.queue = store, queue
        app.state.active = None
        app.state.active_id = None
        controller = controller_factory(settings, store)

        async def worker():
            while True:
                run_id = await queue.get()
                try:
                    run = store.get(run_id)
                    if run.status in TERMINAL:
                        continue
                    app.state.active_id = run_id
                    app.state.active = asyncio.create_task(controller.execute(run))
                    await app.state.active
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                finally:
                    app.state.active, app.state.active_id = None, None
                    queue.task_done()
                if asyncio.current_task().cancelling():
                    return

        worker_task = asyncio.create_task(worker())
        try:
            yield
        finally:
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
            store.close()

    app = FastAPI(title="Job Source Agent", lifespan=lifespan)
    submissions = defaultdict(deque)
    app.mount("/static", RevalidatingStaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        version = hashlib.sha256((STATIC / "app.js").read_bytes() + (STATIC / "style.css").read_bytes()).hexdigest()[:12]
        html = (STATIC / "index.html").read_text().replace("__ASSET_VERSION__", version)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "version": "0.3.0"}

    @app.get("/api/config")
    async def config():
        return {"configured": not settings.missing(), "missing": settings.missing(),
                "deadline_seconds": settings.run_timeout_seconds, "max_actions": settings.max_actions}

    @app.post("/api/runs", status_code=202)
    async def submit(body: Submission, request: Request):
        try:
            canonical = normalize_job_url(body.url)
        except DiscoveryError as exc:
            raise HTTPException(422, exc.reason) from None
        if settings.missing():
            raise HTTPException(503, "Provider credentials are not configured.")
        if app.state.queue.full():
            raise HTTPException(429, "Run queue is full. Please try again shortly.")
        timestamp = time.monotonic()
        # Remove expired clients too, so the limiter does not grow forever.
        for client in list(submissions):
            while submissions[client] and submissions[client][0] < timestamp - 3600:
                submissions[client].popleft()
            if not submissions[client]:
                del submissions[client]
        client = request.client.host if request.client else "unknown"
        if len(submissions[client]) >= settings.requests_per_hour:
            raise HTTPException(429, "Hourly submission limit reached. Please try again later.")
        submissions[client].append(timestamp)
        run = Run(run_id=uuid4().hex, input_url=body.url, normalized_input_url=canonical)
        app.state.store.save(run)
        app.state.queue.put_nowait(run.run_id)
        return run

    def get_run(run_id):
        run = app.state.store.get(run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        return run

    @app.get("/api/runs/{run_id}")
    async def result(run_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return get_run(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        run = get_run(run_id)
        if run.status in TERMINAL:
            return run
        if app.state.active_id == run_id and app.state.active:
            app.state.active.cancel()
        else:
            run.status, run.failure_code, run.finished_at = "cancelled", "cancelled", now()
            run.failure_reason = "Cancelled while queued."
            app.state.store.save(run)
        return {"run_id": run_id, "cancellation_requested": True}

    @app.get("/api/runs/{run_id}/artifacts/{filename}")
    async def artifact(run_id: str, filename: str):
        get_run(run_id)
        if not re.fullmatch(r"[a-f0-9]{32}", run_id) or not re.fullmatch(r"step-\d{2}\.png", filename):
            raise HTTPException(404)
        path = settings.data_dir / "artifacts" / run_id / filename
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png")

    return app


app = create_app()
