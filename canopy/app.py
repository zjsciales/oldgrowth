import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from canopy.api import api_bp

# Vite builds here (frontend/vite.config.js: outDir "../canopy/static/dist")
FRONTEND_DIST = Path(__file__).parent / "static" / "dist"

app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="/static/dist")
app.register_blueprint(api_bp)  # /api/* -- Werkzeug matches this exact prefix before the SPA catch-all below


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa(path):
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        return jsonify(error="frontend not built -- run `npm run build` in frontend/"), 503
    return send_from_directory(FRONTEND_DIST, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
