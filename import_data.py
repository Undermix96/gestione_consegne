#!/usr/bin/env python3
"""
import_data.py — Importazione one-shot dal dati.json originale (V1)

Legge /import/dati.json (montato dall'host) e lo scrive nel backend
configurato tramite le stesse variabili d'ambiente del server.

Utilizzo (dentro al container):
    docker exec <container> python import_data.py

Oppure con volume temporaneo:
    docker run --rm \\
      -v ./dati.json:/import/dati.json:ro \\
      --env-file .env \\
      undermix/gestione-consegne python import_data.py

Il file flag /data/import_done impedisce una seconda esecuzione accidentale.
Per forzare una reimportazione: rimuovere /data/import_done prima di rieseguire.
"""

import json
import logging
import os
import sys

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SOURCE_FILE = os.environ.get("IMPORT_SOURCE", "/import/dati.json")
FLAG_FILE   = os.path.join(os.environ.get("DATA_DIR", "/data"), "import_done")
BACKEND     = os.environ.get("DB_BACKEND", "json").lower()


def main():
    # ── Verifica file flag ───────────────────────────────────────────────────
    if os.path.exists(FLAG_FILE):
        log.error(
            f"Importazione già eseguita ({FLAG_FILE} esiste). "
            "Rimuovi il file flag se vuoi forzare una reimportazione."
        )
        sys.exit(1)

    # ── Verifica sorgente ────────────────────────────────────────────────────
    if not os.path.exists(SOURCE_FILE):
        log.error(
            f"File sorgente non trovato: {SOURCE_FILE}\n"
            "Assicurati di aver montato il dati.json originale con:\n"
            "  -v ./dati.json:/import/dati.json:ro"
        )
        sys.exit(1)

    # ── Leggi sorgente ───────────────────────────────────────────────────────
    log.info(f"Lettura {SOURCE_FILE}...")
    try:
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            source = json.load(f)
    except Exception as e:
        log.error(f"Errore lettura {SOURCE_FILE}: {e}")
        sys.exit(1)

    consegne = source.get("consegne", [])
    giornate  = source.get("giornate",  [])
    squadre   = source.get("squadre",   [])

    log.info(
        f"Dati letti: {len(consegne)} consegne, "
        f"{len(giornate)} giornate, {len(squadre)} squadre"
    )

    # ── Inizializza storage e scrivi ─────────────────────────────────────────
    log.info(f"Backend destinazione: {BACKEND}")

    # import_data gira prima del server: il logging root non è configurato
    # dallo stesso basicConfig di storage.py, ma il modulo usa logging standard
    # che viene catturato dal nostro basicConfig sopra.
    from storage import init_storage, write_data

    log.info("Inizializzazione storage...")
    try:
        init_storage()
    except Exception as e:
        log.error(f"Errore inizializzazione storage: {e}")
        sys.exit(1)

    log.info("Scrittura dati...")
    try:
        write_data({
            "consegne": consegne,
            "giornate":  giornate,
            "squadre":   squadre,
        })
    except Exception as e:
        log.error(f"Errore scrittura dati: {e}")
        sys.exit(1)

    # ── Scrivi file flag ─────────────────────────────────────────────────────
    try:
        with open(FLAG_FILE, "w", encoding="utf-8") as f:
            f.write(
                f"Importazione completata.\n"
                f"Sorgente: {SOURCE_FILE}\n"
                f"Backend:  {BACKEND}\n"
                f"Consegne: {len(consegne)}\n"
                f"Giornate: {len(giornate)}\n"
                f"Squadre:  {len(squadre)}\n"
            )
    except Exception as e:
        log.warning(f"Impossibile scrivere il file flag {FLAG_FILE}: {e}")

    log.info("Importazione completata con successo.")
    log.info(f"File flag creato: {FLAG_FILE}")


if __name__ == "__main__":
    main()
