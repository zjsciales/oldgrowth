import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Listing(Base):
    """One RentCast sale listing, upserted on each ingest run."""

    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # RentCast listing id
    formatted_address: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    zip_code: Mapped[str] = mapped_column(String, index=True)
    county: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    property_type: Mapped[str | None] = mapped_column(String, nullable=True)
    lot_size_sqft: Mapped[float | None] = mapped_column(Float, nullable=True)
    square_footage: Mapped[float | None] = mapped_column(Float, nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String)  # Active / Inactive
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    listed_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    removed_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    mls_name: Mapped[str | None] = mapped_column(String, nullable=True)
    mls_number: Mapped[str | None] = mapped_column(String, nullable=True)

    raw: Mapped[dict] = mapped_column(JSON)  # full RentCast payload, for reference

    first_seen: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    last_ingested: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    parcel: Mapped["Parcel | None"] = relationship(back_populates="listing", uselist=False)
    score: Mapped["Score | None"] = relationship(back_populates="listing", uselist=False)


class Parcel(Base):
    """Stage 2 GIS enrichment results for a listing's parcel."""

    __tablename__ = "parcels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), unique=True)

    parcel_id: Mapped[str | None] = mapped_column(String, nullable=True)
    geometry_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    adjacent_water: Mapped[bool] = mapped_column(default=False)
    adjacent_park_or_conservation: Mapped[bool] = mapped_column(default=False)
    adjacent_county_or_city_owned: Mapped[bool] = mapped_column(default=False)

    flood_zone: Mapped[str | None] = mapped_column(String, nullable=True)
    wetland_overlay: Mapped[bool] = mapped_column(default=False)

    raw_gis: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    enriched_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    listing: Mapped["Listing"] = relationship(back_populates="parcel")


class Score(Base):
    """Stage 3/4 canopy scoring + filter outcome for a listing."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), unique=True)

    canopy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_growth_proxy_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    passed_filter: Mapped[bool] = mapped_column(default=False)
    filter_reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    subagent_flag_ok: Mapped[bool | None] = mapped_column(nullable=True)
    subagent_rationale: Mapped[str | None] = mapped_column(String, nullable=True)

    scored_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    listing: Mapped["Listing"] = relationship(back_populates="score")


class DigestLog(Base):
    """Record of what was emailed and when, to avoid re-sending unchanged candidates."""

    __tablename__ = "digest_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
