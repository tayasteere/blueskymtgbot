FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

RUN useradd --no-create-home --shell /bin/false bot

USER bot

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "bot.main"]
