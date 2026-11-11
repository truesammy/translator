FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home bot && mkdir /data && chown bot /data
USER bot
VOLUME /data
ENV DATABASE_PATH=/data/bot.db

CMD ["python", "-m", "translator_bot"]
