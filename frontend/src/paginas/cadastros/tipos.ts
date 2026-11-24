/** Formatos da API de cadastros (espelham backend/app/api_cadastros.py e ordens_producao.py). */
import type { TipoLote } from '../../lib/tipos';

export interface Equipamento {
  id: number;
  codigo: string;
  descricao: string;
  setor: string;
  marca: string;
  /** "AAAA-MM-DD" */
  data_calibracao: string | null;
  validade_calibracao: string | null;
  certificado: string;
  empresa_calibracao: string;
  ativo: boolean;
  /** Validade da calibração já passou. */
  vencido: boolean;
  /** Vence nos próximos 30 dias. */
  vence_logo: boolean;
  dias_para_vencer: number | null;
}

export interface Prestador {
  id: number;
  codigo: string;
  razao_social: string;
  tipo_servico: string;
  contato: string;
  observacoes: string;
  ativo: boolean;
}

export interface FornecedorMP {
  id: number;
  codigo: string;
  razao_social: string;
  materiais: string;
  contato: string;
  observacoes: string;
  ativo: boolean;
}

/** GET /cadastros/listas */
export interface ListasFixas {
  tipos_prestador: string[];
  materiais_mp: string[];
}

export interface OrdemProducao {
  id: number;
  op: string;
  cliente: string;
  coditem: string;
  descricao: string;
  tipo: TipoLote | null;
  data_faturamento: string | null;
  nf: string;
  /** Coluna "Pedido" da planilha. */
  piv: string;
  qt_lote: number | null;
  qt_faturada: number | null;
  projeto: string;
  /** Pedido do cliente. */
  po: string;
  /** Lotes (não cancelados) com esta OP. */
  lotes: number;
}

export type OrdemEntrada = Omit<OrdemProducao, 'id' | 'lotes' | 'tipo'> & { tipo: string | null };

export interface OpNova {
  op: string;
  cliente: string;
  coditem: string;
  descricao: string;
  tipo: TipoLote | null;
  qt_lote: number | null;
  projeto: string;
}

/** POST /ordens-producao/importacao/comparar */
export interface Comparacao {
  arquivo: string;
  total_planilha: number;
  avisos: string[];
  novas: OpNova[];
  /** Diferenças por coluna da planilha: [no cadastro, na planilha]. */
  alteradas: { op: string; diferencas: Record<string, [string, string]> }[];
  /** OPs do cadastro que não vieram na planilha. */
  ausentes: string[];
  iguais: number;
}

export interface Parametro {
  chave: string;
  valor: string;
  padrao: string;
  descricao: string;
  /** Está na lista de parâmetros conhecidos do sistema. */
  conhecido: boolean;
  /** O valor que os documentos usam (o gravado ou, se vazio, o padrão). */
  em_uso: string;
  alterado_em: string | null;
  alterado_por: string;
}
