/**
 * Cálculos ao vivo dos formulários de registro. Repetem os de backend/app/formularios.py: a tela mostra verde/vermelho
 * enquanto a pessoa digita, mas quem decide o resultado gravado é sempre o servidor.
 */

/** "24,5" -> 24.5; vazio ou texto -> null */
export function num(valor: string | number | null | undefined): number | null {
  if (valor === null || valor === undefined) return null;
  if (typeof valor === 'number') return Number.isFinite(valor) ? valor : null;
  const texto = valor.trim().replace(',', '.');
  if (texto === '') return null;
  const numero = Number(texto);
  return Number.isFinite(numero) ? numero : null;
}

/** Número em pt-BR, sem zeros sobrando: 24.5 -> "24,5". */
export function fmt(valor: number | null | undefined, casas = 3): string {
  if (valor === null || valor === undefined || !Number.isFinite(valor)) return '';
  return valor.toLocaleString('pt-BR', { maximumFractionDigits: casas });
}

export function dentro(valor: number, minimo: number | null, maximo: number | null): boolean {
  return (minimo === null || valor >= minimo) && (maximo === null || valor <= maximo);
}

/** Linhas "tempo;temperatura" (aceita ; tab espaço ou vírgula), em ordem de tempo. */
export function lerCurva(texto: string): [number, number][] {
  const pontos: [number, number][] = [];
  for (const bruta of texto.split(/\r?\n/)) {
    const linha = bruta.trim();
    if (!linha) continue;
    const partes = linha.includes(';') || linha.includes('\t') ? linha.replace(/,/g, '.').split(/[;\t]+/) : linha.split(/[,\s]+/);
    const x = num(partes[0]);
    const y = num(partes[1]);
    if (x !== null && y !== null) pontos.push([x, y]);
  }
  return pontos.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
}

/** Minutos em que a curva ficou dentro da faixa [baixo, alto], interpolando entre os pontos. */
export function tempoNoPatamar(pontos: [number, number][], baixo: number, alto: number): number {
  let total = 0;
  for (let i = 0; i + 1 < pontos.length; i++) {
    const [x1, y1] = pontos[i];
    const [x2, y2] = pontos[i + 1];
    const dx = x2 - x1;
    if (dx <= 0) continue;
    if (y1 === y2) {
      if (baixo <= y1 && y1 <= alto) total += dx;
      continue;
    }
    let a = (baixo - y1) / (y2 - y1);
    let b = (alto - y1) / (y2 - y1);
    if (a > b) [a, b] = [b, a];
    a = Math.max(a, 0);
    b = Math.min(b, 1);
    if (b > a) total += (b - a) * dx;
  }
  return total;
}

export interface PecaDureza {
  nome: string;
  valores: number[];
}

/** "P1 35 37", "P1-35-35-37" ou "35;35;37" (uma peça por linha). Devolve as peças ou a mensagem de erro. */
export function lerLeituras(texto: string): { pecas: PecaDureza[]; erro: string | null } {
  const pecas: PecaDureza[] = [];
  const linhas = texto.split(/\r?\n/).filter((l) => l.trim());
  for (let i = 0; i < linhas.length; i++) {
    const linha = linhas[i];
    const partes = linha.trim().split(/[;\s-]+/).filter(Boolean);
    let nome: string | null = null;
    const valores: number[] = [];
    for (const parte of partes) {
      const valor = num(parte);
      if (valor === null) {
        if (nome === null && valores.length === 0) nome = parte;
        else return { pecas, erro: `Linha ${i + 1}: o valor '${parte}' não é um número.` };
      } else {
        valores.push(valor);
      }
    }
    if (valores.length === 0) return { pecas, erro: `Linha ${i + 1}: nenhuma leitura numérica.` };
    pecas.push({ nome: nome ?? `P${i + 1}`, valores });
  }
  return { pecas, erro: null };
}

/** Medidas separadas por ponto e vírgula ou espaço. */
export function tokens(texto: string): string[] {
  return texto.trim().split(/[;\s]+/).filter(Boolean);
}

/**
 * Códigos gravados a laser, no formato do parâmetro (ex.: "{ano}T{tri}-C{corrida}-L{lote}-{seq:03d}").
 * Entende {campo} e {campo:0Nd}, que é o que o formato usa.
 */
export function codigoLaser(formato: string, valores: { ano: string; tri: string; corrida: string; lote: string; seq: number }): string {
  return formato.replace(/\{(\w+)(?::0?(\d+)d)?\}/g, (_inteiro, campo: string, largura?: string) => {
    const valor = String((valores as unknown as Record<string, string | number>)[campo] ?? '');
    return largura ? valor.padStart(Number(largura), '0') : valor;
  });
}

export function trimestreDe(data: Date): number {
  return Math.floor(data.getMonth() / 3) + 1;
}
