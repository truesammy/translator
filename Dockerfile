FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

RUN useradd --create-home bot && mkdir /data && chown bot /data
USER bot
VOLUME /data
ENV DATABASE_PATH=/data/bot.db

# Python as process 1 ignores SIGTERM; SIGINT makes the bot close cleanly.
STOPSIGNAL SIGINT
CMD ["python", "-m", "translator_bot"]
