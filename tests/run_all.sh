#!/bin/sh
# Esegue la suite di contratto di storage.py su ogni backend elencato in TEST_BACKENDS
# (default: solo json). I backend vengono provati in sequenza: se uno fallisce si prosegue
# con gli altri e l'esito finale è comunque negativo.
rc=0
for b in ${TEST_BACKENDS:-json}; do
  echo ""
  echo "================ backend: $b ================"
  if [ "${TEST_VERBOSE:-0}" = "1" ]; then v="-v"; else v=""; fi
  DB_BACKEND="$b" python -B -m unittest discover -s tests $v || rc=1
done
echo ""
if [ $rc -eq 0 ]; then echo "================ ESITO FINALE: OK ================"
else echo "================ ESITO FINALE: FALLITO ================"; fi
exit $rc
