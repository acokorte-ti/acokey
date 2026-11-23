"""Tabelas do sistema.

Datas de PRODUÇÃO (registros, anexos, eventos, envios) são a hora local da fábrica, SEM fuso: é o que
aparece nos relatórios e o que veio do sistema antigo. Datas de SISTEMA (sessões, auditoria, login)
têm fuso.

Regra do projeto: nada é apagado. Cadastros são inativados; registros de etapa são anulados;
ordens e envios são cancelados.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.tipos import DataHoraFuso, IdGrande, Json

TIPOS_LOTE = ("PIN", "BOX", "ARK")
MODULOS = ("qualidade", "pcp", "producao_tt", "producao_usinagem", "cadastros")
STATUS_REGISTRO = ("aprovado", "reprovado", "pendente")
STATUS_MP = ("pendente", "aprovada", "reprovada")
STATUS_NC = ("aberta", "em_tratamento", "encerrada")
DISPOSICOES_NC = ("retrabalho", "sucata", "uso_como_esta", "anulada")
STATUS_CARGA_TT = ("planejada", "em_andamento", "concluida", "cancelada")
STATUS_ENVIO = ("enviado", "retornado", "cancelado")
STATUS_OF = ("rascunho", "emitida", "faturada", "cancelada")


def _em(valores: tuple[str, ...], coluna: str) -> str:
    return f"{coluna} IN ({', '.join(repr(v) for v in valores)})"


# ---------------------------------------------------------------- acesso


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(60), unique=True)
    nome: Mapped[str] = mapped_column(String(120))
    cargo: Mapped[str] = mapped_column(String(80), default="", server_default="")
    senha_hash: Mapped[str] = mapped_column(String(255))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    trocar_senha: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    tentativas_falhas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DataHoraFuso)
    criado_em: Mapped[datetime] = mapped_column(DataHoraFuso, server_default=func.now())
    ultimo_login_em: Mapped[datetime | None] = mapped_column(DataHoraFuso)
    # Administrador do sistema: cadastra usuários e enxerga todos os módulos.
    # Substitui a "senha administrativa" única que o sistema antigo compartilhava.
    admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    mod_qualidade: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    mod_pcp: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    mod_producao_tt: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    mod_producao_usinagem: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    mod_cadastros: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Pode assinar relatórios como "Aprovado por" e decidir desvios (uso como está, anulação).
    # É autoridade da Qualidade: ser administrador NÃO dá esse direito.
    pode_aprovar: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    assinatura_arquivo: Mapped[str | None] = mapped_column(String(255))  # caminho dentro da pasta de arquivos
    tutorial_visto_em: Mapped[datetime | None] = mapped_column(DataHoraFuso)

    @property
    def modulos(self) -> list[str]:
        return [m for m in MODULOS if getattr(self, f"mod_{m}")]


class Sessao(Base):
    __tablename__ = "sessoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 do token do cookie
    csrf: Mapped[str] = mapped_column(String(64))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    criada_em: Mapped[datetime] = mapped_column(DataHoraFuso, server_default=func.now())
    expira_em: Mapped[datetime] = mapped_column(DataHoraFuso)
    ip: Mapped[str | None] = mapped_column(String(45))
    agente: Mapped[str | None] = mapped_column(String(300))

    usuario: Mapped[Usuario] = relationship()


class Auditoria(Base):
    """Registro de quem fez o quê. Só recebe inserções."""

    __tablename__ = "auditoria"
    __table_args__ = (Index("ix_auditoria_quando", "quando"),)

    id: Mapped[int] = mapped_column(IdGrande, primary_key=True)
    quando: Mapped[datetime] = mapped_column(DataHoraFuso, server_default=func.now())
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    login: Mapped[str | None] = mapped_column(String(60))
    acao: Mapped[str] = mapped_column(String(30))
    entidade: Mapped[str | None] = mapped_column(String(40))
    entidade_id: Mapped[str | None] = mapped_column(String(80))
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("lotes.id", ondelete="SET NULL"), index=True)
    detalhes: Mapped[dict | None] = mapped_column(Json)
    ip: Mapped[str | None] = mapped_column(String(45))


# ---------------------------------------------------------------- cadastros (eram planilhas Excel)


class FornecedorMP(Base):
    __tablename__ = "fornecedores_mp"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True)
    razao_social: Mapped[str] = mapped_column(String(160))
    materiais: Mapped[str] = mapped_column(String(200), default="", server_default="")
    contato: Mapped[str] = mapped_column(String(200), default="", server_default="")
    observacoes: Mapped[str] = mapped_column(Text, default="", server_default="")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class Prestador(Base):
    """Laboratórios, revestidores e empresas de calibração. Não têm login."""

    __tablename__ = "prestadores"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True)
    razao_social: Mapped[str] = mapped_column(String(160))
    tipo_servico: Mapped[str] = mapped_column(String(60), default="", server_default="")
    contato: Mapped[str] = mapped_column(String(200), default="", server_default="")
    observacoes: Mapped[str] = mapped_column(Text, default="", server_default="")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class Equipamento(Base):
    """Durômetro e fornos, com a validade da calibração."""

    __tablename__ = "equipamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True)
    descricao: Mapped[str] = mapped_column(String(200), default="", server_default="")
    setor: Mapped[str] = mapped_column(String(80), default="", server_default="")
    marca: Mapped[str] = mapped_column(String(80), default="", server_default="")
    data_calibracao: Mapped[date | None] = mapped_column(Date)
    validade_calibracao: Mapped[date | None] = mapped_column(Date)
    certificado: Mapped[str] = mapped_column(String(80), default="", server_default="")
    empresa_calibracao: Mapped[str] = mapped_column(String(160), default="", server_default="")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class OrdemProducao(Base):
    """Cadastro mestre de OPs (antiga planilha Cadastro_Lote_<cliente>.xlsx, aba Dados)."""

    __tablename__ = "ordens_producao"

    id: Mapped[int] = mapped_column(primary_key=True)
    op: Mapped[str] = mapped_column(String(20), unique=True)
    cliente: Mapped[str] = mapped_column(String(160), default="", server_default="")
    coditem: Mapped[str] = mapped_column(String(40), default="", server_default="")
    descricao: Mapped[str] = mapped_column(String(300), default="", server_default="")
    tipo: Mapped[str | None] = mapped_column(String(3))  # classificação PIN/BOX/ARK (pode faltar na planilha)
    data_faturamento: Mapped[date | None] = mapped_column(Date)
    nf: Mapped[str] = mapped_column(String(40), default="", server_default="")
    piv: Mapped[str] = mapped_column(String(40), default="", server_default="")  # coluna "Pedido" da planilha
    qt_lote: Mapped[int | None] = mapped_column(Integer)
    qt_faturada: Mapped[int | None] = mapped_column(Integer)
    projeto: Mapped[str] = mapped_column(String(120), default="", server_default="")
    po: Mapped[str] = mapped_column(String(60), default="", server_default="")  # pedido do cliente


# ---------------------------------------------------------------- especificações (nunca inventar valores)


class EspecificacaoTipo(Base):
    """Limites de dureza, tração e Charpy por tipo de chaveta. Vêm da especificação técnica oficial."""

    __tablename__ = "especificacoes_tipo"
    __table_args__ = (CheckConstraint(_em(TIPOS_LOTE, "tipo"), name="ck_especificacoes_tipo_tipo"),)

    tipo: Mapped[str] = mapped_column(String(3), primary_key=True)
    dureza_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    dureza_max: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    tr_le_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # limite de escoamento
    tr_le_max: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    tr_lr_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # limite de resistência
    tr_lr_max: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    tr_al_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # alongamento
    tr_ra_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # redução de área
    ch_temp: Mapped[str] = mapped_column(String(40), default="", server_default="")  # texto: "Ambiente", "-20"
    ch_med_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    ch_ind_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    ch_dim_cp: Mapped[str] = mapped_column(String(40), default="", server_default="")


class EspecificacaoCota(Base):
    """Cotas dimensionais por desenho (CODITEM). Texto, exatamente como foi cadastrado."""

    __tablename__ = "especificacoes_cotas"

    id: Mapped[int] = mapped_column(primary_key=True)
    coditem: Mapped[str] = mapped_column(String(40), index=True)
    descricao: Mapped[str] = mapped_column(String(200), default="", server_default="")
    nominal: Mapped[str] = mapped_column(String(40), default="", server_default="")
    tol_min: Mapped[str] = mapped_column(String(40), default="", server_default="")
    tol_max: Mapped[str] = mapped_column(String(40), default="", server_default="")


# ---------------------------------------------------------------- matéria-prima


class MateriaPrima(Base):
    """Corrida de matéria-prima recebida. Uma corrida pode alimentar várias OPs."""

    __tablename__ = "materias_primas"
    __table_args__ = (CheckConstraint(_em(STATUS_MP, "status"), name="ck_materias_primas_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nf_entrada: Mapped[str] = mapped_column(String(40), default="", server_default="")
    corrida: Mapped[str] = mapped_column(String(60), default="", server_default="", index=True)
    fornecedor: Mapped[str] = mapped_column(String(160), default="", server_default="")
    tipo_destino: Mapped[str] = mapped_column(String(3), default="", server_default="")
    data_recebimento: Mapped[date | None] = mapped_column(Date)
    qt_fund: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qt_real: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qt_ok: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qt_rej: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qt_retrab: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qt_cp_tt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    observacoes: Mapped[str] = mapped_column(Text, default="", server_default="")
    criado_em: Mapped[datetime | None] = mapped_column(DateTime)
    responsavel: Mapped[str] = mapped_column(String(120), default="", server_default="")
    status: Mapped[str] = mapped_column(String(12), default="pendente", server_default="pendente")
    aprovado_por: Mapped[str] = mapped_column(String(120), default="", server_default="")
    aprovado_em: Mapped[datetime | None] = mapped_column(DateTime)
    obs_aprovacao: Mapped[str] = mapped_column(Text, default="", server_default="")


class MateriaPrimaAnexo(Base):
    __tablename__ = "materias_primas_anexos"

    id: Mapped[int] = mapped_column(primary_key=True)
    materia_prima_id: Mapped[int] = mapped_column(ForeignKey("materias_primas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(255))
    arquivo: Mapped[str] = mapped_column(String(400))  # caminho dentro da pasta de arquivos
    quando: Mapped[datetime | None] = mapped_column(DateTime)


# ---------------------------------------------------------------- lotes e o fluxo de etapas


class Lote(Base):
    __tablename__ = "lotes"
    __table_args__ = (CheckConstraint(_em(TIPOS_LOTE, "tipo"), name="ck_lotes_tipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(40), unique=True)
    op: Mapped[str] = mapped_column(String(20), index=True)
    tipo: Mapped[str] = mapped_column(String(3))
    qtd: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    corrida: Mapped[str] = mapped_column(String(60), default="", server_default="")
    coditem: Mapped[str] = mapped_column(String(40), default="", server_default="")
    materia_prima_id: Mapped[int | None] = mapped_column(ForeignKey("materias_primas.id"), index=True)
    # Cursor da etapa em que o lote foi deixado (índice em fluxo.ETAPAS). O estado mostrado nas telas
    # é sempre recalculado pelos registros (fluxo.etapa_real), não lido daqui.
    etapa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    etapa_desde: Mapped[datetime | None] = mapped_column(DateTime)
    criado_em: Mapped[datetime | None] = mapped_column(DateTime)


class Registro(Base):
    """Uma aprovação ou reprovação de etapa. Os dados do formulário ficam em JSON.

    Registro anulado (erro de digitação reconhecido numa não conformidade) é ignorado pelo fluxo.
    """

    __tablename__ = "registros"
    __table_args__ = (
        CheckConstraint(_em(STATUS_REGISTRO, "status"), name="ck_registros_status"),
        Index("ix_registros_lote_etapa", "lote_id", "etapa", "sub"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"))
    etapa: Mapped[str] = mapped_column(String(20))
    sub: Mapped[str] = mapped_column(String(10), default="", server_default="")
    status: Mapped[str] = mapped_column(String(10))
    dados: Mapped[dict | None] = mapped_column(Json)
    quando: Mapped[datetime | None] = mapped_column(DateTime)
    responsavel: Mapped[str] = mapped_column(String(120), default="", server_default="")
    # Quem estava logado ao gravar (o sistema antigo só tinha o nome digitado em "responsavel")
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    anulado: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    anulado_motivo: Mapped[str] = mapped_column(Text, default="", server_default="")
    anulado_em: Mapped[datetime | None] = mapped_column(DateTime)
    anulado_por: Mapped[str] = mapped_column(String(120), default="", server_default="")


class Anexo(Base):
    """Arquivo (PDF/JPG/PNG) ligado a uma etapa de um lote."""

    __tablename__ = "anexos"

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    etapa: Mapped[str] = mapped_column(String(20))
    sub: Mapped[str] = mapped_column(String(10), default="", server_default="")
    nome: Mapped[str] = mapped_column(String(255))
    arquivo: Mapped[str] = mapped_column(String(400))  # caminho dentro da pasta de arquivos
    quando: Mapped[datetime | None] = mapped_column(DateTime)
    # Evidência só interna (ex.: fotos): não entra no databook do cliente
    apenas_registro: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Evento(Base):
    """Linha do tempo de um lote, em texto para leitura humana."""

    __tablename__ = "eventos"

    id: Mapped[int] = mapped_column(IdGrande, primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    quando: Mapped[datetime | None] = mapped_column(DateTime)
    texto: Mapped[str] = mapped_column(Text)


class NaoConformidade(Base):
    """Aberta automaticamente quando um registro de etapa é reprovado."""

    __tablename__ = "nao_conformidades"
    __table_args__ = (
        CheckConstraint(_em(STATUS_NC, "status"), name="ck_nao_conformidades_status"),
        CheckConstraint(_em(("", *DISPOSICOES_NC), "disposicao"), name="ck_nao_conformidades_disposicao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(20), unique=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    etapa: Mapped[str] = mapped_column(String(20), default="", server_default="")
    sub: Mapped[str] = mapped_column(String(10), default="", server_default="")
    registro_id: Mapped[int | None] = mapped_column(ForeignKey("registros.id"), index=True)
    descricao: Mapped[str] = mapped_column(Text, default="", server_default="")
    qtd_lote_na_abertura: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qtd_afetada: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    disposicao: Mapped[str] = mapped_column(String(20), default="", server_default="")
    justificativa: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(15), default="aberta", server_default="aberta", index=True)
    aberta_em: Mapped[datetime | None] = mapped_column(DateTime)
    aberta_por: Mapped[str] = mapped_column(String(120), default="", server_default="")
    decidida_em: Mapped[datetime | None] = mapped_column(DateTime)
    decidida_por: Mapped[str] = mapped_column(String(120), default="", server_default="")
    encerrada_em: Mapped[datetime | None] = mapped_column(DateTime)
    encerrada_por: Mapped[str] = mapped_column(String(120), default="", server_default="")
    observacoes: Mapped[str] = mapped_column(Text, default="", server_default="")


# ---------------------------------------------------------------- tratamento térmico


class CargaTT(Base):
    """Lotes que entram juntos no forno. Um lote pode estar em várias cargas (têmpera, revenimento)."""

    __tablename__ = "cargas_tt"
    __table_args__ = (CheckConstraint(_em(STATUS_CARGA_TT, "status"), name="ck_cargas_tt_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(20), unique=True)
    forno_tempera_codigo: Mapped[str] = mapped_column(String(30), default="", server_default="")
    forno_revenimento_codigo: Mapped[str] = mapped_column(String(30), default="", server_default="")
    data_planejada: Mapped[date | None] = mapped_column(Date)
    data_inicio: Mapped[datetime | None] = mapped_column(DateTime)
    data_fim: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(15), default="planejada", server_default="planejada")
    observacoes: Mapped[str] = mapped_column(Text, default="", server_default="")
    criado_em: Mapped[datetime | None] = mapped_column(DateTime)
    criado_por: Mapped[str] = mapped_column(String(120), default="", server_default="")
    relatorio_anexo_id: Mapped[int | None] = mapped_column(ForeignKey("anexos.id", ondelete="SET NULL"))


class CargaTTLote(Base):
    __tablename__ = "cargas_tt_lotes"
    __table_args__ = (UniqueConstraint("carga_id", "lote_id", name="uq_cargas_tt_lotes"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    carga_id: Mapped[int] = mapped_column(ForeignKey("cargas_tt.id"), index=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


# ---------------------------------------------------------------- envios a prestador externo


class EnvioPrestador(Base):
    """Saída de lotes ou corpos de prova para laboratório/revestidor (ou vinda do inspetor de NDT)."""

    __tablename__ = "envios_prestador"
    __table_args__ = (CheckConstraint(_em(STATUS_ENVIO, "status"), name="ck_envios_prestador_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(20), unique=True)
    prestador: Mapped[str] = mapped_column(String(160), default="", server_default="")
    tipo_servico: Mapped[str] = mapped_column(String(60), default="", server_default="")
    data_emissao: Mapped[date | None] = mapped_column(Date)
    data_envio: Mapped[date | None] = mapped_column(Date)
    data_retorno: Mapped[date | None] = mapped_column(Date)
    responsavel: Mapped[str] = mapped_column(String(120), default="", server_default="")
    status: Mapped[str] = mapped_column(String(12), default="enviado", server_default="enviado", index=True)
    observacoes: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Especificação aplicável "congelada" no momento do envio
    spec_snapshot: Mapped[dict | list | None] = mapped_column(Json)
    qtd_cps: Mapped[str] = mapped_column(String(40), default="", server_default="")
    qtd_cp_tracao: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qtd_cp_impacto: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    criado_em: Mapped[datetime | None] = mapped_column(DateTime)
    criado_por: Mapped[str] = mapped_column(String(120), default="", server_default="")


class EnvioPrestadorLote(Base):
    __tablename__ = "envios_prestador_lotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    envio_id: Mapped[int] = mapped_column(ForeignKey("envios_prestador.id"), index=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qt_cp_tracao: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qt_cp_impacto: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qt_liberar: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    volumes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    peso_liq: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0, server_default="0")
    peso_bruto: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0, server_default="0")


class EnvioPrestadorFoto(Base):
    __tablename__ = "envios_prestador_fotos"

    id: Mapped[int] = mapped_column(primary_key=True)
    envio_id: Mapped[int] = mapped_column(ForeignKey("envios_prestador.id"), index=True)
    nome: Mapped[str] = mapped_column(String(255))
    arquivo: Mapped[str] = mapped_column(String(400))  # caminho dentro da pasta de arquivos
    quando: Mapped[datetime | None] = mapped_column(DateTime)
    legenda: Mapped[str] = mapped_column(String(200), default="", server_default="")


# ---------------------------------------------------------------- ordem de faturamento (saída física)


class OrdemFaturamento(Base):
    __tablename__ = "ordens_faturamento"
    __table_args__ = (CheckConstraint(_em(STATUS_OF, "status"), name="ck_ordens_faturamento_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(20), unique=True)
    data_emissao: Mapped[date | None] = mapped_column(Date)
    cliente: Mapped[str] = mapped_column(String(160), default="", server_default="")
    pedido_cliente: Mapped[str] = mapped_column(String(60), default="", server_default="")
    piv: Mapped[str] = mapped_column(String(40), default="", server_default="")
    nf_saida: Mapped[str] = mapped_column(String(40), default="", server_default="")
    destinatario: Mapped[str] = mapped_column(String(300), default="", server_default="")
    observacoes: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(12), default="rascunho", server_default="rascunho", index=True)
    criado_em: Mapped[datetime | None] = mapped_column(DateTime)
    criado_por: Mapped[str] = mapped_column(String(120), default="", server_default="")


class OrdemFaturamentoLote(Base):
    __tablename__ = "ordens_faturamento_lotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ordem_faturamento_id: Mapped[int] = mapped_column(ForeignKey("ordens_faturamento.id"), index=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    qtd_faturada: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    volumes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ordem: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    peso_liq: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0, server_default="0")
    peso_bruto: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0, server_default="0")


# ---------------------------------------------------------------- databooks enviados ao cliente (documental)


class DatabookEnviado(Base):
    """Histórico de databooks mandados ao cliente ("Enviado-DB"). Não é a saída física do lote."""

    __tablename__ = "databooks_enviados"

    id: Mapped[int] = mapped_column(primary_key=True)
    op: Mapped[str] = mapped_column(String(20), default="", server_default="", index=True)
    tipo: Mapped[str] = mapped_column(String(3), default="", server_default="")
    lote: Mapped[str] = mapped_column(String(40), default="", server_default="")
    revisao: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    arquivo: Mapped[str] = mapped_column(String(255), default="", server_default="")  # nome do PDF
    caminho: Mapped[str] = mapped_column(String(400), default="", server_default="")  # dentro da pasta de arquivos
    data_envio: Mapped[date | None] = mapped_column(Date)
    destinatario: Mapped[str] = mapped_column(String(300), default="", server_default="")
    nf_saida: Mapped[str] = mapped_column(String(40), default="", server_default="")
    observacoes: Mapped[str] = mapped_column(Text, default="", server_default="")
    enviado_em: Mapped[datetime | None] = mapped_column(DateTime)
    enviado_por: Mapped[str] = mapped_column(String(120), default="", server_default="")
