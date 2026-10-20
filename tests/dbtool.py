"""
dbtool.py — piccolo strumento per i test di integrazione: opera su UN backend scelto dall'ambiente
(DB_BACKEND, DATA_DIR, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD) in un processo dedicato,
perché storage.py legge l'ambiente una volta sola.

  wipe        elimina tutto (tabelle o file): SOLO per database il cui nome finisce per _test e cartelle temporanee
  v1-write    scrive nel backend (schema V1) il JSON letto da stdin: {"consegne": [], "giornate": [], "squadre": []}
  v2-dump     stampa su stdout tutte le collezioni V2 come JSON (esce con 2 se lo schema V2 non è valido)
  tables      stampa l'elenco di tabelle (SQL) o file (json) presenti
  set-flag    imposta il flag di migrazione in corso su un archivio V2

Non è parte dell'applicazione e non è nell'immagine di produzione (vive in tests/).
"""
import json
import os
import shutil
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import storage as st  # noqa: E402

COLLECTIONS = ("negozi", "tipi_account", "utenti", "squadre", "consegne", "giornate")


def _guard_sql():
    name = os.environ.get("DB_NAME", "")
    if not name.endswith("_test"):
        sys.exit(f"dbtool: rifiuto di operare su un database che non è di test ({name!r})")


def wipe():
    if st.BACKEND == "json":
        d = st.DATA_DIR
        if os.path.isdir(d):
            for name in os.listdir(d):
                p = os.path.join(d, name)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        return
    _guard_sql()
    if st.BACKEND == "postgres":
        conn = st._pg_connect()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    else:
        conn = st._mysql_connect()
        cur = conn.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute("SHOW TABLES")
        for (t,) in cur.fetchall():
            cur.execute(f"DROP TABLE `{t}`")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    cur.close()
    conn.close()


def tables():
    if st.BACKEND == "json":
        d = st.DATA_DIR
        return sorted(os.listdir(d)) if os.path.isdir(d) else []
    _guard_sql()
    conn = st._pg_connect() if st.BACKEND == "postgres" else st._mysql_connect()
    cur = conn.cursor()
    if st.BACKEND == "postgres":
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
    else:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
    out = sorted(str(r[0]).lower() for r in cur.fetchall())
    conn.close()
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "wipe":
        wipe()
    elif cmd == "v1-write":
        data = json.loads(sys.stdin.read())
        st.init_storage()
        st.write_data(data)
    elif cmd == "v2-dump":
        try:
            st.init_storage_v2()
        except st.SchemaError as e:
            print(f"SchemaError: {e}", file=sys.stderr)
            return 2
        print(json.dumps({c: st.list_records(c) for c in COLLECTIONS}, ensure_ascii=False))
    elif cmd == "tables":
        print(json.dumps(tables()))
    elif cmd == "set-flag":
        st.init_storage_v2(ignore_migration=True)
        st.set_meta("migrazione_in_corso", True)
    else:
        sys.exit(f"dbtool: comando sconosciuto {cmd!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
