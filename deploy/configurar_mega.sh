#!/usr/bin/env bash
# Grava no .env do servidor os dados de conexão com o Mega e testa a conexão.
# A senha é digitada aqui, não aparece na tela e não passa por conversa, e-mail ou repositório.
#
# Uso (no servidor):  ~/apps/acokey/deploy/configurar_mega.sh            # pede só a senha
#                     ~/apps/acokey/deploy/configurar_mega.sh --alterar  # pede também DSN e usuário
# Antes: o DBA cria o usuário com scripts/mega/01_criar_usuario_leitura.sql (blocos A e B).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Não achei o .env nesta pasta ($(pwd))."; exit 1; }

atual() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
DSN=$(atual MEGA_DSN)
USUARIO=$(atual MEGA_USUARIO)

echo "Conexão com o Mega (somente leitura)"
if [ -z "$DSN" ] || [ -z "$USUARIO" ] || [ "${1:-}" = "--alterar" ]; then
  read -rp "  DSN, no formato host:porta/servico${DSN:+ [Enter mantém $DSN]}: " RESPOSTA
  DSN=${RESPOSTA:-$DSN}
  DSN=${DSN#MEGA_DSN=}   # aceita o valor colado junto com o nome da variável
  read -rp "  Usuário [Enter mantém ${USUARIO:-acokey_ro}]: " RESPOSTA
  USUARIO=${RESPOSTA:-${USUARIO:-acokey_ro}}
else
  echo "  DSN:     $DSN"
  echo "  Usuário: $USUARIO"
  echo "  (para trocar esses dois, rode de novo com --alterar)"
fi
# Formato conferido antes de gravar: evita salvar por engano outra coisa (a senha, por exemplo) como DSN.
if ! [[ "$DSN" =~ ^[A-Za-z0-9._-]+:[0-9]+/[A-Za-z0-9._-]+$ ]]; then
  echo "O DSN precisa ter o formato host:porta/servico. Nada foi alterado."; exit 1
fi
if ! [[ "$USUARIO" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "Nome de usuário inválido. Nada foi alterado."; exit 1
fi

echo
echo "  Digite agora a SENHA desse usuário no banco e tecle Enter."
echo "  Nada aparece na tela enquanto você digita: é assim mesmo."
read -rsp "  Senha: " SENHA
echo
# A senha é gravada entre aspas simples, que o Docker Compose lê ao pé da letra (#, $ e ! passam);
# só não pode ter a própria aspa simples nem espaço.
if [ "${#SENHA}" -lt 12 ] || [[ "$SENHA" == *"'"* ]] || [[ "$SENHA" =~ [[:space:]] ]]; then
  echo "A senha precisa ter 12 ou mais caracteres, sem espaço e sem aspas simples."
  echo "Nada foi alterado. Troque a senha do usuário no banco e rode de novo."
  exit 1
fi

# Reescreve só as três linhas. A senha não passa pelo sed nem pela linha de comando.
umask 077
TMP=$(mktemp .env.XXXXXX)
trap 'rm -f "$TMP"' EXIT
grep -vE '^MEGA_(DSN|USUARIO|SENHA)=' .env > "$TMP"
printf "MEGA_DSN=%s\nMEGA_USUARIO=%s\nMEGA_SENHA='%s'\n" "$DSN" "$USUARIO" "$SENHA" >> "$TMP"
mv "$TMP" .env
chmod 600 .env
unset SENHA
echo "Gravado no .env. A leitura do Mega continua desligada (MEGA_HABILITADO) até as consultas ficarem prontas."

echo "Reiniciando a API e testando a conexão..."
docker compose up -d api >/dev/null 2>&1
for _ in $(seq 1 30); do
  docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/saude')" >/dev/null 2>&1 </dev/null && break
  sleep 2
done
docker compose exec -T api python -m app.mega testar </dev/null
