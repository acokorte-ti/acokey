/** Formatos da API das cargas de tratamento térmico (backend/app/api_cargas_tt.py). */
import type { TipoLote } from '../../lib/tipos';
import type { Equipamento } from '../relatorios/tipos';

export type StatusCarga = 'planejada' | 'em_andamento' | 'concluida' | 'cancelada';
export type Aba = 'ativas' | 'concluidas' | 'canceladas';

export interface LoteNaCarga {
  id: number;
  numero: string;
  op: string;
  tipo: TipoLote;
  qtd: number;
}

export interface CargaResumo {
  id: number;
  numero: string;
  status: StatusCarga;
  /** "AAAA-MM-DD" */
  data_planejada: string | null;
  /** Data e hora local da fábrica, sem fuso. */
  data_inicio: string | null;
  data_fim: string | null;
  forno_tempera_codigo: string;
  forno_revenimento_codigo: string;
  forno_tempera_desc: string;
  forno_revenimento_desc: string;
  observacoes: string;
  criado_em: string | null;
  criado_por: string;
  cancelado_em: string | null;
  cancelado_por: string;
  cancelado_motivo: string;
  n_lotes: number;
  total_pecas: number;
  lotes: LoteNaCarga[];
}

export interface ListaCargas {
  itens: CargaResumo[];
  contagens: Record<Aba, number>;
}

export interface LoteDaCarga extends LoteNaCarga {
  corrida: string;
  cliente: string;
  cancelado: boolean;
  tt_aprovado: boolean;
  etapa_atual: string;
}

export interface CargaDetalhe extends Omit<CargaResumo, 'lotes'> {
  lotes: LoteDaCarga[];
  relatorio: { anexo_id: number; nome: string; lote_id: number } | null;
}

export interface LoteDisponivel extends LoteNaCarga {
  corrida: string;
  cliente: string;
  aguardando_tt: boolean;
  /** Em quantas OUTRAS cargas não canceladas o lote já está. */
  em_cargas: number;
}

export interface FormularioCarga {
  numero_previsto: string;
  carga: CargaResumo | null;
  lote_ids: number[];
  fornos_tempera: Equipamento[];
  fornos_revenimento: Equipamento[];
  forno_tempera_padrao: string;
  forno_revenimento_padrao: string;
  disponiveis: LoteDisponivel[];
  hoje: string;
}

export interface RespostaCarga {
  id: number;
  numero: string;
  aviso: string;
  mensagem: string;
}

/** GET /recursos/instrucoes: instruções de trabalho da Qualidade (PDF). */
export interface Instrucao {
  nome: string;
  arquivo: string;
  tamanho_kb: number;
}
