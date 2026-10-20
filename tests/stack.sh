#!/bin/bash
# stack.sh — prova dello stack con le IMMAGINI VERE, come in produzione.
#
# Compila l'immagine, poi per ognuno dei tre backend: compose.yaml con il profilo del database, migrazione
# con il servizio `migrate` (prima il rapporto, poi l'esecuzione, poi una seconda esecuzione che dev'essere
# rifiutata), avvio dell'app, controllo di salute (healthcheck dell'immagine) e giro via HTTP nel container.
# Poi la migrazione "alla maniera della GUI di Docker" (docker run, senza read_only né tmpfs), con
# compose.migrate.yaml e con un database in una rete Docker a parte (creazione del database inclusa).
#
# Si esegue SULL'HOST con Docker (non nel container dei test):   bash tests/stack.sh
# Richiede che Docker possa montare la cartella del progetto e le cartelle temporanee (non una condivisione
# di rete non esportata a Docker). Non tocca le immagini né i volumi dell'installazione: usa il progetto
# `gc-stack-test`, l'immagine `gc-stack-test:local` e porte e cartelle proprie.
#
# Opzioni: STACK_BACKENDS="json postgres mysql" (default tutti) · STACK_KEEP=1 per non ripulire.

cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1   # Git Bash su Windows: niente conversione automatica dei percorsi

IMG=gc-stack-test:local
PROJECT=gc-stack-test
APP_PORT=${STACK_PORT:-18091}
BACKENDS=${STACK_BACKENDS:-json postgres mysql}
TMP=$(mktemp -d "${TMPDIR:-/tmp}/gc_stack_XXXXXX")
PASS=0; FAIL=0

hostpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }
has() { grep -q -- "$1" "$TMP/last.out"; }
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
ko()   { echo "  ✗ $1"; FAIL=$((FAIL+1)); }
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else ko "$1"; fi; }
cleanup() {
  [ "${STACK_KEEP:-0}" = "1" ] && { echo "(STACK_KEEP=1: lascio $TMP)"; return; }
  for b in json postgres mysql; do compose_for "$b" down -v >/dev/null 2>&1; done
  docker rm -f gc-stack-pg >/dev/null 2>&1; docker network rm gc-stack-net >/dev/null 2>&1
  rm -rf "$TMP" 2>/dev/null
}
trap cleanup EXIT

# ── dati V1 di prova: una giornata con squadra, una senza, una con un nome che non esiste ──
SRC="$TMP/src"; mkdir -p "$SRC" "$TMP/migration"
cat > "$SRC/squadre.json" <<'EOF'
[{"id":"sq1","nome":"Squadra A","colorIdx":0}]
EOF
cat > "$SRC/consegne.json" <<'EOF'
[{"id":"c1","nome":"Mario","cognome":"Rossi","stato":"programmata","citta":"Vicenza","articoli":[]},
 {"id":"c2","nome":"Anna","cognome":"Verdi","stato":"in_attesa","citta":"Padova","articoli":[]},
 {"id":"c3","nome":"Luca","cognome":"Bianchi","stato":"in_attesa","citta":"Verona","articoli":[]}]
EOF
cat > "$SRC/giornate.json" <<'EOF'
[{"id":"g1","data":"2026-05-01","squadra":"Squadra A","consegneIds":["c1"]},
 {"id":"g2","data":"2026-05-02","squadra":"","consegneIds":[]},
 {"id":"g3","data":"2026-05-03","squadra":"Ghost","consegneIds":[]}]
EOF

# ── giro HTTP eseguito DENTRO il container dell'app ──
cat > "$TMP/giro.py" <<'EOF'
import hashlib, http.client, json, sys
def call(m, p, body=None, tok=None):
    c = http.client.HTTPConnection("localhost", 8080, timeout=30)
    h = {"Content-Type": "application/json"}
    if tok: h["X-Session-Token"] = tok
    c.request(m, p, json.dumps(body) if body is not None else None, h)
    r = c.getresponse(); raw = r.read()
    return r.status, (json.loads(raw) if raw else None)
H = lambda s: hashlib.sha256(s.encode()).hexdigest()
def login(u, pw):
    ch = call("GET", "/api/auth/challenge")[1]["challenge"]
    return call("POST", "/api/auth/login", {"username": u, "challenge": ch, "response": H(H(pw) + ch)})
code, d = login("superadmin", "admin"); assert code == 200 and d["must_change_password"], (code, d)
tok = d["token"]
ch = call("GET", "/api/auth/challenge")[1]["challenge"]
assert call("POST", "/api/auth/change-password", {"challenge": ch, "response": H(H("admin") + ch), "nuova_hash": H("Stack#Pass2026")}, tok)[0] == 200
code, d = login("superadmin", "Stack#Pass2026"); tok = d["token"]
neg = call("GET", "/api/negozi", tok=tok)[1]["negozi"]
assert [n["nome"] for n in neg] == ["Negozio principale"], neg
tipo = call("POST", "/api/tipi-account", {"nome": "Op", "permessi": ["consegne.leggi", "giornate.leggi", "squadre.leggi"]}, tok)[1]["tipo"]["id"]
assert call("POST", "/api/utenti", {"username": "op1", "password_hash": H("Op1#Pass2026"), "tipo_account_id": tipo, "negozio_id": neg[0]["id"]}, tok)[0] == 201
code, d = login("op1", "Op1#Pass2026"); assert code == 200, (code, d)
t = d["token"]
cons = call("GET", "/api/consegne", tok=t)[1]["consegne"]
gio = call("GET", "/api/giornate", tok=t)[1]["giornate"]
sq = {s["id"]: s["nome"] for s in call("GET", "/api/squadre", tok=t)[1]["squadre"]}
nomi = {g["id"]: sq[g["squadra_id"]] for g in gio}
assert len(cons) == 3 and len(gio) == 3, (len(cons), len(gio))
assert nomi == {"g1": "Squadra A", "g2": "Non assegnata", "g3": "Ghost"}, nomi
assert sorted(sq.values()) == ["Ghost", "Non assegnata", "Squadra A"], sq
print("GIRO-OK")
EOF

echo "== Compilazione dell'immagine ($IMG)"
if docker build -q -t "$IMG" . >/dev/null; then ok "immagine compilata"; else ko "build fallita"; exit 1; fi
cat > "$TMP/override.yaml" <<EOF
services:
  app:
    image: $IMG
  migrate:
    image: $IMG
EOF

compose_for() {   # compose_for <backend> <argomenti...>
  local b="$1"; shift
  local prof=""; [ "$b" = "postgres" ] && prof="--profile postgres"; [ "$b" = "mysql" ] && prof="--profile mysql"
  docker compose -p "$PROJECT" -f compose.yaml -f "$(hostpath "$TMP/override.yaml")" $prof "$@"
}

for b in $BACKENDS; do
  echo "== Backend $b (compose.yaml)"
  export DB_BACKEND=$b DB_PASSWORD=stackpw DB_USER=gcuser DB_NAME=gc_stack APP_PORT=$APP_PORT
  export DB_PORT=$([ "$b" = "postgres" ] && echo 5432 || echo 3306)
  export SRC_HOST_DIR=$(hostpath "$SRC") MIGRATE_DIR=$(hostpath "$TMP/migration")
  compose_for "$b" down -v >/dev/null 2>&1

  out=$(compose_for "$b" --profile migrate run --rm migrate 2>&1); rc=$?
  echo "$out" > "$TMP/last.out"
  check "rapporto senza scritture (codice 0)" "[ $rc -eq 0 ] && has 'Nulla è stato scritto'"
  out=$(MIGRATE_EXECUTE=1 compose_for "$b" --profile migrate run --rm migrate 2>&1); rc=$?
  echo "$out" > "$TMP/last.out"
  check "migrazione eseguita e verificata" "[ $rc -eq 0 ] && has 'Verifica superata'"
  MIGRATE_EXECUTE=1 compose_for "$b" --profile migrate run --rm migrate >/dev/null 2>&1; rc=$?
  check "seconda migrazione rifiutata (codice 2)" "[ $rc -eq 2 ]"

  compose_for "$b" up -d app >/dev/null 2>&1
  cid=$(compose_for "$b" ps -q app)
  st=""; for i in $(seq 1 60); do st=$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null); [ "$st" = "healthy" ] && break; sleep 3; done
  check "healthcheck dell'immagine: healthy" "[ '$st' = healthy ]"
  out=$(compose_for "$b" exec -T app python - < "$TMP/giro.py" 2>&1)
  echo "$out" > "$TMP/last.out"
  check "giro HTTP: login, cambio password, utente, dati migrati e squadre" "has GIRO-OK"
  [ "$FAIL" -gt 0 ] && echo "$out" | tail -5
  check "porta pubblicata raggiungibile dall'host" "curl -fsS http://localhost:$APP_PORT/api/ping | grep -q ok"
  compose_for "$b" down -v >/dev/null 2>&1
done

echo "== Alla maniera della GUI di Docker (docker run: senza read_only né tmpfs, cartelle montate)"
D1="$TMP/gui-data"; mkdir -p "$D1"; chmod 777 "$D1" "$TMP/migration"
guirun() { docker run --rm -e SRC_BACKEND=json -v "$(hostpath "$SRC"):/source:ro" -v "$(hostpath "$D1"):/data" \
           -v "$(hostpath "$TMP/migration"):/migration" "$@" "$IMG" python migrate.py; }
out=$(guirun 2>&1); rc=$?
echo "$out" > "$TMP/last.out"
check "docker run, rapporto" "[ $rc -eq 0 ] && has 'Nulla è stato scritto' && [ -z \"\$(ls $D1)\" ]"
out=$(guirun -e MIGRATE_EXECUTE=1 2>&1); rc=$?
echo "$out" > "$TMP/last.out"
check "docker run, esecuzione" "[ $rc -eq 0 ] && has 'ESITO: OK — migrazione completata'"
out=$(docker run --rm -e SRC_BACKEND=json -e MIGRATE_EXECUTE=1 -v "$(hostpath "$SRC"):/source:ro" "$IMG" python migrate.py 2>&1); rc=$?
echo "$out" > "$TMP/last.out"
check "senza cartella di migrazione montata: avviso e prosegue" "[ $rc -eq 0 ] && has 'non è montata'"
check "file di esportazione salvato nella cartella montata" "ls $TMP/migration | grep -q '^export-'"

echo "== compose.migrate.yaml (stack Portainer) con database in una rete a parte"
docker network create gc-stack-net >/dev/null 2>&1
docker run -d --name gc-stack-pg --network gc-stack-net -e POSTGRES_USER=gcuser -e POSTGRES_PASSWORD=stackpw \
  -e POSTGRES_DB=vecchio postgres:16-alpine >/dev/null 2>&1
for i in $(seq 1 30); do docker exec gc-stack-pg pg_isready -U gcuser -d vecchio >/dev/null 2>&1 && break; sleep 1; done; sleep 2
export DB_NETWORK=gc-stack-net DB_BACKEND=postgres DB_HOST=gc-stack-pg DB_PORT=5432 DB_NAME=gc_nuovo DB_USER=gcuser DB_PASSWORD=stackpw
export SRC_HOST_DIR=$(hostpath "$SRC") DATA_HOST_DIR=$(hostpath "$D1") MIGRATE_HOST_DIR=$(hostpath "$TMP/migration")
sed "s#image: undermix/gestione-consegne:latest#image: $IMG#" compose.migrate.yaml > "$TMP/compose.migrate.test.yaml"
pm() { docker compose -p gc-stack-mig -f "$(hostpath "$TMP/compose.migrate.test.yaml")" run --rm migrate; }
out=$(pm 2>&1); rc=$?
echo "$out" > "$TMP/last.out"
check "senza MIGRATE_CREATE_DB il database mancante è segnalato (codice 3)" "[ $rc -eq 3 ] && has MIGRATE_CREATE_DB"
out=$(MIGRATE_CREATE_DB=1 MIGRATE_EXECUTE=1 pm 2>&1); rc=$?
echo "$out" > "$TMP/last.out"
check "con MIGRATE_CREATE_DB=1 crea il database e migra" "[ $rc -eq 0 ] && has 'Database .gc_nuovo. creato' && has 'Verifica superata'"
check "il database esiste e contiene le consegne" "[ \"\$(docker exec gc-stack-pg psql -U gcuser -d gc_nuovo -tAc 'select count(*) from consegne')\" = 3 ]"
docker compose -p gc-stack-mig -f "$(hostpath "$TMP/compose.migrate.test.yaml")" down >/dev/null 2>&1

echo ""
echo "================ STACK: $PASS controlli superati, $FAIL falliti ================"
[ "$FAIL" -eq 0 ]
