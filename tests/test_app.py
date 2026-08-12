from canopy.app import app


def test_healthz():
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_spa_returns_503_when_frontend_not_built(monkeypatch, tmp_path):
    monkeypatch.setattr("canopy.app.FRONTEND_DIST", tmp_path / "nonexistent")
    client = app.test_client()

    resp = client.get("/")

    assert resp.status_code == 503


def test_spa_serves_index_html_when_built(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<html><body>Canopy</body></html>")
    monkeypatch.setattr("canopy.app.FRONTEND_DIST", tmp_path)
    client = app.test_client()

    resp = client.get("/")

    assert resp.status_code == 200
    assert b"Canopy" in resp.data


def test_spa_catch_all_serves_index_for_client_side_routes(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<html><body>Canopy</body></html>")
    monkeypatch.setattr("canopy.app.FRONTEND_DIST", tmp_path)
    client = app.test_client()

    resp = client.get("/consider")

    assert resp.status_code == 200
    assert b"Canopy" in resp.data


def test_api_routes_are_not_shadowed_by_the_spa_catch_all(monkeypatch, session):
    """Regression test for the routing decision in canopy/app.py: the
    blueprint is registered before the SPA catch-all specifically so
    /api/* never falls through to it."""
    monkeypatch.setattr("canopy.api.SessionLocal", lambda: session)
    client = app.test_client()

    resp = client.get("/api/tags")

    assert resp.status_code == 200
    assert resp.get_json() == {"tags": []}
