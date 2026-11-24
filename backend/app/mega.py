"""Integração com o ERP Mega (Oracle) — SOMENTE LEITURA. Hoje DESLIGADA (MEGA_HABILITADO=false).

Padrão dos sistemas internos (o mesmo do EstoqueACK e dos Indicadores de Manutenção):
- Um usuário de banco PRÓPRIO deste sistema (`acokey_ro`), só com SELECT nas tabelas usadas, criado pelo DBA com
  `scripts/mega/01_criar_usuario_leitura.sql`. Assim o acesso de um sistema não amplia o do outro, e a auditoria
  do Oracle mostra qual sistema fez cada consulta.
- Conexão em modo thick (o banco do Mega exige criptografia nativa de rede), só a partir do servidor system-lab.
- Toda sessão começa com SET TRANSACTION READ ONLY. O sistema nunca grava no ERP: copia o que leu para as tabelas
  dele (PostgreSQL).
- A senha vai direto para o .env do servidor por `deploy/configurar_mega.sh`; nunca para o repositório ou conversa.

O QUE AINDA FALTA (precisa do mapeamento das tabelas com o DBA; nenhum nome de tabela foi inventado aqui):
1. Ordens de produção -> tabela `ordens_producao` (hoje vem da planilha "Cadastro_Lote_*.xlsx"): cliente, OP,
   CODITEM, descrição, classificação PIN/BOX/ARK, quantidade do lote, pedido (PIV), pedido do cliente (PO),
   NF e data de faturamento, quantidade faturada.
2. Fornecedores de matéria-prima e NF de entrada da corrida (tela Matéria-prima).
3. Possivelmente a NF de saída da Ordem de Faturamento.
Passo a passo: o DBA roda os blocos A e B do script (leitura ampla temporária), rodamos `python -m app.mega testar`
e o mapeamento no servidor; depois os blocos C (SELECT só nas tabelas usadas) e D (revoga a leitura ampla), e a
consulta entra aqui, no mesmo formato de `manut-mtbf-mttr/backend/app/mega.py`.
"""
import re
import threading

from app.config import config

_cliente_iniciado = False
_trava_cliente = threading.Lock()


class MegaIndisponivel(Exception):
    pass


def situacao() -> tuple[bool, str]:
    """(pronto para ler?, motivo quando não está)."""
    cfg = config()
    if not cfg.mega_habilitado:
        return False, "A integração com o Mega está desligada."
    if not (cfg.mega_dsn and cfg.mega_usuario and cfg.mega_senha):
        return False, "Os dados de conexão com o Mega não foram configurados no servidor."
    return True, ""


def conectar():
    """Conexão com o Oracle do Mega em modo thick (o banco exige criptografia nativa de rede)."""
    import oracledb

    global _cliente_iniciado
    cfg = config()
    with _trava_cliente:
        if not _cliente_iniciado:
            oracledb.init_oracle_client(lib_dir=cfg.mega_instant_client)
            _cliente_iniciado = True
    return oracledb.connect(user=cfg.mega_usuario, password=cfg.mega_senha, dsn=cfg.mega_dsn)


def _mensagem_publica(erro: Exception) -> str:
    """Só o código e o texto do erro do Oracle (sem DSN, usuário ou senha)."""
    achado = re.search(r"(ORA|DPI|DPY)-\d+[^\n]*", str(erro))
    return achado.group(0)[:300] if achado else type(erro).__name__


def testar() -> None:
    """`python -m app.mega testar`: confere a conexão e o que o usuário do banco pode fazer. Não altera nada."""
    cfg = config()
    if not (cfg.mega_dsn and cfg.mega_usuario and cfg.mega_senha):
        raise SystemExit("MEGA_DSN, MEGA_USUARIO e MEGA_SENHA ainda não estão no .env do servidor.")
    try:
        with conectar() as conexao, conexao.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            usuario = cursor.execute("select user from dual").fetchone()[0]
            privilegios = [linha[0] for linha in cursor.execute("select privilege from session_privs order by 1")]
            visiveis = cursor.execute(
                "select count(*) from all_objects where owner = :dono and object_type in ('TABLE', 'VIEW')",
                dono=cfg.mega_esquema,
            ).fetchone()[0]
    except Exception as erro:  # noqa: BLE001 — ferramenta de diagnóstico: mostra o motivo e sai
        raise SystemExit(f"Não conectou: {_mensagem_publica(erro)}") from None
    de_escrita = [p for p in privilegios if not p.startswith(("SELECT", "READ", "CREATE SESSION"))]
    print(f"Conexão OK como {usuario}.")
    print(f"Tabelas e visões de {cfg.mega_esquema} visíveis: {visiveis}.")
    print(f"Privilégios: {', '.join(privilegios) or '(nenhum de sistema)'}.")
    if de_escrita:
        print(f"ATENÇÃO: este usuário tem privilégios além de leitura: {', '.join(de_escrita)}. Peça ao DBA para revogar.")
    else:
        print("Somente leitura: confirmado.")


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["testar"]:
        testar()
    else:
        raise SystemExit("Uso: python -m app.mega testar")
