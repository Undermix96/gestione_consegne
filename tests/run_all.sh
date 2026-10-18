#!/bin/sh
# Esegue la suite di contratto di storage.py su ogni backend elencato in TEST_BACKENDS
# (default: solo json). I backend vengono provati in sequenza: se uno fallisce si prosegue
# con gli altri e l'esito finale è comunque negativo.
#
# Host/porta dei database (opzionali, utili fuori da Docker):
#   TEST_PG_HOST (default: postgres)  TEST_PG_PORT
#   TEST_MYSQL_HOST (default: mysql)  TEST_MYSQL_PORT
# Utente, password e nome database arrivano da DB_USER / DB_PASSWORD / DB_NAME.
rc=0
for b in ${TEST_BACKENDS:-json}; do
  echo ""
  echo "================ backend: $b ================"
  case "$b" in
    postgres) host="${TEST_PG_HOST:-postgres}";  port="${TEST_PG_PORT:-}" ;;
    mysql)    host="${TEST_MYSQL_HOST:-mysql}";  port="${TEST_MYSQL_PORT:-}" ;;
    *)        host="";                           port="" ;;
  esac
  if [ "${TEST_VERBOSE:-0}" = "1" ]; then v="-v"; else v=""; fi
  env DB_BACKEND="$b" ${host:+DB_HOST="$host"} ${port:+DB_PORT="$port"} \
    python -B -m unittest discover -s tests $v || rc=1
done
echo ""
if [ $rc -eq 0 ]; then echo "================ ESITO FINALE: OK ================"
else echo "================ ESITO FINALE: FALLITO ================"; fi
exit $rc
