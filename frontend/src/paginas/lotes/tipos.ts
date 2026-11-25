/** Formatos da API do ciclo do lote (backend/app/api_lotes.py e api_etapas.py). */
import type { AnexoEtapa, EtapaDoLote, LoteDetalhe, StatusNc, StatusRegistro, TipoLote } from '../../lib/tipos';

// ---------------------------------------------------------------- página do lote

export interface NcPendente {
  id: number;
  numero: string;
  status: StatusNc;
}

export interface EtapaDoLoteCompleta extends EtapaDoLote {
  indice: number;
  /** Documentos que entram no databook (sem as fotos "só registro interno"). */
  n_documentos: number;
  /** NC ainda aberta do último registro reprovado da etapa. */
  nc_pendente: NcPendente | null;
}

export interface MateriaPrimaDoLote {
  id: number;
  corrida: string;
  nf_entrada: string;
  fornecedor: string;
  tipo_destino: string;
  status: 'pendente' | 'aprovada' | 'reprovada';
  qt_ok: number;
  pct_refugo: number;
  obs_aprovacao: string;
}

export interface CargaTTDoLote {
  id: number;
  numero: string;
  status: 'planejada' | 'em_andamento' | 'concluida' | 'cancelada';
  data_planejada: string | null;
}

export interface LinhaChecklist {
  prefixo: string;
  etapa: string;
  sub: string;
  curto: string;
  titulo: string;
}

/** GET /lotes/{id} (o contrato antigo, mais o que a página do lote precisa para registrar). */
export interface LoteDetalheCompleto extends Omit<LoteDetalhe, 'etapas'> {
  etapas: EtapaDoLoteCompleta[];
  /** Cursor da etapa em que o lote foi deixado: "Concluir etapa atual" anda com ele. */
  cursor: number;
  cursor_curto: string | null;
  pode_avancar: boolean;
  /** Já tem registro ou anexo: editar e cancelar exigem quem pode aprovar, com motivo. */
  tem_dados: boolean;
  databook_enviado: boolean;
  materia_prima: MateriaPrimaDoLote | null;
  carga_tt: CargaTTDoLote | null;
  desenho: { coditem: string; descricao: string } | null;
  /** Arquivos importados sem prefixo do checklist: registro interno, fora do databook. */
  avulsos: AnexoEtapa[];
  importacao: { indice: string; checklist: LinhaChecklist[] };
  laser_disponivel: boolean;
}

export interface SugestaoOp {
  op: string;
  cliente: string;
  coditem: string;
  descricao: string;
  descricao_curta: string;
  tipo: TipoLote | null;
  qtd: number | null;
  /** Lotes (não cancelados) que já existem para a OP. */
  lotes: number;
}

export interface Desenho {
  coditem: string;
  descricao: string;
  arquivo: string;
}

// ---------------------------------------------------------------- página da etapa

export type Formulario = 'quimica' | 'tt' | 'dureza' | 'lab' | 'dim' | 'lp' | 'simples' | 'fosfato' | 'visual' | 'embalagem';

export interface RegistroDaEtapa {
  id: number;
  sub: string;
  status: StatusRegistro;
  quando: string | null;
  responsavel: string;
  anulado: boolean;
  anulado_motivo: string;
  /** formulario | documento_anexado | sem_documento | importacao | sistema (relatório gerado pelo sistema) */
  via: string;
  titulo: string;
  tem_relatorio: boolean;
  nc: { id: number; numero: string; status: StatusNc; disposicao: string } | null;
}

export interface Especificacao {
  dureza_min: number | null;
  dureza_max: number | null;
  tr_le_min: number | null;
  tr_le_max: number | null;
  tr_lr_min: number | null;
  tr_lr_max: number | null;
  tr_al_min: number | null;
  tr_ra_min: number | null;
  ch_med_min: number | null;
  ch_ind_min: number | null;
  ch_temp: string;
  ch_dim_cp: string;
}

export interface CotaCadastrada {
  id: number;
  descricao: string;
  nominal: string;
  tol_min: string;
  tol_max: string;
}

export interface EquipamentoCadastrado {
  codigo: string;
  descricao: string;
  setor: string;
  texto: string;
  validade: string | null;
  vencido: boolean;
}

export interface EnvioDaEtapa {
  id: number;
  numero: string;
  prestador: string;
  tipo_servico: string;
  status: 'enviado' | 'retornado' | 'cancelado';
  data_envio: string | null;
  data_retorno: string | null;
  responsavel: string;
  laudo_lancado: boolean;
}

export interface PaginaEtapaDados {
  lote: {
    id: number;
    numero: string;
    op: string;
    tipo: TipoLote;
    qtd: number;
    corrida: string;
    coditem: string;
    cursor: number;
    concluido: boolean;
  };
  etapa: {
    chave: string;
    indice: number;
    nome: string;
    curto: string;
    setor: string;
    formulario: Formulario;
    exige_anexo: boolean;
    relatorio: string;
    aplicavel: boolean;
    opcional?: boolean;
    situacao: string;
    subs: { sub: string; nome: string; status: StatusRegistro | null }[];
    /** O formulário detalhado só vale para etapa já liberada (o atalho por documento vale sempre). */
    liberada: boolean;
  };
  sub: string;
  pode_avancar: boolean;
  /** Do mais novo para o mais antigo. */
  registros: RegistroDaEtapa[];
  anexos: AnexoEtapa[];
  fotos_registro: AnexoEtapa[];
  espec: Especificacao | null;
  cotas: CotaCadastrada[];
  desenho: { coditem: string; descricao: string } | null;
  prestadores: { codigo: string; razao_social: string; tipo_servico: string }[];
  fornecedores_mp: { codigo: string; razao_social: string; materiais: string }[];
  rotulo_prestador: string;
  equipamentos: EquipamentoCadastrado[];
  corridas_mp: { corrida: string; nf_entrada: string; fornecedor: string; tipo_destino: string; status: string }[];
  certificados_corrida: number;
  envios: EnvioDaEtapa[];
  padroes: {
    ano: number;
    trimestre: number;
    laser_formato: string;
    laser_formato_legivel: string;
    elementos: string[];
    usuario: string;
    parafusos: string;
    ciclos_tt: string[];
  };
}

export interface RespostaRegistro {
  registro: RegistroDaEtapa;
  status: StatusRegistro;
  aviso: string | null;
  nc: { id: number; numero: string } | null;
  nc_encerrada: string | null;
}

// ---------------------------------------------------------------- mapa do lote

export interface LinhaMapa {
  etapa: string;
  sub: string;
  nome: string;
  setor: string;
  status: StatusRegistro;
  quando: string | null;
  responsavel: string;
  anexos: AnexoEtapa[];
}

export interface MapaDoLote {
  lote: { id: number; numero: string; op: string; tipo: TipoLote; qtd: number; corrida: string; coditem: string; criado_em: string | null };
  concluido: boolean;
  etapa_numero: number;
  total_etapas: number;
  linhas: LinhaMapa[];
  /** Do mais antigo para o mais novo. */
  eventos: { quando: string | null; texto: string }[];
}
