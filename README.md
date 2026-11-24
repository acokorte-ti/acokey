# AçoKey Q — Controle de lotes de fabricação (Qualidade, AçoKorte)

Sistema da Qualidade para acompanhar os lotes de chavetas PIN, BOX e ARK pelas 11 etapas de fabricação
(recebimento de matéria-prima até embalagem), com registro de cada aprovação, anexos, não conformidades
e trilha de auditoria. Reescrita, no padrão dos sistemas internos, do sistema que o Gerente da Qualidade
montou em Flask. O sistema antigo fica em `legado/` **só na máquina de desenvolvimento**: ele não vai para o
repositório, porque tem dados reais e informações do cliente.

**Este repositório é público. Dados reais nunca entram nele** (banco, anexos, planilhas, PDFs, assinaturas,
nomes do cliente e de funcionários). Ver `.gitignore` e o aviso no topo do `CLAUDE.md`.

## Estado da reescrita

| Fase | O que entra | Situação |
|---|---|---|
| 1. Base | Login, sessões, CSRF, usuários e permissões, auditoria, modelo de dados completo, carga do sistema antigo | **pronta** |
| 2. Lote e etapas | Novo/editar/cancelar lote, formulários de cada etapa (verde/vermelho ao vivo pela especificação), aprovação por documento, anexos e fotos, avanço, importação em massa, PDF do registro, NC automática | **pronta** |
| 3. Qualidade | Não conformidades (4 disposições, correção de dureza), especificações, verificação dimensional RIP-33A | **pronta** |
| 4. Relatórios e databook | Dureza RIP-35, Tratamento Térmico (por carga), Visual, databook (capa, índice, anexos), conferência, controle "Enviado-DB" | **pronta** |
| 5. Demais módulos | Matéria-prima (carimbo e propagação), cadastros, ordens de produção (importação da planilha), parâmetros, assinaturas, cargas de TT, envios a prestador (PDF e modelo do laboratório), ordem de faturamento, início, painel com alertas, dashboard, Gantt, KPIs, indicadores, busca (Ctrl+K), exportações Excel | **pronta** |
| 6. Mega | Leitura das OPs, faturamento e notas de entrada do ERP | infraestrutura pronta, desligada; falta mapear as tabelas |
| 7. Visita guiada e manual | Tutorial por tela (o antigo tinha 25) e manual do usuário | a fazer |
| 8. Virada | Homologação no system-lab, carga final dos dados reais, desligamento do notebook | a fazer |

Até a virada, o sistema antigo continua em uso no notebook da Qualidade. A carga pode ser repetida (com o banco
novo vazio) quantas vezes for preciso.

## Arquitetura

```
navegador ──HTTPS──> nginx do servidor (certificado, lista de IPs da empresa)
                        └─> 127.0.0.1:8093  contêiner web (nginx: site + /api)
                                               └─> contêiner api (FastAPI, Python 3.12)
                                                      ├─> contêiner db (PostgreSQL 16, sem porta exposta)
                                                      └─> volume "arquivos" (anexos, certificados, fotos, assinaturas)
```

| Pasta | Conteúdo |
|---|---|
| `backend/app/` | API: `api_*.py` (rotas), `models.py` (tabelas), `fluxo.py` (regras das etapas, funções puras), `estado.py` (lê o estado dos lotes), `carga.py` (importa o sistema antigo), `seguranca.py`, `admin.py` (socorro pela linha de comando) |
| `backend/alembic/` | Migrações do banco (rodam sozinhas quando a API sobe) |
| `backend/tests/` | pytest, em SQLite temporário (no CI também em PostgreSQL) |
| `frontend/` | Telas (React + TypeScript + Vite) |
| `deploy/` | Dockerfile do site, nginx, backup |
| `legado/` | Sistema antigo (Flask), com seus dados. **Só na máquina local, fora do Git** |

### O que mudou em relação ao sistema antigo

| Antes (Flask) | Agora |
|---|---|
| SQLite, colunas quase todas texto, sem chave estrangeira, `ALTER TABLE` a cada requisição | PostgreSQL, colunas tipadas, chaves estrangeiras e restrições de status, migrações Alembic |
| Usuários, OPs, equipamentos, prestadores e fornecedores em planilhas Excel lidas a cada requisição | Tabelas no banco (`usuarios`, `ordens_producao`, `equipamentos`, `prestadores`, `fornecedores_mp`) |
| Caminho absoluto do Windows gravado em cada anexo (`C:\...\data\lotes\...`) | Caminho relativo à pasta de arquivos (volume), servido só de dentro dela |
| Sem CSRF; escape de HTML dependente do nome do template | Token CSRF em toda gravação; React escapa por padrão; CSP no nginx |
| Metade das rotas só exigia estar logado (qualquer um alterava a especificação) | Toda rota declara a permissão (`exigir(...)`) e tem teste |
| Senha administrativa única compartilhada (`SENHA_EDICAO`) | Perfil de administrador por usuário; "pode aprovar" continua separado |
| Senhas pbkdf2/scrypt, algumas em texto puro, cópias da planilha com os hashes | Argon2id; ninguém traz senha do sistema antigo (todos recebem provisória) |
| Sessão sem validade; responsável digitado à mão | Sessão no banco com validade e teto; o registro guarda também o usuário logado |
| Notebook com `.bat`, tarefa agendada e watchdog | Docker no system-lab, `restart: unless-stopped`, backup cifrado |

### Segurança

Senhas com Argon2id; sessão em cookie `__Host-` HttpOnly/Secure/SameSite=Strict, guardada no banco, com
validade de 12 h renovada no uso e teto de 7 dias; token CSRF em toda gravação; bloqueio após 5 tentativas
de login; permissões por módulo (Qualidade, PCP, Produção – TT, Produção – Usinagem, Cadastros), administrador
e "pode aprovar"; auditoria de todas as alterações; nada é apagado (inativa-se, anula-se ou cancela-se);
contêineres sem privilégios, API com sistema de arquivos só de leitura e banco sem porta exposta; CSP e
demais cabeçalhos no nginx.

## Desenvolvimento (Windows)

Cada bloco parte da pasta do repositório.

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check app tests
```

```powershell
cd frontend
npm install
npm run build
```

Para subir localmente, crie `backend\.env` (fica fora do Git) com:

```
APP_ENV=dev
DATABASE_URL=sqlite:///../dados_dev/acokey.db
ARQUIVOS_DIR=../dados_dev/arquivos
ADMIN_SENHA_INICIAL=<uma senha com letras e números, 10+ caracteres>
```

```powershell
cd backend
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m app.carga ..\legado --dados data_teste --aplicar
.venv\Scripts\uvicorn app.main:app --port 8000
```

```powershell
cd frontend
npm run dev
```

O site abre em http://localhost:5173 (o Vite repassa `/api` para a porta 8000). Entre como `admin` com a
senha do `.env`, troque a senha e, em Usuários, defina uma senha provisória para quem for testar. Com
`APP_ENV=dev`, a documentação da API fica em http://localhost:8000/api/docs. A carga com `--dados data_teste`
usa a base de **testes** do sistema antigo.

## Carga do sistema antigo

`python -m app.carga <pasta do sistema antigo>` lê o `data/sistema.db` (só leitura), as planilhas e as pastas
de arquivos e mostra um relatório; com `--aplicar`, grava. Só roda com o banco novo sem lotes, sem
matéria-prima e sem OPs. Mantém os ids (o lote 7 continua lote 7) e copia os arquivos para a pasta nova com
caminho relativo.

- **Senhas não são migradas.** Todos os usuários entram sem senha utilizável e com troca obrigatória; o
  administrador define uma provisória para cada um na tela Usuários.
- **Só vira administrador quem for indicado com `--admin LOGIN`** (o login novo). O relatório avisa quem
  tinha o módulo Cadastros no sistema antigo (lá ele também cadastrava usuários) e não foi indicado.
- **`--renomear ANTIGO=NOVO`** troca o login de um usuário na carga (ex.: para o padrão `nome.sobrenome`).
  A assinatura e o histórico da auditoria vão junto para o login novo. As duas opções podem se repetir.
- Os logins de verdade são passados só na linha de comando, no servidor: **não os escreva neste repositório**.
- **Especificação que não seja número bloqueia a carga** (nunca se inventa valor da especificação técnica).
- O relatório lista arquivos referenciados que não existem no disco e arquivos da pasta de dados que o banco
  não referencia (por exemplo, os databooks gerados em `lotes/<id>/databook/`, que ficam só no sistema antigo
  até o módulo de databook ser feito).

Simulação com os dados reais em 23/11/2026: 18 lotes, 97 registros, 90 anexos, 106 OPs, 7 usuários,
111 arquivos (101,7 MB), nenhum arquivo faltando e nenhum bloqueio. Avisos: 4 OPs repetidas na
planilha de OPs (fica a última linha, igual ao sistema antigo) e 2 usuários com o módulo Cadastros.

No servidor, com a pasta do sistema antigo copiada para `~/acokey-carga/`. A carga roda com o usuário da
imagem (`app`, uid 10001), que é o dono do volume de arquivos; por isso a pasta passa a ser dele, sem acesso
para mais ninguém:

```bash
sudo chown -R 10001:10001 ~/acokey-carga && sudo chmod -R u+rX,go-rwx ~/acokey-carga
RODAR='docker compose run --rm --no-deps -v /home/ubuntu/acokey-carga:/carga:ro api'
CARGA='python -m app.carga /carga --renomear <antigo>=<novo> --admin <novo>'
$RODAR $CARGA              # só confere e mostra o relatório
$RODAR $CARGA --aplicar    # grava
```

Rode a carga depois da primeira subida da API: o administrador do `.env` (`ADMIN_LOGIN`) já existe e não é
tocado pela carga.

Depois da carga, apague a cópia (`sudo rm -rf ~/acokey-carga`): ela tem os dados reais e as planilhas.

## Publicação (system-lab)

Pasta `~/apps/acokey`, no mesmo padrão dos outros sistemas do servidor. Site: `acokey.acokorte.com.br`.
**A confirmar:** a porta local (8093), que precisa estar livre no servidor.

```bash
cp .env.example .env && chmod 600 .env     # trocar POSTGRES_PASSWORD, DATABASE_URL, ADMIN_LOGIN e ADMIN_SENHA_INICIAL
docker compose up -d --build               # site em 127.0.0.1:8093
```

Administradores: o da TI entra pelo `.env` (`ADMIN_LOGIN`, `ADMIN_NOME`, `ADMIN_SENHA_INICIAL`, criado na
primeira subida); o da Qualidade entra pela carga, com `--admin` (seção "Carga do sistema antigo"). Os dois
trocam a senha no primeiro acesso.

HTTPS (uma vez; o DNS `acokey.acokorte.com.br` já precisa apontar para o servidor, o mesmo IP de
`manutencao.acokorte.com.br`): `deploy/ativar_https.sh` emite o certificado, liga o site no nginx do servidor,
testa a configuração e recarrega (se o teste falhar, desliga o site de novo).

Backup (crontab do usuário `ubuntu`):

```
50 2 * * *  $HOME/apps/acokey/deploy/backup/backup.sh >> $HOME/.local/state/acokey-backup.log 2>&1
```

`deploy/backup/backup.sh` gera, por dia, um dump do banco e um pacote dos arquivos, ambos cifrados com
GPG/AES256 (banco guardado 30 dias, arquivos 7 dias, uma cópia mensal de cada por 12 meses). A senha fica em
`~/.config/acokey/backup.env` (`BACKUP_GPG_SENHA=...`, permissão 600) — **guarde uma cópia no cofre de
senhas; sem ela o backup não abre**. `deploy/backup/restaurar.sh <arquivo>` restaura o banco em um banco de
conferência e mostra as contagens.

## Decisões pendentes (com a Qualidade)

O sistema novo já funciona assim; cada item pode ser revertido se a Qualidade preferir o comportamento antigo.

1. **Relatórios gerados pelo sistema (Dureza RIP-35, TT, Visual)** estão ligados para todos. No antigo só
   funcionavam no modo de teste.
2. **Registro do tratamento térmico é sempre aprovado**, mesmo quando a dureza medida depois do TT dá reprovada
   (a reprovação aparece só no PDF), como no antigo.
3. **Databook do ARK:** a seção 08 sai "Oxidação Negra", as seções de etapas que não se aplicam ao ARK ficam de
   fora e o checklist não cobra dureza e tração. O antigo misturava.
4. **Limites da especificação travados:** quando o limite está cadastrado, o formulário da etapa usa o valor do
   cadastro e não deixa mudar; só o limite não cadastrado é digitado.
5. **Lote cancelado** tem o número trocado por `<número>-CANC<id>`, para o número voltar a ficar livre (o original
   fica na linha do tempo e na auditoria).
6. **Tirar um lote de uma carga de TT, envio ou OF** em edição apaga só o vínculo (com antes/depois na auditoria).
7. **Modelo do laboratório (.docx):** só as células marcadas "Preencher" são preenchidas (data e identificação).
   Material, ensaio e norma são texto fixo do modelo; para o sistema preenchê-los, marque essas células como
   "Preencher" no modelo.
8. **Reabrir NC e corrigir dureza** exigem "pode aprovar" (o antigo exigia só o módulo Qualidade).

## Mega (ERP, somente leitura) — desligado até o mapeamento

Mesmo padrão do EstoqueACK e dos Indicadores de Manutenção: usuário de banco **próprio deste sistema**
(`acokey_ro`), só com SELECT nas tabelas usadas, conexão em modo thick a partir do system-lab, toda sessão em
`SET TRANSACTION READ ONLY`. O sistema copia o que lê para o PostgreSQL e nunca grava no ERP.

O que deve vir do Mega: as ordens de produção (hoje vêm da planilha de OPs: cliente, item, descrição, quantidade,
PIV, PO, NF e faturamento), fornecedores e NF de entrada da matéria-prima e, talvez, a NF de saída da OF. Nenhuma
tabela do Mega foi mapeada ainda.

1. O DBA roda os blocos A e B de `scripts/mega/01_criar_usuario_leitura.sql` (leitura ampla só para o mapeamento).
2. No servidor: `deploy/configurar_mega.sh` (pede a senha sem mostrar, grava no `.env` e testa) e
   `docker compose exec api python -m app.mega testar`.
3. Mapeamento das tabelas; as consultas entram em `backend/app/mega.py`.
4. O DBA roda os blocos C (SELECT só nas tabelas usadas) e D (revoga a leitura ampla); `MEGA_HABILITADO=true`.

Socorro, quando ninguém consegue entrar:

```bash
docker compose exec api python -m app.admin desbloquear LOGIN
docker compose exec api python -m app.admin senha-provisoria LOGIN
```
