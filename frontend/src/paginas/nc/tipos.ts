/** Formatos da API de não conformidades (backend/app/api_nc.py). */
import type { StatusNc, StatusRegistro, TipoLote } from '../../lib/tipos';

export type Disposicao = 'retrabalho' | 'sucata' | 'uso_como_esta' | 'anulada';
export type AbaNc = 'abertas' | 'encerradas';

export interface LoteDaNc {
  id: number;
  numero: string;
  op: string;
  tipo: TipoLote;
  qtd: number;
  coditem: string;
  cancelado: boolean;
}

export interface NaoConformidade {
  id: number;
  numero: string;
  status: StatusNc;
  etapa: string;
  sub: string;
  /** Nome curto da etapa, já resolvido para o tipo do lote. */
  etapa_nome: string;
  sub_nome: string;
  descricao: string;
  registro_id: number | null;
  qtd_lote_na_abertura: number;
  qtd_afetada: number;
  /** "" enquanto não foi decidida. */
  disposicao: Disposicao | '';
  disposicao_nome: string;
  justificativa: string;
  observacoes: string;
  /** Datas de produção: hora local, sem fuso. */
  aberta_em: string | null;
  aberta_por: string;
  decidida_em: string | null;
  decidida_por: string;
  encerrada_em: string | null;
  encerrada_por: string;
  lote: LoteDaNc | null;
}

/** GET /nao-conformidades?aba= */
export interface ListaNc {
  aba: AbaNc;
  contagens: Record<AbaNc, number>;
  itens: NaoConformidade[];
}

export interface RegistroDaNc {
  id: number;
  etapa: string;
  sub: string;
  status: StatusRegistro;
  quando: string | null;
  responsavel: string;
  anulado: boolean;
  anulado_motivo: string;
  anulado_em: string | null;
  anulado_por: string;
}

/** GET /nao-conformidades/{id} */
export interface DetalheNc extends NaoConformidade {
  registro: RegistroDaNc | null;
  /** Registro de dureza reprovado e não anulado: dá para corrigir os valores digitados. */
  corrigir_dureza_disponivel: boolean;
  pode_decidir_desvio: boolean;
}

/** POST /nao-conformidades/{id}/decidir e /reabrir */
export interface RespostaDecisao {
  mensagem: string;
  nc: DetalheNc;
}

export interface Leitura {
  cp: string;
  valores: number[];
  status: string;
}

/** GET /registros/{id}/corrigir-dureza */
export interface TelaCorrecaoDureza {
  lote: LoteDaNc;
  registro: { id: number; status: StatusRegistro; quando: string | null; responsavel: string };
  leituras: Leitura[];
  /** null: especificação de dureza não cadastrada para o tipo. */
  esp_min: number | null;
  esp_max: number | null;
  nc: { id: number; numero: string; status: StatusNc } | null;
}

/** POST /registros/{id}/corrigir-dureza */
export interface RespostaCorrecao {
  mensagem: string;
  status: StatusRegistro;
  lote_id: number;
  nc_encerrada: { id: number; numero: string } | null;
  nc_id: number | null;
  leituras: Leitura[];
}
