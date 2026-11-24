/** Formatos da API de matéria-prima (espelham backend/app/api_materia_prima.py). */
import type { TipoLote } from '../../lib/tipos';

export type StatusCorrida = 'pendente' | 'aprovada' | 'reprovada';

export interface Quantidades {
  qt_fund: number;
  qt_real: number;
  qt_ok: number;
  qt_rej: number;
  qt_retrab: number;
  qt_cp_tt: number;
}

/** Corrida com os cálculos do sistema antigo (_mp_calcular). */
export interface Corrida extends Quantidades {
  id: number;
  nf_entrada: string;
  corrida: string;
  fornecedor: string;
  /** Pode vir vazio em corrida antiga. */
  tipo_destino: TipoLote | '';
  /** "AAAA-MM-DD" */
  data_recebimento: string | null;
  observacoes: string;
  /** Data e hora local da fábrica, sem fuso. */
  criado_em: string | null;
  responsavel: string;
  status: StatusCorrida;
  aprovado_por: string;
  aprovado_em: string | null;
  obs_aprovacao: string;
  pct_refugo: number;
  pct_retrab: number;
  pct_aprov: number;
  rendimento: number;
  /** QT-OK menos os corpos de prova. */
  qt_disponivel: number;
  /** Soma das quantidades dos lotes que usam a corrida. */
  qt_consumida: number;
  qt_saldo: number;
}

export interface CorridaNaLista extends Corrida {
  lotes_usando: number;
  /** Tem certificado carimbado APROVADO neste sistema. */
  tem_carimbado: boolean;
}

export interface SugestaoFornecedor {
  valor: string;
  /** Razão social do cadastro (vazio para nomes já usados nas corridas). */
  rotulo: string;
}

/** GET /materia-prima */
export interface ListaCorridas {
  itens: CorridaNaLista[];
  fornecedores: SugestaoFornecedor[];
  /** A busca no Mega está ligada no servidor (mostra o botão "Buscar no Mega"). */
  mega: boolean;
}

/** Item de nota de entrada de peças fundidas lido no Mega, com o que já foi lançado aqui. */
export interface EntradaMega {
  chave: string;
  nf: string;
  /** Data de entrada no Mega (AAAA-MM-DD): é a data de recebimento da corrida. */
  entrada: string | null;
  emissao: string | null;
  /** Razão social no Mega. */
  fornecedor: string;
  /** Nome que a Qualidade já usa para esse fornecedor (ou o código do cadastro). */
  fornecedor_sugerido: string;
  descricao: string;
  tipo: TipoLote | null;
  unidade: string;
  qtde: number | null;
  /** Soma da QT-FUND. das corridas já lançadas com a mesma NF, data e tipo. */
  lancado: number;
  falta: number;
  corridas: { id: number; corrida: string }[];
}

export interface AnexoCorrida {
  id: number;
  nome: string;
  quando: string | null;
  pdf: boolean;
  carimbado: boolean;
}

export interface LoteDaCorrida {
  id: number;
  numero: string;
  op: string;
  tipo: TipoLote;
  qtd: number;
  criado_em: string | null;
  concluido: boolean;
  /** Etapa atual (nome curto); null quando concluído. */
  etapa: string | null;
}

export interface LoteVinculavel {
  id: number;
  numero: string;
  op: string;
  qtd: number;
  corrida: string;
}

export interface OpDoTipo {
  op: string;
  coditem: string;
  descricao: string;
  qt_lote: number | null;
}

/** GET /materia-prima/{id} */
export interface DetalheCorrida {
  corrida: Corrida;
  anexos: AnexoCorrida[];
  lotes: LoteDaCorrida[];
  vinculaveis: LoteVinculavel[];
  /** OPs do cadastro do mesmo tipo da corrida (sugestões do "criar lote"). */
  ops: OpDoTipo[];
  /** O usuário logado tem assinatura digital (o carimbo precisa dela). */
  tenho_assinatura: boolean;
  /** Sugestões para o campo Fornecedor (edição). */
  fornecedores: SugestaoFornecedor[];
}

/** Corpo de POST /materia-prima e PUT /materia-prima/{id}. */
export interface CorridaEntrada extends Quantidades {
  nf_entrada: string;
  corrida: string;
  fornecedor: string;
  tipo_destino: string;
  data_recebimento: string | null;
  observacoes: string;
}

export interface RespostaMensagem {
  mensagem: string;
}

export interface RespostaCarimbo extends RespostaMensagem {
  anexo_id: number;
  nome: string;
  corrida_aprovada: boolean;
  lotes_atualizados: number;
}

export interface RespostaLoteCriado extends RespostaMensagem {
  lote_id: number;
  numero: string;
  certificados: number;
}
