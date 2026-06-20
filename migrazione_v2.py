#!/usr/bin/env python3
"""
migrazione_v2.py — Script di migrazione one-shot da v1 a v2

Eseguire UNA SOLA VOLTA prima di avviare il nuovo server.
Crea backup di tutti i file originali in backup/pre-migrazione/.

Operazioni:
  1. Backup dei file originali
  2. Aggiunge negozio_id + versione a ogni consegna, giornata, squadra in dati.json
  3. Crea negozi.json con un negozio "Negozio principale"
  4. Aggiorna utenti.json: rimuove 'ruolo', aggiunge tipo_account_id e negozio_id
  5. Crea tipi_account.json vuoto
"""

import json
import os
import sys
import shutil
import secrets
from datetime import datetime

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
DATI_FILE        = os.path.join(BASE_DIR, "dati.json")
UTENTI_FILE      = os.path.join(BASE_DIR, "utenti.json")
NEGOZI_FILE      = os.path.join(BASE_DIR, "negozi.json")
TIPI_FILE        = os.path.join(BASE_DIR, "tipi_account.json")
BACKUP_DIR       = os.path.join(BASE_DIR, "backup", "pre-migrazione")
MIGRAZIONE_FLAG  = os.path.join(BASE_DIR, "migrazione_v2.done")

def abort(msg):
    print(f"\n❌ ERRORE: {msg}")
    print("Nessun file è stato modificato.")
    sys.exit(1)

def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def backup_file(path):
    if os.path.exists(path):
        name = os.path.basename(path)
        dst  = os.path.join(BACKUP_DIR, name)
        shutil.copy2(path, dst)
        print(f"  📦 Backup: {name}")

# ── Guardie ──────────────────────────────────────────────────────────────────

if os.path.exists(MIGRAZIONE_FLAG):
    abort("La migrazione è già stata eseguita (migrazione_v2.done esiste).\n"
          "   Per rieseguirla, elimina manualmente il file migrazione_v2.done\n"
          "   e ripristina i file originali da backup/pre-migrazione/.")

if not os.path.exists(DATI_FILE):
    abort(f"dati.json non trovato in {BASE_DIR}")

if not os.path.exists(UTENTI_FILE):
    abort(f"utenti.json non trovato in {BASE_DIR}")

# ── Lettura file originali ────────────────────────────────────────────────────

print("\n🔄 Lettura file originali...")

try:
    with open(DATI_FILE, "r", encoding="utf-8") as f:
        dati = json.load(f)
except Exception as e:
    abort(f"Impossibile leggere dati.json: {e}")

try:
    with open(UTENTI_FILE, "r", encoding="utf-8") as f:
        utenti_data = json.load(f)
except Exception as e:
    abort(f"Impossibile leggere utenti.json: {e}")

consegne = dati.get("consegne", [])
giornate = dati.get("giornate", [])
squadre  = dati.get("squadre",  [])
utenti   = utenti_data.get("utenti", [])

print(f"  ✅ dati.json: {len(consegne)} consegne, {len(giornate)} giornate, {len(squadre)} squadre")
print(f"  ✅ utenti.json: {len(utenti)} utenti")

# ── Backup ────────────────────────────────────────────────────────────────────

print("\n📦 Creazione backup...")
os.makedirs(BACKUP_DIR, exist_ok=True)
backup_file(DATI_FILE)
backup_file(UTENTI_FILE)
if os.path.exists(NEGOZI_FILE):
    backup_file(NEGOZI_FILE)
if os.path.exists(TIPI_FILE):
    backup_file(TIPI_FILE)

# ── Crea negozio di default ───────────────────────────────────────────────────

print("\n🏪 Creazione negozio di default...")
negozio_id = "n_" + secrets.token_hex(8)
negozi_data = {
    "negozi": [{
        "id":        negozio_id,
        "nome":      "Negozio principale",
        "creato_il": datetime.now().isoformat(),
    }]
}
write_json(NEGOZI_FILE, negozi_data)
print(f"  ✅ negozi.json creato (id: {negozio_id})")

# ── Migra dati.json ───────────────────────────────────────────────────────────

print("\n📋 Migrazione dati.json...")

c_migrated = g_migrated = s_migrated = 0

for c in consegne:
    if "negozio_id" not in c:
        c["negozio_id"] = negozio_id
    if "versione" not in c:
        c["versione"] = 1
    c_migrated += 1

for g in giornate:
    if "negozio_id" not in g:
        g["negozio_id"] = negozio_id
    if "versione" not in g:
        g["versione"] = 1
    g_migrated += 1

for s in squadre:
    if "negozio_id" not in s:
        s["negozio_id"] = negozio_id
    if "versione" not in s:
        s["versione"] = 1
    s_migrated += 1

write_json(DATI_FILE, dati)
print(f"  ✅ {c_migrated} consegne, {g_migrated} giornate, {s_migrated} squadre migrate")

# ── Migra utenti.json ─────────────────────────────────────────────────────────

print("\n👥 Migrazione utenti.json...")

u_migrated   = 0
u_superadmin = 0

for u in utenti:
    ruolo = u.pop("ruolo", None)

    if u.get("id") == "u_superadmin" or ruolo == "superadmin":
        # Superadmin: tipo_account_id e negozio_id sempre null
        u["tipo_account_id"] = None
        u["negozio_id"]      = None
        u_superadmin += 1
    else:
        # Utenti operativi: tipo_account_id null finché superadmin non assegna
        u["tipo_account_id"] = None
        u["negozio_id"]      = None
        u_migrated += 1

write_json(UTENTI_FILE, utenti_data)
print(f"  ✅ {u_superadmin} superadmin, {u_migrated} utenti operativi migrati")
if u_migrated > 0:
    print(f"  ⚠️  Gli utenti operativi hanno tipo_account_id=null.")
    print(f"     Devono ricevere un tipo account dal superadmin prima di poter accedere.")

# ── Crea tipi_account.json vuoto ─────────────────────────────────────────────

print("\n🗂️  Creazione tipi_account.json...")
write_json(TIPI_FILE, {"tipi_account": []})
print("  ✅ tipi_account.json creato (vuoto)")

# ── Flag migrazione completata ────────────────────────────────────────────────

with open(MIGRAZIONE_FLAG, "w", encoding="utf-8") as f:
    f.write(f"Migrazione v2 completata il {datetime.now().isoformat()}\n")
    f.write(f"Negozio di default: {negozio_id}\n")

# ── Riepilogo ─────────────────────────────────────────────────────────────────

print("\n" + "="*50)
print("✅ MIGRAZIONE COMPLETATA")
print("="*50)
print(f"  Negozio creato:    Negozio principale ({negozio_id})")
print(f"  Consegne migrate:  {c_migrated}")
print(f"  Giornate migrate:  {g_migrated}")
print(f"  Squadre migrate:   {s_migrated}")
print(f"  Utenti migrati:    {u_migrated + u_superadmin}")
print(f"  Backup in:         backup/pre-migrazione/")
print()
print("  ⚠️  PROSSIMI PASSI:")
print("  1. Avvia il nuovo server.py")
print("  2. Accedi come superadmin")
print("  3. Crea i tipi di account necessari")
print("  4. Assegna un tipo account a ogni utente operativo")
print()
