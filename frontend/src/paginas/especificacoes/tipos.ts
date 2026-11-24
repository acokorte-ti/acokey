/** Formatos da API de especificações (backend/app/api_especificacoes.py). */
import type { TipoLote } from '../../lib/tipos';

/** Limites por tipo. Números vêm como texto com ponto ("39.5"); vazio = não cadastrado (nunca um valor inventado). */
export interface EspecificacaoTipo {
  tipo: TipoLote;
  cadastrada: boolean;
  dureza_min: string;
  dureza_max: string;
  tr_le_min: string;
  tr_le_max: string;
  tr_lr_min: string;
  tr_lr_max: string;
  tr_al_min: string;
  tr_ra_min: string;
  ch_temp: string;
  ch_med_min: string;
  ch_ind_min: string;
  ch_dim_cp: string;
}

export type CampoEspecificacao = Exclude<keyof EspecificacaoTipo, 'tipo' | 'cadastrada'>;

export interface Desenho {
  coditem: string;
  descricao: string;
  /** PIN, BOX, ARK ou "" (detectado pelo nome do desenho). */
  classificacao: TipoLote | '';
  n_cotas: number;
}

export interface ItemComCotas {
  coditem: string;
  n_cotas: number;
  descricao: string;
}

/** GET /especificacoes */
export interface TelaEspecificacoes {
  tipos: EspecificacaoTipo[];
  desenhos: Desenho[];
  itens: ItemComCotas[];
  pode_editar: boolean;
}

/** Cota dimensional: texto, exatamente como foi cadastrado. */
export interface Cota {
  id?: number;
  descricao: string;
  nominal: string;
  tol_min: string;
  tol_max: string;
}

/** GET /especificacoes/cotas/{coditem} */
export interface CotasDoItem {
  coditem: string;
  desenho: { descricao: string; classificacao: TipoLote | '' } | null;
  cotas: Cota[];
}

/** PUT /especificacoes/cotas */
export interface RespostaCotas {
  mensagem: string;
  coditem: string;
  cotas: Cota[];
}

/** PUT /especificacoes/tipos/{tipo} */
export interface RespostaTipo {
  mensagem: string;
  tipo: EspecificacaoTipo;
}
