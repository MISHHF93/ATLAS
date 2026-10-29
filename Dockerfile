FROM python:3.11-slim

RUN useradd --create-home --shell /usr/sbin/nologin bot
WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir -e ".[founder]"
USER bot
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -m atlas.ops.health || exit 1
CMD ["atlas-run"]
