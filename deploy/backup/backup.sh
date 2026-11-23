#!/usr/bin/env bash
# Backup diário do AçoKey Q: banco (pg_dump) e arquivos (anexos, certificados, fotos, assinaturas, databooks),
# cada um em gzip + GPG (AES256).
# Agendado no cron do usuário ubuntu (system-lab):
#   50 2 * * *  $HOME/apps/acokeyq/deploy/backup/backup.sh >> $HOME/.local/state/acokeyq-backup.log 2>&1
# Configuração (fora do repositório, permissão 600): ~/.config/acokeyq/backup.env
#   BACKUP_GPG_SENHA=...                (OBRIGATÓRIA; guarde uma cópia no cofre de senhas — sem ela o backup não abre)
#   BACKUP_DIR=/var/backups/acokeyq
#   BACKUP_RETENCAO_DIAS=30             (banco)
#   BACKUP_ARQUIVOS_RETENCAO_DIAS=7     (arquivos: são bem maiores que o banco)
set -euo pipefail
umask 077   # os arquivos de backup já nascem legíveis só pelo dono
cd "$(dirname "$0")/../.."
# Lê só as variáveis necessárias do .env (o arquivo segue o formato do Docker, não é script bash)
ler_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
POSTGRES_USER=$(ler_env POSTGRES_USER); POSTGRES_DB=$(ler_env POSTGRES_DB)
CONF=${ACOKEYQ_BACKUP_CONF:-$HOME/.config/acokeyq/backup.env}
# shellcheck disable=SC1090
[ -f "$CONF" ] && source "$CONF"
: "${BACKUP_GPG_SENHA:?defina BACKUP_GPG_SENHA em $CONF}"

DESTINO=${BACKUP_DIR:-$HOME/backups/acokeyq}
RETENCAO_DIAS=${BACKUP_RETENCAO_DIAS:-30}
RETENCAO_ARQUIVOS=${BACKUP_ARQUIVOS_RETENCAO_DIAS:-7}
mkdir -p "$DESTINO"
CARIMBO=$(date +%Y%m%d_%H%M%S)
BANCO="$DESTINO/acokeyq_banco_$CARIMBO.sql.gz.gpg"
ARQUIVOS="$DESTINO/acokeyq_arquivos_$CARIMBO.tar.gz.gpg"
trap 'rm -f "$BANCO.parcial" "$ARQUIVOS.parcial"' EXIT

cifrar() { gpg --batch --yes --quiet --symmetric --cipher-algo AES256 --passphrase-fd 3 -o "$1" 3<<<"$BACKUP_GPG_SENHA"; }

docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=plain --no-owner --no-privileges \
  | gzip -9 | cifrar "$BANCO.parcial"
mv "$BANCO.parcial" "$BANCO"
docker compose exec -T api tar -C /dados -cf - arquivos | gzip -6 | cifrar "$ARQUIVOS.parcial"
mv "$ARQUIVOS.parcial" "$ARQUIVOS"
chmod 600 "$BANCO" "$ARQUIVOS"
echo "$(date -Is) backup gerado: $BANCO ($(du -h "$BANCO" | cut -f1)) e $ARQUIVOS ($(du -h "$ARQUIVOS" | cut -f1))"

# Retenção. No dia 1º, uma cópia de cada vai para mensal/ (guardada 12 meses)
if [ "$(date +%d)" = "01" ]; then
  mkdir -p "$DESTINO/mensal" && cp -p "$BANCO" "$ARQUIVOS" "$DESTINO/mensal/"
fi
find "$DESTINO" -maxdepth 1 -name 'acokeyq_banco_*.sql.gz.gpg' -mtime +"$RETENCAO_DIAS" -delete
find "$DESTINO" -maxdepth 1 -name 'acokeyq_arquivos_*.tar.gz.gpg' -mtime +"$RETENCAO_ARQUIVOS" -delete
find "$DESTINO/mensal" -name 'acokeyq_*.gpg' -mtime +366 -delete 2>/dev/null || true
