# CLAUDE.md: AçoKey Q

Contexto para o Claude Code. Leia inteiro antes de mexer em qualquer coisa. O `README.md` tem a arquitetura,
o estado de cada fase e os comandos.

> **O repositório é PÚBLICO.** Não escreva em arquivo versionado: o nome ou os contatos do cliente final,
> nomes de funcionários, números reais de OP, lote ou corrida, caminhos e máquinas da rede interna, nem
> nenhum dado de produção. Em testes e exemplos, use valores fictícios (OP 900001, "Fulano", "CLIENTE EXEMPLO").

## 1. O que é

Controle de lotes de fabricação das chavetas PIN, BOX e ARK (Qualidade da AçoKorte). Cada lote passa por
11 etapas (`backend/app/fluxo.py`); cada etapa tem registros aprovados/reprovados, anexos e, na reprovação,
uma não conformidade formal.

O sistema foi criado pelo Gerente da Qualidade (não é programador) em Flask + SQLite e está sendo reescrito
pela TI no padrão dos sistemas internos, para rodar no system-lab e depois entrar no "AçoKorte Sistemas".
O sistema antigo continua em uso no notebook da Qualidade até a virada.

- Com o desenvolvedor da TI: pode usar termos técnicos.
- Telas e mensagens são para a Qualidade e a equipe da fábrica: português simples, sem jargão.

## 2. Onde está cada coisa

| Caminho | Papel |
|---|---|
| `backend/app/fluxo.py` | Etapas, quais se aplicam a cada tipo, quando o lote avança. Funções puras. **A ordem de `ETAPAS` não pode mudar** (`lotes.etapa` guarda o índice) |
| `backend/app/estado.py` | Lê do banco o estado que o `fluxo.py` precisa (último registro não anulado, NC de cada registro), sem N+1 |
| `backend/app/models.py` | Todas as tabelas, inclusive as dos módulos ainda sem tela |
| `backend/app/seguranca.py` | Senha, sessão, CSRF, `exigir(...)`, `auditar(...)` |
| `backend/app/carga.py` | Importa o sistema antigo (banco, planilhas, arquivos) |
| `legado/` | **Só na máquina local, fora do Git.** O sistema antigo inteiro: código, documentação e dados reais de produção |
| `legado/app.py` | Fonte das regras de negócio ainda não portadas. Antes de portar um módulo, leia a rota antiga |
| `legado/CLAUDE.md` | Documentação completa do sistema antigo. Regras de negócio, telas, decisões, nome do cliente |
| `legado/data/`, `legado/DATABOOK/`, planilhas, `legado/assinaturas/` | Dados reais. Nunca alterar, nunca versionar, nunca mostrar conteúdo em conversa |

Se `legado/` não existir na máquina, peça a pasta à TI (há cópia no notebook da Qualidade e no backup).
Padrão de referência dos sistemas internos: `..\manut-mtbf-mttr\` (mais completo) e `..\relata-visita\`.

## 3. Regras de negócio que valem em qualquer reescrita

- **Nunca inventar valor da especificação técnica do cliente.** Se um limite não está cadastrado,
  perguntar. A carga bloqueia se um limite não for número.
- **Nunca citar o cliente final em documento que pode sair da empresa** (ex.: PDF para prestador externo).
  Documento interno (ex.: Ordem de Faturamento) pode. O nome está em `legado/CLAUDE.md`.
- **Nunca "arrumar" código de documento oficial** (ex.: `FOR-TT-IS.8.5-06-8`): copiar exatamente.
- Razão social nos documentos novos: "AçoKorte Indústria Metalúrgica e Comércio" (sem "Ltda.", sem CNPJ).
- "Enviado-DB" (databook mandado ao cliente) ≠ saída física do lote (Ordem de Faturamento). Não misturar.
- Reprovação abre NC automaticamente. Retrabalho só libera com um registro novo aprovado; sucata, uso como
  está e anulada liberam. "Uso como está" e "anulada" exigem quem **pode aprovar** e justificativa escrita.
- Registro anulado é invisível para o fluxo. Registros antigos podem ter `dados` em formato diferente
  (ex.: dureza antiga em `report.tabelas.linhas`, nova em `leituras`): ao reprocessar, tratar os dois.
- PIN/BOX: SC 4330, 30–39 HRc. ARK: H11 Modified, 43–48 HRc, pula dureza, usinagem e tamboreamento, e no
  laboratório só faz Charpy.

## 4. Convenções

- **Idioma:** português do Brasil em tudo, inclusive nomes de funções, variáveis e arquivos.
- **Comandos locais:** PowerShell no Windows, um por bloco. No servidor: bash, uma sessão SSH só (o Snort
  bloqueia várias seguidas).
- **Banco:** mudou `models.py`? Crie uma migração nova em `backend/alembic/versions/` (nunca edite a `0001`
  depois que for para produção) e confira com `alembic check`. Datas de produção são hora local sem fuso
  (`DateTime`); datas de sistema têm fuso (`DataHoraFuso`).
- **Permissões:** toda rota nova usa `exigir(...)` (ou `QUALQUER`, `ADMIN`, `QUALIDADE`, `APROVADOR`) e ganha
  um teste de acesso negado. Administrador NÃO tem "pode aprovar" automaticamente.
- **Auditoria:** toda gravação chama `auditar(...)` na mesma transação, com `lote_id` quando houver.
- **Nada é apagado:** inativar, anular ou cancelar.
- **Arquivos:** sempre caminho relativo à pasta de arquivos; servir só por `caminho_seguro()`.
- **Testes:** `pytest` em SQLite temporário; no CI também em PostgreSQL. Depois de mexer no front,
  `npm run build` (o `tsc` confere os tipos).
- **Segredos e dados:** nunca versionar `.env`, bancos, planilhas, PDFs, assinaturas, `dados_dev/` nem
  `legado/`. Conferir `git status` e o aviso do topo antes de cada commit.
- **Commits:** mensagens curtas em português (`feat: registro das etapas`).

## 5. Próximo passo

Todos os módulos do sistema antigo foram portados (ver tabela no README). Faltam: visita guiada por tela
(o Início já dispara o evento `acokey:visita-guiada`; o antigo usava driver.js com 25 tours), manual do usuário
atualizado, mapeamento das tabelas do Mega e a homologação no system-lab. Decisões em aberto com a Qualidade
estão no fim do README ("Decisões pendentes").

Estrutura por módulo: backend `app/api_<modulo>.py` (+ auxiliares) e `tests/test_<modulo>.py`; front
`src/paginas/<modulo>/` com `index.tsx` (sub-rotas), `tipos.ts` e CSS próprio com prefixo. O `App.tsx` carrega
cada módulo sob demanda. Peças comuns: `arquivos.py`, `numeracao.py`, `nc.py`, `lotes.py`, `parametros.py`,
`pdf_comum.py`, `historico.py`; no front `EnvioArquivos.tsx` e `lib/teclado.ts`.
