from __future__ import annotations

import json
from pathlib import Path

from paper_search.reader_server import ReaderServerConfig, create_reader_handler


def _make_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True, exist_ok=True)
    (site / "data").mkdir(exist_ok=True)
    (site / "papers").mkdir(exist_ok=True)
    (site / "index.html").write_text("<html><title>Reader</title><body>INDEX</body></html>", encoding="utf-8")
    (site / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (site / "data" / "papers.json").write_text(
        json.dumps([
            {"paper_id": "p1", "title": "Paper One", "topic_slug": "bias-fairness", "source_label": "ACL"},
            {"paper_id": "p2", "title": "Paper Two", "topic_slug": "sycophancy", "source_label": "arxiv"},
        ]),
        encoding="utf-8",
    )
    (site / "papers" / "p1.html").write_text("<html>PAPER ONE</html>", encoding="utf-8")
    return site


def _request(tmp_path: Path, path: str):
    site = _make_site(tmp_path)
    config = ReaderServerConfig(site_dir=site, profile="private", site_title="Test Reader")
    handler_cls = create_reader_handler(config)
    return handler_cls.handle_test_request(path)


def test_health_endpoint_returns_safe_json(tmp_path: Path):
    response = _request(tmp_path, "/health")

    assert response.status == 200
    assert response.headers["Content-Type"].startswith("application/json")
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["status"] == "ok"
    assert payload["profile"] == "private"
    assert payload["site_title"] == "Test Reader"
    assert "api_key" not in response.body.decode("utf-8").lower()
    assert "token" not in response.body.decode("utf-8").lower()


def test_static_index_and_asset_are_served(tmp_path: Path):
    index = _request(tmp_path, "/")
    asset = _request(tmp_path, "/assets/app.js")

    assert index.status == 200
    assert b"INDEX" in index.body
    assert index.headers["Content-Type"].startswith("text/html")
    assert asset.status == 200
    assert b"console.log" in asset.body
    assert "javascript" in asset.headers["Content-Type"]


def test_papers_api_loads_generated_metadata(tmp_path: Path):
    response = _request(tmp_path, "/api/papers")

    assert response.status == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["count"] == 2
    assert payload["papers"][0]["title"] == "Paper One"
    assert payload["topics"] == ["bias-fairness", "sycophancy"]
    assert payload["sources"] == ["ACL", "arxiv"]


def test_public_config_redacts_runtime_paths_and_secrets(tmp_path: Path):
    response = _request(tmp_path, "/api/config/public")

    assert response.status == 200
    text = response.body.decode("utf-8")
    payload = json.loads(text)
    assert payload == {
        "profile": "private",
        "site_title": "Test Reader",
        "features": {
            "chat": False,
            "models": False,
            "jobs": False,
            "figures": False,
        },
    }
    assert str(tmp_path) not in text
    assert "api_key" not in text.lower()
    assert "secret" not in text.lower()


def test_unknown_api_returns_json_404(tmp_path: Path):
    response = _request(tmp_path, "/api/missing")

    assert response.status == 404
    assert response.headers["Content-Type"].startswith("application/json")
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["error"] == "not_found"
