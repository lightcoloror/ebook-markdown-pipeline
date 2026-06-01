FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV EBOOK_CONVERTER_API_TOKEN=change-me

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        pandoc \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/ebook_markdown_pipeline
WORKDIR /app

EXPOSE 8765

CMD ["python", "-m", "ebook_markdown_pipeline.ebook_converter_http", "--host", "0.0.0.0", "--port", "8765"]
