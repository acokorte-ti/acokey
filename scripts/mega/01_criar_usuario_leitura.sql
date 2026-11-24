-- ============================================================================
-- AçoKey Q — usuário SOMENTE LEITURA no Oracle 19c do Mega
-- Executar como DBA, conectado ao PDB do Mega.
-- Mesmo roteiro do EstoqueACK e dos Indicadores de Manutenção, com um usuário PRÓPRIO
-- deste sistema: o acesso de um sistema não amplia o do outro, e a auditoria do Oracle
-- mostra qual sistema fez cada consulta.
--
-- Passo 1: troque <SENHA_FORTE> e rode o bloco A. Use 16 ou mais caracteres, sem espaço e
--          sem aspas simples (o script que grava a senha no servidor não aceita esses dois).
-- Passo 2: rode o bloco B (leitura ampla, SÓ durante o mapeamento das tabelas de
--          ordem de produção, faturamento e nota fiscal de entrada).
-- Passo 3: depois do mapeamento, preencha e rode o bloco C (SELECT só nas tabelas usadas)
--          e rode o bloco D (revoga a leitura ampla).
-- A senha vai direto para o .env do servidor, digitada em deploy/configurar_mega.sh;
-- nunca para o repositório, e-mail ou conversa.
-- ============================================================================

-- A) Usuário e perfil com limites (evita que uma consulta pesada atrapalhe o ERP)
CREATE PROFILE acokey_ro_perfil LIMIT
  SESSIONS_PER_USER       3
  CPU_PER_CALL            30000      -- centésimos de segundo (5 min)
  LOGICAL_READS_PER_CALL  5000000
  IDLE_TIME               30         -- minutos
  FAILED_LOGIN_ATTEMPTS   5
  PASSWORD_LOCK_TIME      1/96;      -- 15 minutos

CREATE USER acokey_ro IDENTIFIED BY "<SENHA_FORTE>" PROFILE acokey_ro_perfil;
GRANT CREATE SESSION TO acokey_ro;

-- B) Somente durante o MAPEAMENTO: ler qualquer tabela/visão e o dicionário.
--    (SELECT ANY TABLE não permite alterar nada; é revogado no bloco D.)
GRANT SELECT ANY TABLE      TO acokey_ro;
GRANT SELECT ANY DICTIONARY TO acokey_ro;

-- C) Tabelas que as consultas usam.
--    Já mapeadas e validadas em outros sistemas (EstoqueACK e Indicadores de Manutenção):
GRANT SELECT ON ACOKORTE.PRO_ORDENS      TO acokey_ro;  -- OP: item, quantidade, situação, pedido alternativo
GRANT SELECT ON ACOKORTE.PRO_ORIGEM      TO acokey_ro;  -- origem da OP (pedido de venda)
GRANT SELECT ON ACOKORTE.VEN_PEDIDOVENDA TO acokey_ro;  -- pedido de venda (PIV) e cliente
GRANT SELECT ON ACOKORTE.GLO_AGENTES     TO acokey_ro;  -- nome do cliente e do fornecedor
GRANT SELECT ON ACOKORTE.EST_PRODUTOS    TO acokey_ro;  -- descrição do item (CODITEM)
GRANT SELECT ON ACOKORTE.EST_RECEBIMENTO TO acokey_ro;  -- nota fiscal de entrada (matéria-prima)
GRANT SELECT ON ACOKORTE.EST_ITENSRECEB  TO acokey_ro;  -- itens da nota de entrada
--    Mapeadas em 24/11/2026 para o AçoKey Q (ver docs/integracao_mega.md):
GRANT SELECT ON ACOKORTE.VEN_ITEMPEDIDOVENDA      TO acokey_ro;  -- item do pedido: PO do cliente, qtd faturada
GRANT SELECT ON ACOKORTE.VEN_ITEMPEDI_VEN_ITEMNOT TO acokey_ro;  -- vínculo item do pedido x item da nota
GRANT SELECT ON ACOKORTE.VEN_ITEMNOTAFISCAL       TO acokey_ro;  -- item da nota fiscal de saída
GRANT SELECT ON ACOKORTE.VEN_NOTAFISCAL           TO acokey_ro;  -- nota fiscal de saída: número, data, situação

-- D) Encerrar o mapeamento: tira a leitura ampla do bloco B. Rodar logo depois do bloco C.
-- REVOKE SELECT ANY TABLE      FROM acokey_ro;
-- REVOKE SELECT ANY DICTIONARY FROM acokey_ro;
-- Depois, no servidor, conferir:
--   docker compose exec -T api python -m app.mega testar </dev/null

-- Conferência: o usuário NÃO pode ter nenhum privilégio de escrita
-- SELECT * FROM dba_sys_privs WHERE grantee = 'ACOKEY_RO';
-- SELECT * FROM dba_tab_privs WHERE grantee = 'ACOKEY_RO' AND privilege <> 'SELECT';
