"""Fluxo de produção das chavetas: etapas, quais se aplicam a cada tipo e quando o lote pode avançar.

Regras trazidas do sistema antigo (legado/app.py: ETAPAS, etapa_aplicavel, subs_aplicaveis, etapa_real,
pode_avancar, _nc_libera_avanco, _nc_pendente_etapa). As funções daqui são puras: recebem o estado já
lido do banco (ver estado.py), para poderem ser testadas sem banco.

Etapa OPCIONAL para um tipo (ex.: dureza e usinagem no ARK, pedido da Qualidade em 25/11/2026): aparece no lote e
aceita registros, relatórios e anexos (que entram no databook), mas não trava o avanço nem conta no progresso.

Regra central: um lote só avança quando TODOS os sub-registros aplicáveis da etapa estão aprovados.
Uma reprovação bloqueia até a não conformidade ligada a ela ser encerrada como sucata, uso como está
ou anulada. Retrabalho NÃO libera: o lote só segue quando um novo registro da mesma etapa é aprovado.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.models import TIPOS_LOTE

TODOS = frozenset(TIPOS_LOTE)
SUB_NOME = {"": "", "tracao": "Ensaio de tração", "charpy": "Ensaio de impacto Charpy"}
# Disposições de NC que liberam o avanço mesmo com o registro original reprovado
DISPOSICOES_QUE_LIBERAM = frozenset({"sucata", "uso_como_esta", "anulada"})
NC_EM_ABERTO = frozenset({"aberta", "em_tratamento"})


@dataclass(frozen=True, eq=False)
class Etapa:
    chave: str
    nome: str
    curto: str
    setor: str
    formulario: str  # qual formulário de registro a etapa usa no sistema antigo
    exige_anexo: bool  # precisa de documento anexado para aprovar pelo atalho "por anexo"
    relatorio: str
    tipos: frozenset[str] = TODOS
    subs: tuple[str, ...] = ("",)
    subs_por_tipo: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    nome_por_tipo: Mapping[str, str] = field(default_factory=dict)
    curto_por_tipo: Mapping[str, str] = field(default_factory=dict)
    relatorio_por_tipo: Mapping[str, str] = field(default_factory=dict)
    curto_gantt: str = ""
    opcional_para: frozenset[str] = frozenset()  # tipos em que a etapa pode ser feita, sem travar o lote

    def aplicavel(self, tipo: str) -> bool:
        """Obrigatória para o tipo: entra no fluxo (avanço, progresso, etapa atual)."""
        return tipo in self.tipos

    def opcional(self, tipo: str) -> bool:
        return tipo in self.opcional_para and tipo not in self.tipos

    def abrivel(self, tipo: str) -> bool:
        """Aparece no lote e aceita registros e anexos: obrigatória ou opcional para o tipo."""
        return self.aplicavel(tipo) or self.opcional(tipo)

    def subs_de(self, tipo: str) -> tuple[str, ...]:
        return self.subs_por_tipo.get(tipo, self.subs)

    def nome_de(self, tipo: str) -> str:
        return self.nome_por_tipo.get(tipo) or self.nome

    def curto_de(self, tipo: str) -> str:
        return self.curto_por_tipo.get(tipo) or self.curto

    def relatorio_de(self, tipo: str) -> str:
        return self.relatorio_por_tipo.get(tipo) or self.relatorio


# A ordem desta lista é a ordem do processo. lotes.etapa guarda o índice aqui (não mude a ordem).
ETAPAS: tuple[Etapa, ...] = (
    Etapa("receb_mp", "Recebimento de matéria-prima e inspeção de recebimento", "Receb. MP",
          "Inspeção de recebimento", "quimica", True,
          "Inspeção de Recebimento - Composição Química da Matéria-Prima"),
    Etapa("trat_termico", "Tratamento térmico", "Trat. térmico", "Tratamento térmico", "tt", False,
          "Relatório de Tratamento Térmico"),
    Etapa("dureza", "Ensaio de dureza HRC", "Dureza HRC", "Controle de qualidade", "dureza", False,
          "Relatório de Ensaio de Dureza (HRC)", tipos=frozenset({"PIN", "BOX"}), opcional_para=frozenset({"ARK"})),
    Etapa("lab_ext", "Ensaios de tração e impacto Charpy", "Tração / Charpy", "Laboratório externo", "lab", True, "",
          subs=("tracao", "charpy"), subs_por_tipo={"ARK": ("charpy",)},
          curto_por_tipo={"ARK": "Charpy"}, nome_por_tipo={"ARK": "Ensaio mecânico - Charpy"}),
    Etapa("usinagem", "Usinagem do perfil e controle dimensional", "Usinagem", "Usinagem", "dim", False,
          "Relatório de Controle Dimensional (em processo)", tipos=frozenset({"PIN", "BOX"}),
          opcional_para=frozenset({"ARK"})),
    Etapa("dim_final", "Inspeção dimensional final", "Dimensional final", "Controle de qualidade", "dim", False,
          "Relatório de Inspeção Dimensional Final"),
    Etapa("lp", "Ensaio NDT - líquido penetrante (trincas)", "Líq. penetrante", "Laboratório interno", "lp", False,
          "Relatório de Ensaio por Líquido Penetrante"),
    Etapa("tambor", "Acabamento em tamboreamento", "Tamboreamento", "Acabamento", "simples", False,
          "Registro de Tamboreamento", tipos=frozenset({"PIN", "BOX"})),
    Etapa("fosfato", "Revestimento fosfato de manganês / Oxidação Negra", "Fosfato Mn", "Operação externa", "fosfato", True,
          "Registro de Revestimento - Fosfato de Manganês",
          nome_por_tipo={"ARK": "Revestimento - Oxidação Negra"}, curto_por_tipo={"ARK": "Oxidação Negra"},
          relatorio_por_tipo={"ARK": "Certificado de Revestimento - Oxidação Negra"},
          curto_gantt="Fosfato Mn / Oxid. Negra"),
    Etapa("visual", "Inspeção visual e gravação a laser", "Visual / Laser", "Controle de qualidade", "visual", False,
          "Relatório de Inspeção Visual e Marcação a Laser"),
    Etapa("embalagem", "Embalagem e parafusos M6x1", "Embalagem", "Expedição", "embalagem", False,
          "Registro de Embalagem",
          nome_por_tipo={"ARK": "Embalagem e parafusos M10x10mm / M10x12mm"},
          relatorio_por_tipo={"ARK": "Registro de Embalagem - Parafusos M10x10mm / M10x12mm"}),
)  # fmt: skip
POR_CHAVE: dict[str, Etapa] = {e.chave: e for e in ETAPAS}
INDICE: dict[str, int] = {e.chave: i for i, e in enumerate(ETAPAS)}
CONCLUIDO = len(ETAPAS)


@dataclass(frozen=True)
class SituacaoSub:
    """O que o banco diz de um sub-registro: o último registro NÃO anulado e a NC mais recente dele."""

    registro_status: str | None = None  # None = nenhum registro ainda
    nc_status: str | None = None
    nc_disposicao: str | None = None

    @property
    def resolvida(self) -> bool:
        if self.registro_status == "aprovado":
            return True
        return (
            self.registro_status == "reprovado"
            and self.nc_status == "encerrada"
            and self.nc_disposicao in DISPOSICOES_QUE_LIBERAM
        )

    @property
    def nc_pendente(self) -> bool:
        """Reprovado com NC ainda em aberto. Registro reprovado antigo, de antes das NCs existirem, também conta."""
        return self.registro_status == "reprovado" and (self.nc_status is None or self.nc_status in NC_EM_ABERTO)


# (chave da etapa, sub) -> situação. Ausente = sem registro.
Estado = Mapping[tuple[str, str], SituacaoSub]
_SEM_REGISTRO = SituacaoSub()


def situacao_sub(estado: Estado, etapa: Etapa, sub: str) -> SituacaoSub:
    return estado.get((etapa.chave, sub), _SEM_REGISTRO)


def etapa_resolvida(etapa: Etapa, tipo: str, estado: Estado) -> bool:
    return all(situacao_sub(estado, etapa, s).resolvida for s in etapa.subs_de(tipo))


def etapa_real(tipo: str, estado: Estado) -> int:
    """Índice da primeira etapa APLICÁVEL ainda não resolvida; CONCLUIDO se todas estão.

    É o estado verdadeiro do lote, calculado pelos registros (o cursor lotes.etapa pode estar atrasado).
    """
    for indice, etapa in enumerate(ETAPAS):
        if etapa.aplicavel(tipo) and not etapa_resolvida(etapa, tipo, estado):
            return indice
    return CONCLUIDO


def pode_avancar(cursor: int, tipo: str, estado: Estado) -> bool:
    """Se o cursor do lote (lotes.etapa) pode andar uma posição."""
    if cursor >= CONCLUIDO:
        return False
    etapa = ETAPAS[cursor]
    if not etapa.aplicavel(tipo):
        return True  # etapa que não se aplica ao tipo: passa direto
    return etapa_resolvida(etapa, tipo, estado)


def nc_pendente_etapa(etapa: Etapa, tipo: str, estado: Estado) -> bool:
    return any(situacao_sub(estado, etapa, s).nc_pendente for s in etapa.subs_de(tipo))


def situacao_etapa(indice: int, tipo: str, estado: Estado, indice_real: int) -> str:
    """aprovada | reprovada | atual | futura | opcional | nao_aplicavel — para as telas."""
    etapa = ETAPAS[indice]
    if not etapa.abrivel(tipo):
        return "nao_aplicavel"
    if etapa_resolvida(etapa, tipo, estado):
        return "aprovada"
    if any(situacao_sub(estado, etapa, s).registro_status == "reprovado" for s in etapa.subs_de(tipo)):
        return "reprovada"
    if etapa.opcional(tipo):
        return "opcional"
    return "atual" if indice == indice_real else "futura"


def progresso(tipo: str, estado: Estado) -> tuple[int, int]:
    """(etapas aplicáveis resolvidas, total de etapas aplicáveis)."""
    aplicaveis = [e for e in ETAPAS if e.aplicavel(tipo)]
    return sum(1 for e in aplicaveis if etapa_resolvida(e, tipo, estado)), len(aplicaveis)
