/** Formatos da API de envios a prestador externo (backend/app/api_envios.py). */
import type { TipoLote } from '../../lib/tipos';

export type StatusEnvio = 'enviado' | 'retornado' | 'cancelado';
export type AbaEnvios = 'ativos' | 'retornados' | 'cancelados';
/** cp = só corpos de prova (azul); interno = o laboratório vem à fábrica (verde); pecas = as peças saem (laranja). */
export type ClasseNatureza = 'cp' | 'interno' | 'pecas' | 'outro';

export interface Natureza {
  classe: ClasseNatureza;
  texto: string;
}

export interface TipoServico {
  valor: string;
  /** Revestimento, NDT e outro: qtd liberada, volumes e pesos por OP (em vez de CPs). */
  modo_pecas: boolean;
  natureza: Natureza;
  rotulo_fotos: string;
  /** Tipos do cadastro de prestadores que atendem este serviço; null = todos. */
  tipos_prestador: string[] | null;
  mostrar_tracao: boolean;
  mostrar_charpy: boolean;
}

export interface PrestadorOpcao {
  razao_social: string;
  codigo: string;
  tipo_servico: string;
}

/** GET /envios/opcoes */
export interface OpcoesEnvio {
  tipos: TipoServico[];
  prestadores: PrestadorOpcao[];
  /** Trecho do nome do laboratório do modelo .docx: já vem escolhido nos ensaios de tração. */
  prestador_preferido: string;
  norma_codigo: string;
  cliente_curto: string;
  numero_previsto: string;
  hoje: string;
  usuario: string;
}

export interface LoteDoEnvioResumo {
  id: number;
  op: string;
  tipo: TipoLote;
  numero: string;
  qtd: number;
}

export interface EnvioResumo {
  id: number;
  numero: string;
  prestador: string;
  tipo_servico: string;
  status: StatusEnvio;
  data_emissao: string | null;
  data_envio: string | null;
  data_retorno: string | null;
  responsavel: string;
  dias_envio: number;
  /** "enviado" há 10 dias ou mais sem retorno. */
  parado: boolean;
  n_lotes: number;
  total_pecas: number;
  lotes: LoteDoEnvioResumo[];
}

/** GET /envios?aba= */
export interface ListaEnvios {
  itens: EnvioResumo[];
  contagens: Record<AbaEnvios, number>;
  dias_alerta: number;
}

/** GET /envios/lotes-disponiveis */
export interface LoteDisponivel {
  id: number;
  op: string;
  tipo: TipoLote;
  numero: string;
  qtd: number;
  corrida: string;
  coditem: string;
  cliente: string;
  etapa_atual: string;
}

/** [rótulo, valor] */
export type LinhaEspecificacao = [string, string];

export interface EspecificacaoTipo {
  tipo: TipoLote;
  material: string;
  tracao: LinhaEspecificacao[];
  charpy: LinhaEspecificacao[];
  vazio: boolean;
}

/** GET /envios/especificacao */
export interface PreviaEspecificacao {
  tipos_pecas: TipoLote[];
  especificacao: EspecificacaoTipo[];
  norma_codigo: string;
}

export interface ItemEnvio {
  lote_id: number;
  op: string;
  tipo: TipoLote;
  numero: string;
  qtd: number;
  coditem: string;
  cliente: string;
  descricao: string;
  material: string;
  etapa_atual: string;
  cancelado: boolean;
  qt_cp_tracao: number;
  qt_cp_impacto: number;
  qt_liberar: number;
  volumes: number;
  peso_liq: number;
  peso_bruto: number;
  /** O laudo/retorno já foi lançado na etapa do lote. */
  retornou: boolean;
}

export interface FotoEnvio {
  id: number;
  nome: string;
  quando: string | null;
  legenda: string;
}

/** GET /envios/{id} */
export interface EnvioDetalhe extends EnvioResumo {
  observacoes: string;
  /** Anotação livre do sistema antigo ("Nota antiga"). */
  qtd_cps: string;
  qtd_cp_tracao: number;
  qtd_cp_impacto: number;
  criado_em: string | null;
  criado_por: string;
  cancelado_em: string | null;
  cancelado_por: string;
  cancelado_motivo: string;
  natureza: Natureza;
  rotulo_fotos: string;
  modo_pecas: boolean;
  mostrar_tracao: boolean;
  mostrar_charpy: boolean;
  itens: ItemEnvio[];
  totais: { qt_cp_tracao: number; qt_cp_impacto: number; qt_liberar: number; volumes: number; peso_liq: number; peso_bruto: number };
  todos_retornaram: boolean;
  etapa_referencia: string;
  /** Congelada no envio. */
  especificacao: EspecificacaoTipo[];
  norma_codigo: string;
  fotos: FotoEnvio[];
  /** O botão do modelo .docx do laboratório aparece. */
  modelo_ensaio: boolean;
  pode_editar: boolean;
}

/** Quantidades digitadas por lote (ficam guardadas mesmo se o lote for desmarcado e marcado de novo). */
export interface QuantidadesLote {
  qt_cp_tracao: string;
  qt_cp_impacto: string;
  qt_liberar: string;
  volumes: string;
  peso_liq: string;
  peso_bruto: string;
}

/** Corpo de POST /envios e PUT /envios/{id} */
export interface EnvioEntrada {
  tipo_servico: string;
  prestador: string;
  data_emissao: string | null;
  data_envio: string | null;
  responsavel: string;
  observacoes: string;
  itens: {
    lote_id: number;
    qt_cp_tracao: number;
    qt_cp_impacto: number;
    qt_liberar: number;
    volumes: number;
    peso_liq: string;
    peso_bruto: string;
  }[];
}

export interface RespostaGravacao {
  id: number;
  numero: string;
}
