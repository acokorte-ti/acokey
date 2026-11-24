/** Formatos da API de verificação dimensional (backend/app/api_dimensional.py e dimensional.py). */
import type { TipoLote } from '../../lib/tipos';

export interface AmostraFora {
  /** "P1".."P10" */
  amostra: string;
  valor: number;
}

export interface Caracteristica {
  car: string;
  requisito: string;
  espec: string;
  tol: string;
  nominal: number | null;
  /** [mínimo, máximo] aceitáveis; null quando a tolerância não pôde ser calculada. */
  faixa: [number, number] | null;
  fora: AmostraFora[];
  /** Tolerância em formato não reconhecido: revisar à mão. */
  aviso: boolean;
  /** P1..P10: número, "ok" (qualitativo) ou null (vazio). */
  amostras: (number | 'ok' | null)[];
  minimo: number | null;
  maximo: number | null;
}

export interface Rodape {
  status?: string;
  inspecionado_por?: string;
  data_inspecao?: string;
  aprovado_por?: string;
  data_aprovacao?: string;
}

export type ResultadoAnalise =
  | { ok: false; erro: string }
  | {
      ok: true;
      erro: null;
      total_cars: number;
      cars: Caracteristica[];
      cars_fora: Caracteristica[];
      cars_aviso: Caracteristica[];
      rodape: Rodape;
    };

/** POST /dimensional/verificar e GET /dimensional/anexos/{id} */
export interface RespostaVerificacao {
  nome: string;
  anexo: { id: number; etapa: string; sub: string } | null;
  lote: { id: number; numero: string; op: string; tipo: TipoLote } | null;
  resultado: ResultadoAnalise;
}
