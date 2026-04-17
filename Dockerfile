FROM python:3.11-slim

WORKDIR /app

# requirements.txt do seu projeto está em UTF-16LE (com BOM).
# Convertemos para UTF-8 antes de instalar.
COPY requirements.txt /app/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends locales && rm -rf /var/lib/apt/lists/* \
 && python -c "import codecs; \
    data=codecs.open('requirements.txt','r','utf-16').read(); \
    codecs.open('requirements-utf8.txt','w','utf-8').write(data)" \
 && pip install --no-cache-dir -r requirements-utf8.txt \
 && pip install --no-cache-dir "celery[redis]==5.5.3" \
 && python -m playwright install --with-deps chromium

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
