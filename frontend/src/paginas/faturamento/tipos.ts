/** Formatos da API da ordem de faturamento (backend/app/api_faturamento.py). */
import type { TipoLote } from '../../lib/tipos';

export type StatusOF = 'rascunho' | 'emitida' | 'faturada' | 'cancelada';
export type AbaOF = 'ativas' | 'faturadas' | 'canceladas';

export interface OFResumo {
  id: number;
  numero: string;
  status: StatusOF;
  cliente: string;
  pedido_cliente: string;
  piv: string;
  data_emissao: string | null;
  nf_saida: string;
  n_lotes: number;
  total_pecas: number;
  total_volumes: number;
  lotes: { id: number; op: string; tipo: TipoLote; numero: string }[];
}

/** GET /faturamento?aba= */
export interface ListaOFs {
  itens: OFResumo[];
  contagens: Record<AbaOF, number>;
}

/** GET /faturamento/opcoes */
export interface OpcoesOF {
  numero_previsto: string;
  hoje: string;
  /** Nome curto do cliente (parâmetro), só para o exemplo do campo. */
  cliente_exemplo: string;
}

/** GET /faturamento/lotes-disponiveis */
export interface LoteParaFaturar {
  id: number;
  op: string;
  tipo: TipoLote;
  numero: string;
  qtd: number;
  coditem: string;
  descricao: string;
  cliente: string;
  piv: string;
  pedido_cliente: string;
  /** "26-4-900001" */
  lote_completo: string;
  /** "26-4-900001 (72 Peças)" */
  lote_com_qtd: string;
  /** Vazio = pronto para faturar. */
  motivos: string[];
  pronto: boolean;
  /** Já está em outra OF emitida ou faturada. */
  ja_faturado: boolean;
}

export interface ItemOF {
  lote_id: number;
  op: string;
  tipo: TipoLote;
  numero: string;
  lote_completo: string;
  lote_com_qtd: string;
  coditem: string;
  descricao: string;
  qtd: number;
  qtd_faturada: number;
  volumes: number;
  peso_liq: number;
  peso_bruto: number;
}

/** GET /faturamento/{id} */
export interface OFDetalhe {
  id: number;
  numero: string;
  status: StatusOF;
  data_emissao: string | null;
  cliente: string;
  pedido_cliente: string;
  piv: string;
  nf_saida: string;
  destinatario: string;
  observacoes: string;
  criado_em: string | null;
  criado_por: string;
  cancelado_em: string | null;
  cancelado_por: string;
  cancelado_motivo: string;
  itens: ItemOF[];
  totais: { qtd: number; qtd_faturada: number; volumes: number; peso_liq: number; peso_bruto: number };
  /** Rascunho ou emitida (faturada fica travada). */
  pode_editar: boolean;
  /** Situações para onde a OF pode ir agora. */
  proximos: StatusOF[];
}

/** O que se digita por lote na tabela "Peças por OP" (guardado mesmo se o lote for desmarcado). */
export interface DadosLoteOF {
  qtd_faturada: string;
  volumes: string;
  peso_liq: string;
  peso_bruto: string;
  /** Nº do lote como aparece no campo (começa com o número completo). */
  numero: string;
}

/** Corpo de POST /faturamento e PUT /faturamento/{id} */
export interface OFEntrada {
  data_emissao: string | null;
  cliente: string;
  pedido_cliente: string;
  piv: string;
  nf_saida: string;
  destinatario: string;
  observacoes: string;
  itens: {
    lote_id: number;
    qtd_faturada: number | null;
    volumes: number;
    peso_liq: string;
    peso_bruto: string;
    numero_corrigido: string | null;
  }[];
}
