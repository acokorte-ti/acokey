#!/usr/bin/env bash
# Restaura um backup do BANCO em um banco de CONFERÊNCIA (não toca no banco em uso) e mostra as contagens.
# Uso:  deploy/backup/restaurar.sh /caminho/acokey_banco_AAAAMMDD_HHMMSS.sql.gz.gpg
# Para conferir um backup de ARQUIVOS sem restaurar:
#   gpg --decrypt acokey_arquivos_....tar.gz.gpg | tar -tzf - | wc -l
set -euo pipefail
ARQ=${1:?informe o arquivo de backup do banco (.sql.gz.gpg)}
cd "$(dirname "$0")/../.."
ler_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
POSTGRES_USER=$(ler_env POSTGRES_USER)
CONF=${ACOKEY_BACKUP_CONF:-$HOME/.config/acokey/backup.env}
# shellcheck disable=SC1090
[ -f "$CONF" ] && source "$CONF"
BANCO=acokey_conferencia

docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS $BANCO" -c "CREATE DATABASE $BANCO"
gpg --batch --quiet --decrypt --passphrase-fd 3 "$ARQ" 3<<<"${BACKUP_GPG_SENHA:?defina BACKUP_GPG_SENHA em $CONF}" \
  | gunzip \
  | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$BANCO" -v ON_ERROR_STOP=1 --quiet >/dev/null
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$BANCO" -At -c \
  "SELECT 'lotes=' || count(*) FROM lotes UNION ALL
   SELECT 'registros=' || count(*) FROM registros UNION ALL
   SELECT 'anexos=' || count(*) FROM anexos UNION ALL
   SELECT 'usuarios=' || count(*) FROM usuarios"
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE $BANCO" >/dev/null
echo "$(date -Is) restauração de conferência OK: $ARQ"
