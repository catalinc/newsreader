FROM python:3.14-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies (cached layer separate from app code)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY *.py ./

# Persist the SQLite database outside the container
VOLUME ["/data"]
ENV DB_PATH=/data/newsreader.db

EXPOSE 8080

CMD ["uv", "run", "main.py"]
