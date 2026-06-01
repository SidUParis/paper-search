"""Private Reader Workbench local HTTP server.

The server is intentionally small and stdlib-only for the first milestone: it
serves a generated reader-site directory and exposes safe JSON APIs that future
LLM/chat/job features can build on. Secrets and local runtime paths are never
returned by the public config endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


def _path_is_allowed(path: Path, roots: list[Path]) -> bool:
    resolved = path.expanduser().resolve()
    allowed = [root.expanduser().resolve() for root in roots]
    if not allowed:
        return False
    return any(resolved.is_relative_to(root) for root in allowed)


def _paper_asset_path(site_dir: Path, paper_key: str, kind: str, allowed_roots: list[Path]) -> Path | None:
    if kind not in {"document", "fulltext", "note"}:
        return None
    papers = _load_papers(site_dir)
    paper = next((p for p in papers if str(p.get("paper_id") or "") == paper_key), None)
    if paper is None:
        return None
    field = {"document": "local_document", "fulltext": "local_fulltext", "note": "obsidian_note"}[kind]
    raw = str(paper.get(field) or "")
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    if not _path_is_allowed(resolved, allowed_roots):
        return None
    return resolved


@dataclass(frozen=True, slots=True)
class ReaderServerConfig:
    """Runtime settings for the local reader server."""

    site_dir: Path
    profile: str = "private"
    site_title: str = "Sidney Deep Paper Reader"
    state_dir: Path = Path(".reader")
    allowed_context_roots: list[Path] = field(default_factory=list)


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
            "chat": True,
            "models": True,
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

        def do_POST(self) -> None:  # noqa: N802 - inherited API
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length) if length else b"{}"
            self._dispatch_post(self.path, raw_body)

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
            if path == "/api/models":
                from paper_search.reader_models import ReaderModelRegistry

                self._send_json(ReaderModelRegistry(config.state_dir).public_config())
                return
            if path.startswith("/api/papers/") and path.endswith("/context"):
                from paper_search.reader_context import build_paper_context

                paper_key = unquote(path.removeprefix("/api/papers/").removesuffix("/context").strip("/"))
                try:
                    paper_context = build_paper_context(
                        config.site_dir,
                        paper_key,
                        allowed_roots=config.allowed_context_roots,
                    )
                except KeyError as exc:
                    self._send_json({"error": "paper_not_found", "message": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"paper": paper_context.paper, "context": paper_context.text, "sources": paper_context.sources})
                return
            if path == "/api/related":
                from urllib.parse import parse_qs
                from paper_search.reader_context import related_papers

                params = parse_qs(parsed.query)
                query = str(params.get("q", [""])[0])
                try:
                    top_k = int(params.get("top_k", ["5"])[0])
                except ValueError:
                    top_k = 5
                self._send_json({"query": query, "papers": related_papers(config.site_dir, query, top_k=max(1, min(top_k, 20)))})
                return
            if path.startswith("/paper-assets/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) == 3:
                    _, kind, paper_key = parts
                    asset = _paper_asset_path(config.site_dir, unquote(paper_key), kind, config.allowed_context_roots)
                    if asset is not None:
                        content_type = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
                        self._send_bytes(asset.read_bytes(), content_type=content_type)
                        return
                self._send_bytes(b"Asset not found", status=HTTPStatus.NOT_FOUND, content_type="text/plain; charset=utf-8")
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

        def _dispatch_post(self, request_path: str, raw_body: bytes) -> None:
            parsed = urlparse(request_path)
            path = parsed.path
            try:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(payload, dict):
                self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
                return

            if path == "/api/chat":
                from paper_search.reader_chat import generate_chat_response
                from paper_search.reader_models import ReaderModelRegistry

                try:
                    result = generate_chat_response(
                        registry=ReaderModelRegistry(config.state_dir),
                        site_dir=config.site_dir,
                        payload=payload,
                        allowed_roots=config.allowed_context_roots,
                    )
                except (KeyError, ValueError, RuntimeError) as exc:
                    self._send_json({"error": "chat_failed", "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(result)
                return

            if path == "/api/models":
                from paper_search.reader_models import ModelProvider, ReaderModelRegistry

                registry = ReaderModelRegistry(config.state_dir)
                try:
                    registry.upsert_provider(ModelProvider.from_dict(payload))
                except ValueError as exc:
                    self._send_json({"error": "invalid_provider", "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(registry.public_config())
                return

            if path.startswith("/api/models/") and path.endswith("/key"):
                from paper_search.reader_models import ReaderModelRegistry

                provider_id = path.removeprefix("/api/models/").removesuffix("/key").strip("/")
                api_key = str(payload.get("key") or "")
                registry = ReaderModelRegistry(config.state_dir)
                try:
                    registry.set_provider_key(provider_id, api_key)
                except (KeyError, ValueError) as exc:
                    self._send_json({"error": "invalid_key", "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True, "provider_id": provider_id, "has_key": True})
                return

            if path.startswith("/api/"):
                self._send_json({"error": "not_found", "path": path}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"error": "method_not_allowed"}, status=HTTPStatus.METHOD_NOT_ALLOWED)

        def _send_json(self, payload: dict[str, Any] | list[Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(_json_bytes(payload), status=status, content_type="application/json; charset=utf-8")

        def _send_bytes(self, body: bytes, status: HTTPStatus = HTTPStatus.OK, content_type: str = "application/octet-stream") -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        @classmethod
        def handle_test_request(cls, path: str, method: str = "GET", json_body: dict[str, Any] | None = None) -> TestResponse:
            """Exercise the handler without opening a network socket."""

            instance = cls.__new__(cls)
            instance.path = path
            instance.wfile = io.BytesIO()
            instance.rfile = io.BytesIO(_json_bytes(json_body or {}))
            instance.headers = {"Content-Length": str(len(instance.rfile.getvalue()))}
            header_buffer = _HeaderBuffer()
            instance.send_response = header_buffer.send_response  # type: ignore[method-assign]
            instance.send_header = header_buffer.send_header  # type: ignore[method-assign]
            instance.end_headers = header_buffer.end_headers  # type: ignore[method-assign]
            if method.upper() == "POST":
                instance._dispatch_post(path, instance.rfile.getvalue())
            else:
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
    parser.add_argument("--state-dir", default=".reader")
    parser.add_argument(
        "--context-root",
        action="append",
        default=[],
        help="Allowed root for local fulltext context reads; repeatable",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve(
        ReaderServerConfig(
            site_dir=Path(args.site_dir),
            profile=args.profile,
            site_title=args.site_title,
            state_dir=Path(args.state_dir),
            allowed_context_roots=[Path(root) for root in args.context_root],
        ),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
