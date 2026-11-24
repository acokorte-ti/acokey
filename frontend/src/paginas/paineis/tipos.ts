/** Formatos devolvidos pela API dos painéis (backend/app/api_paineis.py). */
import type { TipoLote } from '../../lib/tipos';

/** Mês atual contra o anterior. */
export interface Variacao {
  atual: number;
  anterior: number;
  sentido: 'subiu' | 'caiu' | 'igual' | 'novo';
  /** "+20%", "-15%", "0%" ou "novo este mês". */
  rotulo: string;
  pct: number | null;
}

/** null = nada nos dois meses (não mostra tendência). */
export interface Tendencias {
  concluidos: Variacao | null;
  enviados: Variacao | null;
  pin: Variacao | null;
  box: Variacao | null;
  ark: Variacao | null;
}

export interface Totais {
  lotes: number;
  pecas: number;
  andamento: number;
  pecas_andamento: number;
  /** Concluídos que ainda não tiveram o databook enviado. */
  concluidos: number;
  pecas_concluidos: number;
  /** Concluídos com databook enviado ao cliente (Enviado-DB). */
  enviados: number;
  pecas_enviados: number;
  pin: number;
  box: number;
  ark: number;
  pecas_pin: number;
  pecas_box: number;
  pecas_ark: number;
  pin_enviados: number;
  box_enviados: number;
  ark_enviados: number;
  pin_ativos: number;
  box_ativos: number;
  ark_ativos: number;
}

export type Situacao = 'andamento' | 'concluido' | 'enviado';

export interface OpCadastro {
  op: string;
  tipo: string;
  coditem: string;
  descricao: string;
}

export interface ItemFunil {
  nome: string;
  lotes: number;
  pecas: number;
}

export interface ItemFunilTipo {
  nome: string;
  pin: number;
  box: number;
  ark: number;
  pecas_pin: number;
  pecas_box: number;
  pecas_ark: number;
}

export interface Gargalo {
  setor: string;
  setor_completo: string;
  lotes: number;
  dias_medio: number;
}

export interface MesEnvios {
  /** "MM/AAAA" */
  mes: string;
  chave: string;
  enviados: number;
}

export interface MesPecas {
  mes: string;
  chave: string;
  pin: number;
  box: number;
  ark: number;
  total: number;
}

export interface ResumoKpis {
  funil: ItemFunil[];
  funil_tipo: ItemFunilTipo[];
  setores: Gargalo[];
  linha_do_tempo: MesEnvios[];
}

// ---------------------------------------------------------------- início

export interface CartaoInicio {
  chave: 'producao' | 'qualidade' | 'tt' | 'equipamentos' | 'cadastros';
  nome: string;
  texto: string;
  link: string;
  alerta: boolean;
}

export interface RespostaInicio {
  nome: string;
  mostrar_tutorial: boolean;
  cartoes: CartaoInicio[];
}

// ---------------------------------------------------------------- painel

export type NivelAlerta = 'erro' | 'alerta' | 'info' | 'ok';

export interface Pendencia {
  chave: string;
  nivel: NivelAlerta;
  texto: string;
  link: string;
  acao: string;
  quantidade: number;
}

export interface RespostaPainel {
  pendencias: Pendencia[];
  resumo: { total: number; andamento: number; concluidos: number; enviados: number; nc: number };
  enviados: { lote_ids: number[]; pecas: number; pin: number; box: number; ark: number };
  /** Lotes cuja etapa atual já está resolvida: podem avançar. */
  prontos: number[];
}

// ---------------------------------------------------------------- dashboard

export interface LoteDashboard {
  id: number;
  numero: string;
  op: string;
  tipo: TipoLote;
  qtd: number;
  coditem: string;
  descricao: string;
  setor: string;
  etapa: string;
  dias: number | null;
  situacao: Situacao;
  nc: boolean;
}

export interface RespostaDashboard {
  /** Setores na ordem do processo; "Concluído" e "Enviado-DB" por último. */
  setores: string[];
  lotes: LoteDashboard[];
  totais: Totais;
  tendencias: Tendencias;
  maior_qtd: number;
  ops: OpCadastro[];
  /** null para quem não vê os KPIs (só Qualidade ou Produção TT). */
  kpis: ResumoKpis | null;
}

// ---------------------------------------------------------------- Gantt

export type SituacaoCelula = 'aprovada' | 'reprovada' | 'atual' | 'pulada' | 'futura' | 'nao_iniciado' | 'na';

export interface LinhaGantt {
  op: string;
  tipo: TipoLote;
  coditem: string;
  descricao: string;
  qtd: number | null;
  lote: { id: number; numero: string } | null;
  situacao: Situacao | 'semlote';
  pct: number;
  celulas: { s: SituacaoCelula; rotulo: string }[];
}

export interface RespostaGantt {
  etapas: { chave: string; curto: string; nome: string }[];
  linhas: LinhaGantt[];
  totais: Totais & { ops: number; sem_lote: number };
  tendencias: Tendencias;
  ops: OpCadastro[];
}

// ---------------------------------------------------------------- KPIs

export type Periodo = 'tudo' | 'ano' | '12m' | '6m' | '3m';

export interface RespostaKpis extends ResumoKpis {
  periodo: Periodo;
  rotulo_periodo: string;
  tipo: TipoLote | 'todos';
  totais: Totais;
  tendencias: Tendencias;
  pecas_mes: MesPecas[];
  ano: number;
  soma_anual: { total: number; pin: number; box: number; ark: number };
  gerado_em: string;
}

// ---------------------------------------------------------------- indicadores

export interface Rendimento {
  corridas: number;
  qt_fund: number;
  qt_real: number;
  qt_ok: number;
  qt_rej: number;
  qt_retrab: number;
  pct_refugo: number;
  pct_retrab: number;
  pct_aprov: number;
  rendimento: number;
}

export interface CorridaIndicador extends Omit<Rendimento, 'corridas'> {
  id: number;
  nf_entrada: string;
  corrida: string;
  fornecedor: string;
  tipo_destino: string;
}

export interface RespostaIndicadores {
  total: number;
  geral: Rendimento;
  por_fornecedor: (Rendimento & { fornecedor: string })[];
  por_tipo: (Rendimento & { tipo: string })[];
  top_refugo: CorridaIndicador[];
}

// ---------------------------------------------------------------- busca

export interface ItemBusca {
  /** "op" = OP do cadastro ainda sem lote. */
  tipo: 'lote' | 'op';
  id: number | null;
  op: string;
  numero: string;
  formato: string;
  qtd: number | null;
  coditem: string;
  descricao: string;
  etapa: string;
  enviado: boolean;
  nc: boolean;
}

export interface RespostaBusca {
  total: number;
  itens: ItemBusca[];
}
