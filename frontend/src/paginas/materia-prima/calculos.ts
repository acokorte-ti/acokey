/**
 * Cálculos e cores da matéria-prima, iguais aos do sistema antigo (legado/app.py: _mp_calcular e
 * TEMPLATES["materia_prima"]): verde = bom, amarelo = atenção, vermelho = alto.
 */
import type { Quantidades } from './tipos';

export type Tom = 'ok' | 'alerta' | 'erro' | 'info' | '';

const fmtPct = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** 6 -> "6,0%" */
export function porcento(valor: number): string {
  return `${fmtPct.format(valor)}%`;
}

function pct(numerador: number, denominador: number): number {
  return denominador ? Math.round((numerador / denominador) * 1000) / 10 : 0;
}

/** Percentuais e disponível de uma corrida ainda sendo digitada (o servidor recalcula ao gravar). */
export function calcular(q: Quantidades) {
  return {
    pct_refugo: pct(q.qt_rej, q.qt_real),
    pct_retrab: pct(q.qt_retrab, q.qt_real),
    pct_aprov: pct(q.qt_ok, q.qt_real),
    rendimento: pct(q.qt_ok, q.qt_fund),
    qt_disponivel: Math.max(q.qt_ok - q.qt_cp_tt, 0),
  };
}

/** Saldo: zerado em vermelho, abaixo de 50 peças em amarelo. */
export function tomSaldo(saldo: number): Tom {
  if (saldo <= 0) return 'erro';
  return saldo < 50 ? 'alerta' : 'ok';
}

/** Refugo: a partir de 10% vermelho, de 5% amarelo. */
export function tomRefugo(valor: number): Tom {
  if (valor >= 10) return 'erro';
  return valor >= 5 ? 'alerta' : 'ok';
}

/** Retrabalho: a partir de 25% vermelho, de 15% amarelo. */
export function tomRetrabalho(valor: number): Tom {
  if (valor >= 25) return 'erro';
  return valor >= 15 ? 'alerta' : 'ok';
}

/** Data de hoje no computador de quem usa, em "AAAA-MM-DD" (para o campo de data). */
export function hojeIso(): string {
  const agora = new Date();
  const mes = String(agora.getMonth() + 1).padStart(2, '0');
  const dia = String(agora.getDate()).padStart(2, '0');
  return `${agora.getFullYear()}-${mes}-${dia}`;
}
