/**
 * Formatação em pt-BR e datas.
 *
 * Dois tipos de data chegam da API:
 *   - datas de negócio (lote criado em, desde quando está na etapa, registros, anexos, eventos):
 *     hora LOCAL da fábrica, sem fuso ("2026-11-19T07:30:00"). São tratadas como texto (fatiando
 *     a string) e NUNCA passam por `new Date()`, que deslocaria o horário;
 *   - datas de sistema (auditoria, último login): vêm com fuso e são mostradas no horário de São Paulo.
 */
import type { Modulo, Usuario } from './tipos';

export const TRACO = '—';
const FUSO = 'America/Sao_Paulo';

const fmtInteiro = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const fmtSistema = new Intl.DateTimeFormat('pt-BR', {
  timeZone: FUSO,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

function vazio(valor: number | null | undefined): valor is null | undefined {
  return valor === null || valor === undefined || Number.isNaN(valor);
}

export function inteiro(valor: number | null | undefined): string {
  return vazio(valor) ? TRACO : fmtInteiro.format(valor);
}

/** 72 -> "72 peças"; 1 -> "1 peça" */
export function pecas(quantidade: number | null | undefined): string {
  if (vazio(quantidade)) return TRACO;
  return `${fmtInteiro.format(quantidade)} ${quantidade === 1 ? 'peça' : 'peças'}`;
}

/** Dias parado na etapa: 0 -> "hoje"; 1 -> "há 1 dia"; 5 -> "há 5 dias" */
export function haDias(dias: number | null | undefined): string {
  if (vazio(dias)) return TRACO;
  if (dias <= 0) return 'hoje';
  return dias === 1 ? 'há 1 dia' : `há ${fmtInteiro.format(dias)} dias`;
}

// ---------------------------------------------------------------- datas de negócio (texto, sem fuso)

/** "2026-11-19T07:30:00" -> "19/11/2026 07:30" */
export function dataHoraLocal(texto: string | null | undefined): string {
  if (!texto || texto.length < 16) return TRACO;
  return `${texto.slice(8, 10)}/${texto.slice(5, 7)}/${texto.slice(0, 4)} ${texto.slice(11, 16)}`;
}

/** "2026-11-19" (ou data e hora) -> "19/11/2026" */
export function dataCurta(texto: string | null | undefined): string {
  if (!texto || texto.length < 10) return TRACO;
  return `${texto.slice(8, 10)}/${texto.slice(5, 7)}/${texto.slice(0, 4)}`;
}

// ---------------------------------------------------------------- datas de sistema (com fuso)

/** "2026-11-19T10:30:00+00:00" -> "19/11/2026 07:30" (horário de São Paulo) */
export function dataHoraSistema(texto: string | null | undefined): string {
  if (!texto) return TRACO;
  const data = new Date(texto);
  if (Number.isNaN(data.getTime())) return TRACO;
  return fmtSistema.format(data).replace(',', '');
}

// ---------------------------------------------------------------- texto

/** Minúsculas e sem acentos, para buscar "tempera" e achar "TÊMPERA". */
export function normalizar(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}

/** Todos os termos digitados aparecem no texto (ignorando acentos e maiúsculas). */
export function contemTermos(texto: string, busca: string): boolean {
  const termos = normalizar(busca).split(/\s+/).filter(Boolean);
  if (termos.length === 0) return true;
  const alvo = normalizar(texto);
  return termos.every((t) => alvo.includes(t));
}

// ---------------------------------------------------------------- rótulos

/** Módulos do sistema, na ordem em que aparecem nas telas. */
export const MODULOS: { chave: Modulo; rotulo: string }[] = [
  { chave: 'qualidade', rotulo: 'Qualidade' },
  { chave: 'pcp', rotulo: 'PCP' },
  { chave: 'producao_tt', rotulo: 'Produção – TT' },
  { chave: 'producao_usinagem', rotulo: 'Produção – Usinagem' },
  { chave: 'cadastros', rotulo: 'Cadastros' },
];

/** Os módulos liberados, por extenso e na ordem padrão: "Qualidade, PCP". */
export function nomesDosModulos(modulos: readonly Modulo[]): string {
  return MODULOS.filter((m) => modulos.includes(m.chave))
    .map((m) => m.rotulo)
    .join(', ');
}

/** Resumo do que o usuário acessa: "Administrador · Qualidade, PCP". */
export function resumoDoAcesso(usuario: Pick<Usuario, 'admin' | 'modulos'>): string {
  const partes = [usuario.admin ? 'Administrador' : '', nomesDosModulos(usuario.modulos)].filter(Boolean);
  return partes.length > 0 ? partes.join(' · ') : 'Só consulta';
}
