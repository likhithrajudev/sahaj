"""Serving the built PWA (apps/web/dist) from FastAPI: app routes fall back to index.html, the API never does."""
import asyncio
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import API_PREFIXES, SPAStaticFiles


def make_app(dist: Path) -> FastAPI:
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Sahaj PWA</title>")
    (dist / "sw.js").write_text("// service worker")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.mount("/", SPAStaticFiles(directory=dist, html=True), name="web")
    return app


def get(app, path):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            return await c.get(path)
    return asyncio.run(go())


def test_app_shell_and_client_routes(tmp_path):
    app = make_app(tmp_path / "dist")
    assert "Sahaj PWA" in get(app, "/").text
    assert "Sahaj PWA" in get(app, "/some/screen").text        # client-side route -> index.html
    assert get(app, "/assets/app.js").status_code == 200
    assert get(app, "/health").json() == {"status": "ok"}       # routes win over the mount


def test_missing_files_and_api_paths_are_not_the_app(tmp_path):
    app = make_app(tmp_path / "dist")
    assert get(app, "/assets/missing.js").status_code == 404    # a missing file is a 404, not the page
    for prefix in ("users", "auth", "chat", "files", "desk"):
        assert prefix in API_PREFIXES
        assert get(app, f"/{prefix}/does-not-exist").status_code == 404


def test_new_deploys_reach_installed_apps(tmp_path):
    app = make_app(tmp_path / "dist")
    assert get(app, "/sw.js").headers["cache-control"] == "no-cache"
    assert get(app, "/").headers["cache-control"] == "no-cache"
