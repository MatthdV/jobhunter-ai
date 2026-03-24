FROM python:3.11-slim

# WeasyPrint native dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    # Playwright Chromium dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    # cron
    cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[all-llm]"

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy source
COPY src/ src/
COPY .env.example .env.example

# Create volume mount points
RUN mkdir -p /data/db /data/output

# Default env
ENV DATABASE_URL=sqlite:////data/db/jobhunter.db
ENV DRY_RUN=true

VOLUME ["/data/db", "/data/output"]

CMD ["python", "-m", "src.main", "--help"]
