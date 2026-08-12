FROM node:20-slim AS frontend
WORKDIR /app
COPY frontend/ frontend/
WORKDIR /app/frontend
RUN npm ci
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

# rasterio/GDAL dlopen libexpat at runtime for XML-based formats; not
# preinstalled on python:3.12-slim.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/canopy/static/dist ./canopy/static/dist

EXPOSE 8080
CMD exec gunicorn canopy.app:app --bind 0.0.0.0:${PORT:-8080} --timeout 60
