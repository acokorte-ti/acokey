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
  /** Como a OP entrou: digitada, pela planilha (ou carga do sistema antigo) ou pela busca no Mega. */
  origem: 'manual' | 'planilha' | 'mega';
  /** Situação da OP no Mega (AB aberta, EN encerrada, CA cancelada...). */
  situacao_op: string | null;
  /** Última vez que a OP veio do Mega (data de sistema, com fuso). */
  sincronizado_em: string | null;
  /** Retrato do Mega na última busca, só como referência. */
  dados_mega: DadosMega | null;
}

export interface NotaFiscalMega {
  nf: string;
  /** AAAA-MM-DD */
  data: string | null;
  qtd: number;
}

export interface DadosMega {
  coditem: string;
  descricao: string;
  cliente: string;
  /** Quantidade da OP no Mega (a do lote pode ser menor). */
  qtde: number | null;
  /** Pedido de venda para o qual a OP foi aberta. Nem sempre é o pedido do faturamento (PIV). */
  pedido_origem: string | null;
  /** Pedido de onde vieram as notas: o PIV digitado ou, sem ele, o de origem. */
  pedido_notas: string | null;
  notas_do_piv: boolean;
  po: string;
  /** Notas de saída do item nesse pedido. */
  notas: NotaFiscalMega[];
  /** OPs do mesmo item nesse pedido. Mais de uma: não dá para saber qual nota é de cada OP. */
  ops_mesmo_pedido: number;
}

/** Campos que só a busca no Mega preenche (não vão no formulário). */
type CamposDoMega = 'origem' | 'situacao_op' | 'sincronizado_em' | 'dados_mega';

export type OrdemEntrada = Omit<OrdemProducao, 'id' | 'lotes' | 'tipo' | CamposDoMega> & { tipo: string | null };

export interface BuscaMega {
  quando: string | null;
  /** Login de quem buscou, ou "(agendador)". */
  por: string;
  erro: string | null;
  lidas: number | null;
  novas: number | null;
  atualizadas: number | null;
  /** OPs em que o cadastro tem item, descrição ou tipo diferente do Mega (não alterados). */
  divergentes: number | null;
  ops_divergentes: string[];
}

export interface SituacaoMega {
  pronto: boolean;
  motivo: string;
  ultima: BuscaMega | null;
}

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
