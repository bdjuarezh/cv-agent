#!/usr/bin/env bash
# Sin acentos/ñ en los textos de prueba a propósito: `curl.exe` vía Git Bash en Windows
# corrompe argumentos -d con UTF-8 multibyte (confirmado: el mismo body con httpx llega bien;
# con curl.exe da 400 "There was an error parsing the body" de forma consistente). No es un bug
# del servidor — es una trampa de la herramienta en ese entorno. Ver 03_WEBDEV_CHECKLIST.md.
set -uo pipefail
URL="${1:?uso: smoke.sh https://...}"
KEY="${API_KEY:?exporta API_KEY}"
FAIL=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (esperado $3, obtuve $2)"; FAIL=1; fi; }

code=$(curl -s -o /tmp/r1 -w '%{http_code}' -X POST "$URL/v1/responses" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"cv-agent","input":"experiencia en MLOps"}')
check "no-streaming" "$code" "200"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/v1/responses" \
  -H 'Content-Type: application/json' -d '{"model":"cv-agent","input":"hola"}')
check "sin auth -> 401" "$code" "401"

curl -sN -X POST "$URL/v1/responses" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"cv-agent","input":"resume tu perfil","stream":true}' | grep -q '\[DONE\]' \
  && echo "ok   streaming [DONE]" || { echo "FAIL streaming"; FAIL=1; }

ID=$(jq -r .id /tmp/r1)
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/v1/responses" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "{\"model\":\"cv-agent\",\"input\":\"y en que empresa\",\"previous_response_id\":\"$ID\"}")
check "continuación" "$code" "200"

# La plataforma Banorte registra la ruta como {base}/responses, sin el prefijo /v1
# (01_ARQUITECTURA.md §1). El router dual (07_SCRIPTS_Y_CONFIG.md §E.1b) debe responder en ambas.
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/responses" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"cv-agent","input":"hola"}')
check "ruta sin prefijo /v1" "$code" "200"

exit $FAIL
