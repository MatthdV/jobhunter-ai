FROM python:3.11-slim-bookworm

# WeasyPrint dependencies (source: kozea/weasyprint official docs)
# Playwright deps are handled by `playwright install --with-deps` below
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libharfbuzz-subset0 \
    libffi-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (all-llm + api group for auth deps: jose, passlib, cryptography)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[all-llm,api]"

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy source
COPY src/ src/
COPY static/ static/
COPY templates/ templates/
COPY alembic/ alembic/
COPY alembic.ini .

# Create volume mount points
RUN mkdir -p /data/db /data/output

# Default env
ENV DATABASE_URL=sqlite:////data/db/jobhunter.db
ENV DRY_RUN=true

VOLUME ["/data/db", "/data/output"]

EXPOSE 8000

CMD ["python", "-m", "src.main", "--help"]
