"""Parâmetros configuráveis pela tela (tabela `parametros`).

Tudo o que identifica o cliente final, endereços e padrões da fábrica fica aqui, e não no código: o
repositório é público. A carga do sistema antigo preenche os valores a partir de um arquivo local
(`parametros_acokey.json`, fora do Git).
"""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Parametro

# chave -> (valor padrão, descrição para a tela). Chave fora desta lista também funciona com ler(..., padrao).
PADROES: dict[str, tuple[str, str]] = {
    "empresa_razao_social": ("AçoKorte Indústria Metalúrgica e Comércio", "Razão social nos documentos (sem 'Ltda.', sem CNPJ)"),
    "empresa_endereco": ("", "Endereço da fábrica nos documentos"),
    "cliente_nome": ("", "Nome do cliente final. Só aparece em documentos INTERNOS (nunca em PDF para prestador externo)"),
    "cliente_nome_curto": ("", "Nome curto do cliente final (ex.: no topo das telas e na OF)"),
    "especificacao_codigo": ("", "Código e revisão da especificação técnica do cliente, como deve sair nos documentos"),
    "laser_formato": ("{ano}T{tri}-C{corrida}-L{lote}-{seq:03d}", "Formato do código gravado a laser em cada peça"),
    "forno_tempera_padrao": ("", "Forno de têmpera pré-selecionado no relatório de tratamento térmico"),
    "forno_revenimento_padrao": ("", "Forno de revenimento pré-selecionado no relatório de tratamento térmico"),
    "elementos_quimicos": ("C,Mn,Si,P,S,Cr,Ni,Mo,Cu,V,Al", "Elementos da composição química, na ordem do formulário"),
    "qualidade_responsavel": ("", "Nome que sai em 'Qualidade - <nome>' na assinatura do PDF de registro de etapa"),
    # Relatórios gerados pelo sistema (Dureza, Tratamento térmico, Visual). {tipo} vira PIN, BOX ou ARK.
    "relatorio_nome_peca_padrao": ("", "Nome da peça nos relatórios quando a OP não tem descrição"),
    "relatorio_desenho_padrao": ("", "Desenho/revisão nos relatórios quando não há desenho cadastrado para o item"),
    "relatorio_tt_item": ("Chaveta {tipo}", "Campo 'Item' do relatório de tratamento térmico"),
    "visual_designacao_pin_box": ("PIN/BOX", "Designação do produto PIN/BOX no relatório de inspeção visual"),
    "visual_designacao_laser_pin_box": ("PIN/BOX", "Designação gravada a laser no PIN/BOX (relatório visual)"),
    # Modelo .docx de requisição de ensaio do laboratório (envios a prestador)
    "modelo_ensaio_prestador": ("", "Trecho do nome do laboratório que usa o modelo .docx (vazio = botão escondido)"),
    "modelo_ensaio_arquivo": ("", "Nome do .docx em recursos/modelos/ (vazio = o único .docx da pasta)"),
    "modelo_ensaio_texto_tracao": ("Ensaio de tração", "Texto do ensaio de tração no modelo do laboratório"),
    "modelo_ensaio_texto_charpy": ("Ensaio de impacto Charpy", "Texto do ensaio Charpy no modelo do laboratório"),
    "modelo_ensaio_norma_tracao": ("ASTM A370", "Norma de execução do ensaio de tração"),
    "modelo_ensaio_norma_charpy": ("ASTM E23", "Norma de execução do ensaio Charpy"),
}  # fmt: skip


def ler(db: Session, chave: str, padrao: str | None = None) -> str:
    """Valor gravado; se não houver, o padrão de PADROES (ou o informado)."""
    linha = db.get(Parametro, chave)
    if linha is not None and linha.valor != "":
        return linha.valor
    if padrao is not None:
        return padrao
    return PADROES.get(chave, ("", ""))[0]


def todos(db: Session) -> dict[str, str]:
    gravados = {p.chave: p.valor for p in db.scalars(select(Parametro))}
    return {chave: gravados.get(chave) or padrao for chave, (padrao, _) in PADROES.items()} | {
        k: v for k, v in gravados.items() if k not in PADROES
    }


def gravar(db: Session, chave: str, valor: str, login: str) -> tuple[str, str]:
    """Grava e devolve (antes, depois). Quem chama audita e faz o commit."""
    linha = db.get(Parametro, chave)
    antes = linha.valor if linha else ""
    if linha is None:
        linha = Parametro(chave=chave)
        db.add(linha)
    linha.valor = valor
    linha.alterado_em = datetime.now(UTC)
    linha.alterado_por = login
    return antes, valor
