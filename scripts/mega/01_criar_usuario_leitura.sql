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

-- C) Tabelas que as consultas usam: PREENCHER depois do mapeamento (ver backend/app/mega.py).
--    Exemplo do formato:
-- GRANT SELECT ON ACOKORTE.<TABELA> TO acokey_ro;  -- <para que serve>

-- D) Encerrar o mapeamento: tira a leitura ampla do bloco B. Rodar logo depois do bloco C.
-- REVOKE SELECT ANY TABLE      FROM acokey_ro;
-- REVOKE SELECT ANY DICTIONARY FROM acokey_ro;
-- Depois, no servidor, conferir:
--   docker compose exec -T api python -m app.mega testar </dev/null

-- Conferência: o usuário NÃO pode ter nenhum privilégio de escrita
-- SELECT * FROM dba_sys_privs WHERE grantee = 'ACOKEY_RO';
-- SELECT * FROM dba_tab_privs WHERE grantee = 'ACOKEY_RO' AND privilege <> 'SELECT';
