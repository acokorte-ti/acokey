/** Formatos devolvidos pela API (espelham o contrato do backend). */

export type Modulo = 'qualidade' | 'pcp' | 'producao_tt' | 'producao_usinagem' | 'cadastros';
export type TipoLote = 'PIN' | 'BOX' | 'ARK';

export interface Usuario {
  id: number;
  login: string;
  nome: string;
  cargo: string;
  ativo: boolean;
  trocar_senha: boolean;
  /** Administrador do sistema: cuida dos usuários e vê a auditoria. */
  admin: boolean;
  /** Módulos que o usuário acessa. */
  modulos: Modulo[];
  /** Pode assinar relatórios como "Aprovado por" e decidir desvios. */
  pode_aprovar: boolean;
  tem_assinatura: boolean;
  ultimo_login_em: string | null;
  bloqueado: boolean;
}

export interface RespostaSessao {
  usuario: Usuario;
  csrf: string;
}

/** Corpo de POST /usuarios. A senha é provisória: a pessoa troca no primeiro acesso. */
export interface UsuarioNovo {
  login: string;
  nome: string;
  cargo: string;
  senha: string;
  admin: boolean;
  modulos: Modulo[];
  pode_aprovar: boolean;
}

/** Corpo de PATCH /usuarios/{id}: só vai o que mudou. */
export interface UsuarioAlteracao {
  login?: string;
  nome?: string;
  cargo?: string;
  ativo?: boolean;
  admin?: boolean;
  modulos?: Modulo[];
  pode_aprovar?: boolean;
}

// ---------------------------------------------------------------- etapas e lotes

/** GET /etapas: as etapas do processo, na ordem. */
export interface Etapa {
  chave: string;
  nome: string;
  curto: string;
  setor: string;
  /** Tipos de chaveta que passam por esta etapa. */
  tipos: TipoLote[];
  exige_anexo: boolean;
}

export interface EtapaAtual {
  indice: number;
  chave: string;
  curto: string;
  setor: string;
}

export interface LoteResumo {
  id: number;
  numero: string;
  op: string;
  tipo: TipoLote;
  qtd: number;
  corrida: string;
  coditem: string;
  /** Data e hora local da fábrica, sem fuso: "AAAA-MM-DDTHH:MM:SS". */
  criado_em: string | null;
  etapa_desde: string | null;
  dias_na_etapa: number | null;
  /** Todas as etapas aplicáveis ao tipo estão aprovadas. */
  concluido: boolean;
  /** null quando o lote está concluído. */
  etapa_atual: EtapaAtual | null;
  /** Etapas aplicáveis ao tipo do lote. */
  progresso: { aprovadas: number; total: number };
  /** Tem não conformidade aberta ou em tratamento. */
  nc_aberta: boolean;
}

/** GET /lotes */
export interface ListaLotes {
  itens: LoteResumo[];
}

export type SituacaoEtapa = 'aprovada' | 'reprovada' | 'atual' | 'futura' | 'opcional' | 'nao_aplicavel';
export type StatusRegistro = 'aprovado' | 'reprovado' | 'pendente';
export type StatusNc = 'aberta' | 'em_tratamento' | 'encerrada';

export interface RegistroEtapa {
  id: number;
  status: StatusRegistro;
  quando: string | null;
  responsavel: string;
}

export interface SubEtapa {
  /** "" = etapa sem subdivisão; "tracao" | "charpy" no laboratório externo. */
  sub: string;
  nome: string;
  registro: RegistroEtapa | null;
}

export interface AnexoEtapa {
  id: number;
  sub: string;
  nome: string;
  quando: string | null;
  /** Evidência interna: não entra no databook do cliente. */
  apenas_registro: boolean;
}

export interface EtapaDoLote {
  chave: string;
  /** nome e curto já vêm resolvidos para o tipo do lote. */
  nome: string;
  curto: string;
  setor: string;
  aplicavel: boolean;
  /** Etapa que o tipo pode fazer sem travar o lote (ex.: dureza e usinagem no ARK). */
  opcional?: boolean;
  situacao: SituacaoEtapa;
  subs: SubEtapa[];
  anexos: AnexoEtapa[];
}

export interface EventoLote {
  quando: string | null;
  texto: string;
}

export interface NcDoLote {
  id: number;
  numero: string;
  etapa: string;
  sub: string;
  status: StatusNc;
  disposicao: string;
}

/** GET /lotes/{id} */
export interface LoteDetalhe {
  lote: LoteResumo;
  etapas: EtapaDoLote[];
  /** Mais recentes primeiro. */
  eventos: EventoLote[];
  ncs: NcDoLote[];
}

// ---------------------------------------------------------------- auditoria

export interface RegistroAuditoria {
  id: number;
  quando: string;
  login: string | null;
  acao: string;
  entidade: string | null;
  entidade_id: string | null;
  lote_id: number | null;
  detalhes: Record<string, unknown> | null;
  ip: string | null;
}

export interface ListaAuditoria {
  total: number;
  itens: RegistroAuditoria[];
}
