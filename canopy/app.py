import os

from flask import Flask, jsonify, render_template

from canopy.db.models import Listing, Parcel, Score
from canopy.db.session import SessionLocal

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.get("/")
def listings():
    session = SessionLocal()
    try:
        passed = (
            session.query(Listing, Score, Parcel)
            .join(Score, Score.listing_id == Listing.id)
            .outerjoin(Parcel, Parcel.listing_id == Listing.id)
            .filter(Score.passed_filter.is_(True))
            .order_by(Score.scored_at.desc())
            .all()
        )
        total_scored = session.query(Score).count()
        candidates = [
            {"listing": listing, "score": score, "parcel": parcel}
            for listing, score, parcel in passed
        ]
        return render_template("listings.html", candidates=candidates, total_scored=total_scored)
    finally:
        session.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
