# ---------- builder ----------
FROM python:3.12-slim AS builder

# Toolchain solo para compilar wheels en build (no va a la imagen final).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
# Torch CPU-only ANTES de requirements → sentence-transformers NO descarga las wheels
# NVIDIA CUDA (~5-6GB de peso muerto; la inferencia de embeddings es solo CPU).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

# Solo libs de RUNTIME (sin build-essential):
# WeasyPrint (PDF legado), parsers, matplotlib, antiword (extrae texto de .doc binario,
# RF-001) y LibreOffice headless (convierte la plantilla .pptx institucional a PDF, RF-008).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
        libcairo2 libpangoft2-1.0-0 libffi8 \
        libjpeg62-turbo zlib1g \
        fonts-dejavu-core \
        antiword \
        libreoffice-impress \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Fuentes de la plantilla institucional (Franklin Gothic Medium, Trebuchet MS, Calibri,
# Times New Roman). Sin ellas LibreOffice sustituye por DejaVu al convertir el PPTX a PDF
# y cambia la métrica del texto (palabras cortadas / superposiciones en el reporte RF-008).
COPY app/templates/fonts/ /usr/local/share/fonts/briefing/
RUN fc-cache -f

WORKDIR /app
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
