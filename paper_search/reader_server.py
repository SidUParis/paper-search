"""Private Reader Workbench local HTTP server.

The server is intentionally small and stdlib-only for the first milestone: it
serves a generated reader-site directory and exposes safe JSON APIs that future
LLM/chat/job features can build on. Secrets and local runtime paths are never
returned by the public config endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import unquote, urlparse


@dataclass(frozen=True, slots=True)
class ReaderServerConfig:
    """Runtime settings for the local reader server."""

    site_dir: Path
    profile: str = "private"
    site_title: str = "Sidney Deep Paper Reader"


@dataclass(frozen=True, slots=True)
class TestResponse:
    """In-memory response used by unit tests without binding a socket."""

    status: int
    headers: dict[str, str]
    body: bytes


class _HeaderBuffer:
    def __init__(self) -> None:
        self.status = 0
        self.headers: dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.headers[keyword] = value

    def end_headers(self) -> None:  # pragma: no cover - hook for handler API
        return None


def _json_bytes(payload: dict[str, Any] | list[Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _safe_public_config(config: ReaderServerConfig) -> dict[str, Any]:
    return {
        "profile": config.profile,
        "site_title": config.site_title,
        "features": {
            "chat": False,
            "models": False,
            "jobs": False,
            "figures": False,
        },
    }


def _load_papers(site_dir: Path) -> list[dict[str, Any]]:
    data_path = site_dir / "data" / "papers.json"
    if not data_path.exists():
        return []
    data = json.loads(data_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("papers"), list):
        return [item for item in data["papers"] if isinstance(item, dict)]
    return []


def _papers_payload(site_dir: Path) -> dict[str, Any]:
    papers = _load_papers(site_dir)
    topics = sorted({str(p.get("topic_slug") or "").strip() for p in papers if str(p.get("topic_slug") or "").strip()})
    sources = sorted({str(p.get("source_label") or "").strip() for p in papers if str(p.get("source_label") or "").strip()})
    return {"count": len(papers), "topics": topics, "sources": sources, "papers": papers}


def _resolve_static_path(site_dir: Path, request_path: str) -> Path | None:
    parsed = urlparse(request_path)
    raw_path = unquote(parsed.path)
    if raw_path in {"", "/"}:
        raw_path = "/index.html"
    relative = raw_path.lstrip("/")
    candidate = (site_dir / relative).resolve()
    root = site_dir.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def create_reader_handler(config: ReaderServerConfig):
    """Create a request handler class bound to one reader-server config."""

    class ReaderRequestHandler(SimpleHTTPRequestHandler):
        server_version = "PaperSearchReader/0.1"
        _reader_config = config

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - inherited API
            # Keep the local service quiet by default; future ops docs can wire logs.
            return None

        def do_GET(self) -> None:  # noqa: N802 - inherited API
            self._dispatch_get(self.path)

        def _dispatch_get(self, request_path: str) -> None:
            parsed = urlparse(request_path)
            path = parsed.path
            if path == "/health":
                self._send_json({"status": "ok", "profile": config.profile, "site_title": config.site_title})
                return
            if path == "/api/config/public":
                self._send_json(_safe_public_config(config))
                return
            if path == "/api/papers":
                self._send_json(_papers_payload(config.site_dir))
                return
            if path.startswith("/api/"):
                self._send_json({"error": "not_found", "path": path}, status=HTTPStatus.NOT_FOUND)
                return

            static_path = _resolve_static_path(config.site_dir, request_path)
            if static_path is None:
                self._send_bytes(b"Not found", status=HTTPStatus.NOT_FOUND, content_type="text/plain; charset=utf-8")
                return
            content_type = mimetypes.guess_type(str(static_path))[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
                content_type = f"{content_type}; charset=utf-8"
            self._send_bytes(static_path.read_bytes(), content_type=content_type)

        def _send_json(self, payload: dict[str, Any] | list[Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(_json_bytes(payload), status=status, content_type="application/json; charset=utf-8")

        def _send_bytes(self, body: bytes, status: HTTPStatus = HTTPStatus.OK, content_type: str = "application/octet-stream") -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        @classmethod
        def handle_test_request(cls, path: str) -> TestResponse:
            """Exercise the handler without opening a network socket."""

            instance = cls.__new__(cls)
            instance.path = path
            instance.wfile = io.BytesIO()
            header_buffer = _HeaderBuffer()
            instance.send_response = header_buffer.send_response  # type: ignore[method-assign]
            instance.send_header = header_buffer.send_header  # type: ignore[method-assign]
            instance.end_headers = header_buffer.end_headers  # type: ignore[method-assign]
            instance._dispatch_get(path)
            return TestResponse(status=header_buffer.status, headers=header_buffer.headers, body=instance.wfile.getvalue())

    return ReaderRequestHandler


class ReaderHTTPServer(ThreadingHTTPServer):
    """Typed alias for the local reader HTTP server."""

    def __enter__(self) -> "ReaderHTTPServer":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.server_close()


def make_server(config: ReaderServerConfig, host: str = "127.0.0.1", port: int = 8765) -> ReaderHTTPServer:
    handler = create_reader_handler(config)
    return ReaderHTTPServer((host, port), handler)


def serve(config: ReaderServerConfig, host: str = "127.0.0.1", port: int = 8765) -> None:
    if not config.site_dir.exists():
        raise FileNotFoundError(f"reader site directory does not exist: {config.site_dir}")
    with make_server(config, host=host, port=port) as httpd:
        print(f"Serving {config.site_dir} on http://{host}:{port} ({config.profile})")
        httpd.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the private paper reader site with JSON APIs.")
    parser.add_argument("--site-dir", default="private-reader-site")
    parser.add_argument("--profile", default="private", choices=["private", "public"])
    parser.add_argument("--site-title", default="Sidney Deep Paper Reader")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve(
        ReaderServerConfig(site_dir=Path(args.site_dir), profile=args.profile, site_title=args.site_title),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
