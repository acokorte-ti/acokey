#!/usr/bin/env bash
# Liga o site do AçoKey Q no nginx do servidor (system-lab), com HTTPS. Rodar UMA vez, depois que o DNS
# acokey.acokorte.com.br apontar para este servidor. Precisa de sudo (o usuário ubuntu tem).
# Uso:  ~/apps/acokey/deploy/ativar_https.sh
set -euo pipefail
cd "$(dirname "$0")/.."
SITE=acokey.acokorte.com.br

if ! getent hosts "$SITE" >/dev/null; then
  echo "O endereço $SITE ainda não existe no DNS. Crie o registro (mesmo IP de manutencao.acokorte.com.br) e rode de novo."
  exit 1
fi
if [ ! -f "/etc/letsencrypt/live/$SITE/fullchain.pem" ]; then
  # O nginx do servidor já responde o desafio do Let's Encrypt em /var/www/certbot para qualquer nome
  sudo certbot certonly --webroot -w /var/www/certbot -d "$SITE" --non-interactive
fi
sudo cp "deploy/nginx-host/$SITE.conf" /etc/nginx/sites-available/acokey
sudo ln -sf /etc/nginx/sites-available/acokey /etc/nginx/sites-enabled/acokey
if sudo nginx -t; then
  sudo systemctl reload nginx
  echo "Site no ar: https://$SITE (só para a rede da empresa)."
else
  sudo rm -f /etc/nginx/sites-enabled/acokey
  echo "A configuração do nginx não passou no teste; o site foi desligado de novo e nada mais mudou."
  exit 1
fi
