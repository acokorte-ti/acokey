import { useMemo, useState, type ReactNode } from 'react';
import { inteiro } from '../lib/formato';

type ValorOrdenavel = string | number | boolean | null | undefined;

export interface Coluna<T> {
  chave: string;
  titulo: string;
  /** Valor usado para ordenar (e mostrado, se `celula` não for informada). */
  valor: (linha: T) => ValorOrdenavel;
  /** Como desenhar a célula. */
  celula?: (linha: T) => ReactNode;
  /** Alinha à direita com algarismos de largura fixa. */
  numerica?: boolean;
  /** Fonte monoespaçada (códigos). */
  mono?: boolean;
  /** Explicação que aparece ao passar o mouse no título. */
  dica?: string;
  ordenavel?: boolean;
}

export interface Ordenacao {
  chave: string;
  direcao: 'asc' | 'desc';
}

interface PropsTabela<T> {
  /** Descrição da tabela para leitores de tela. */
  legenda: string;
  colunas: Coluna<T>[];
  linhas: T[];
  chaveLinha: (linha: T) => string | number;
  ordemInicial?: Ordenacao;
  classeLinha?: (linha: T) => string | undefined;
  /** Mostra só as primeiras N linhas, com um botão para ver todas. */
  limite?: number;
}

function comparar(a: ValorOrdenavel, b: ValorOrdenavel): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b);
  return String(a).localeCompare(String(b), 'pt-BR', { numeric: true, sensitivity: 'base' });
}

/** Tabela que ordena por qualquer coluna (clique no título). Vazios ficam sempre no fim. */
export function TabelaOrdenavel<T>({
  legenda,
  colunas,
  linhas,
  chaveLinha,
  ordemInicial,
  classeLinha,
  limite,
}: PropsTabela<T>) {
  const [ordem, setOrdem] = useState<Ordenacao | null>(ordemInicial ?? null);
  const [verTodas, setVerTodas] = useState(false);

  const ordenadas = useMemo(() => {
    const coluna = ordem ? colunas.find((c) => c.chave === ordem.chave) : undefined;
    if (!ordem || !coluna) return linhas;
    const sinal = ordem.direcao === 'asc' ? 1 : -1;
    const semValor = (v: ValorOrdenavel) => v === null || v === undefined || v === '';
    return [...linhas].sort((x, y) => {
      const a = coluna.valor(x);
      const b = coluna.valor(y);
      if (semValor(a) && semValor(b)) return 0;
      if (semValor(a)) return 1;
      if (semValor(b)) return -1;
      return sinal * comparar(a, b);
    });
  }, [linhas, colunas, ordem]);

  function ordenarPor(coluna: Coluna<T>) {
    setOrdem((atual) => {
      if (atual?.chave === coluna.chave) return { chave: coluna.chave, direcao: atual.direcao === 'asc' ? 'desc' : 'asc' };
      // Números começam do maior para o menor (o que mais interessa); textos, de A a Z
      return { chave: coluna.chave, direcao: coluna.numerica ? 'desc' : 'asc' };
    });
  }

  const visiveis = limite && !verTodas ? ordenadas.slice(0, limite) : ordenadas;

  return (
    <>
      <div className="tabela-rolagem">
        <table className="tabela">
          <caption className="so-leitor">{legenda}</caption>
          <thead>
            <tr>
              {colunas.map((coluna) => {
                const direcao = ordem && ordem.chave === coluna.chave ? ordem.direcao : null;
                const classe = coluna.numerica ? 'num' : undefined;
                if (coluna.ordenavel === false) {
                  return (
                    <th key={coluna.chave} scope="col" className={classe} title={coluna.dica}>
                      {coluna.titulo}
                    </th>
                  );
                }
                return (
                  <th
                    key={coluna.chave}
                    scope="col"
                    className={classe}
                    aria-sort={direcao === 'asc' ? 'ascending' : direcao === 'desc' ? 'descending' : 'none'}
                  >
                    <button type="button" className="ordenar" onClick={() => ordenarPor(coluna)} title={coluna.dica}>
                      {coluna.titulo}
                      <span className={`ordenar-seta ${direcao ? 'ordenar-ativa' : ''}`} aria-hidden="true">
                        {direcao === 'asc' ? '▲' : direcao === 'desc' ? '▼' : '↕'}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visiveis.map((linha) => (
              <tr key={chaveLinha(linha)} className={classeLinha?.(linha)}>
                {colunas.map((coluna) => {
                  const classes = [coluna.numerica ? 'num' : '', coluna.mono ? 'mono' : ''].filter(Boolean).join(' ');
                  const conteudo = coluna.celula ? coluna.celula(linha) : (coluna.valor(linha) ?? '—');
                  return (
                    <td key={coluna.chave} className={classes || undefined}>
                      {typeof conteudo === 'boolean' ? (conteudo ? 'Sim' : 'Não') : conteudo}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {limite !== undefined && ordenadas.length > limite && (
        <button type="button" className="botao-link ver-todas" onClick={() => setVerTodas((v) => !v)}>
          {verTodas ? `Mostrar só as ${limite} primeiras` : `Mostrar todas as ${inteiro(ordenadas.length)}`}
        </button>
      )}
    </>
  );
}

interface PropsPaginacao {
  pagina: number;
  tamanho: number;
  total: number;
  aoMudar: (pagina: number) => void;
}

/** "1–50 de 1.234" com Anterior / Próxima. */
export function Paginacao({ pagina, tamanho, total, aoMudar }: PropsPaginacao) {
  const paginas = Math.max(1, Math.ceil(total / tamanho));
  const primeiro = total === 0 ? 0 : (pagina - 1) * tamanho + 1;
  const ultimo = Math.min(pagina * tamanho, total);
  return (
    <nav className="paginacao" aria-label="Paginação">
      <span className="paginacao-faixa">
        {inteiro(primeiro)}–{inteiro(ultimo)} de {inteiro(total)}
      </span>
      <button type="button" className="botao" onClick={() => aoMudar(pagina - 1)} disabled={pagina <= 1}>
        ‹ Anterior
      </button>
      <span className="paginacao-pagina">
        Página {inteiro(pagina)} de {inteiro(paginas)}
      </span>
      <button type="button" className="botao" onClick={() => aoMudar(pagina + 1)} disabled={pagina >= paginas}>
        Próxima ›
      </button>
    </nav>
  );
}
