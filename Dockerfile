# ─── Build stage non necessario: nessuna compilazione, deps sono binary wheels
FROM python:3.13-slim-bookworm

# ── Argomenti di build (UID/GID personalizzabili al build time) ───────────────
ARG APP_UID=1001
ARG APP_GID=1001

# ── Metadati immagine ─────────────────────────────────────────────────────────
LABEL org.opencontainers.image.title="Gestione Consegne" \
      org.opencontainers.image.source="https://github.com/undermix/gestione-consegne" \
      org.opencontainers.image.base.name="python:3.13-slim-bookworm"

WORKDIR /app

# ── Dipendenze sistema ────────────────────────────────────────────────────────
# libpq5: runtime library richiesta da psycopg2-binary
# Nessun build tool necessario (usiamo wheels precompilati)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ── Dipendenze Python ─────────────────────────────────────────────────────────
# Copiamo requirements.txt prima del codice per sfruttare la cache dei layer:
# se solo il codice cambia, pip install non viene rieseguito.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Codice applicativo ────────────────────────────────────────────────────────
COPY server.py storage.py import_data.py ./
COPY index.html ./
COPY css/ css/
COPY js/  js/

# ── Utente non-root ───────────────────────────────────────────────────────────
# Creiamo un utente dedicato senza shell e senza home directory.
# /data è il volume dei dati (json) o punto di mount temporaneo (import).
RUN groupadd -g ${APP_GID} appgroup \
    && useradd -u ${APP_UID} -g appgroup -r -s /bin/false appuser \
    && mkdir -p /data /import \
    && chown -R appuser:appgroup /app /data /import

USER appuser

# ── Porta ─────────────────────────────────────────────────────────────────────
EXPOSE 8080

# ── Healthcheck ───────────────────────────────────────────────────────────────
# Verifica che il server risponda HTTP 200 su /api/ping.
# Usa solo la stdlib Python: nessuna dipendenza da curl o wget.
# --start-period=15s lascia tempo all'init_storage() di connettersi al DB.
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c \
        "import urllib.request, sys; \
         r = urllib.request.urlopen('http://localhost:8080/api/ping', timeout=4); \
         sys.exit(0 if r.status == 200 else 1)"

# ── Variabili d'ambiente di default ──────────────────────────────────────────
ENV PORT=8080 \
    DB_BACKEND=json \
    DATA_DIR=/data

CMD ["python", "server.py"]
