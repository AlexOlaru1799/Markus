FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --no-deps playwright
RUN python -m playwright install --with-deps chromium
RUN apt-get update && apt-get install -y --no-install-recommends xauth && rm -rf /var/lib/apt/lists/*

COPY src ./src
RUN pip install --no-cache-dir .

ENV DISPLAY=:99

EXPOSE 8000

CMD ["sh", "-c", "rm -f /tmp/.X99-lock /tmp/.X11-unix/X99; Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp & sleep 0.5; exec markus-mcp"]
