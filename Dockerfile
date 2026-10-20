# ─── Build stage non necessario: nessuna compilazione, deps sono binary wheels
FROM python:3.13-slim-bookworm

# ── Argomenti di build (UID/GID personalizzabili al build time) ───────────────
ARG APP_UID=1001
ARG APP_GID=1001
# Versioni degli strumenti di backup: devono coincidere con i database di compose.yaml
# (postgres:16-alpine → PG_MAJOR=16, mysql:8.4 → MYSQL_COMPONENT=mysql-8.4-lts / MYSQL_SERIES=8.4).
# tests/test_backup.py verifica che compose.yaml e gli strumenti installati siano allineati.
ARG PG_MAJOR=16
ARG MYSQL_COMPONENT=mysql-8.4-lts
ARG MYSQL_SERIES=8.4

# ── Metadati immagine ─────────────────────────────────────────────────────────
LABEL org.opencontainers.image.title="Gestione Consegne" \
      org.opencontainers.image.source="https://github.com/undermix/gestione-consegne" \
      org.opencontainers.image.base.name="python:3.13-slim-bookworm"

WORKDIR /app

# ── Dipendenze sistema ────────────────────────────────────────────────────────
# libpq5: runtime library richiesta da psycopg2-binary
# pg_dump e mysqldump per backup.py, NELLA VERSIONE dei database di compose.yaml: pg_dump rifiuta di
# fare il dump di un server più nuovo di lui, e i pacchetti di Debian sono più vecchi (PostgreSQL 15,
# client MariaDB). Si usano quindi i repository dei produttori (PGDG e MySQL), con chiave GPG verificata.
# curl e gnupg servono solo a scaricare le chiavi e vengono rimossi.
# Nessun build tool necessario (usiamo wheels precompilati)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg libpq5 \
    && install -d /usr/share/keyrings \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://repo.mysql.com/RPM-GPG-KEY-mysql-2025 | gpg --dearmor -o /usr/share/keyrings/mysql.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/mysql.gpg] http://repo.mysql.com/apt/debian bookworm ${MYSQL_COMPONENT}" \
        > /etc/apt/sources.list.d/mysql.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-${PG_MAJOR} mysql-community-client \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/* \
    && pg_dump --version | grep -q " ${PG_MAJOR}\." \
    && mysqldump --version | grep -q "Ver ${MYSQL_SERIES}\."

# ── Dipendenze Python ─────────────────────────────────────────────────────────
# Copiamo requirements.txt prima del codice per sfruttare la cache dei layer:
# se solo il codice cambia, pip install non viene rieseguito.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Codice applicativo ────────────────────────────────────────────────────────
COPY server.py storage.py backup.py import_data.py migrate.py ./
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
