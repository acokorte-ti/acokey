/**
 * Gráficos dos painéis, em SVG e CSS, sem biblioteca (o sistema antigo usava Chart.js por CDN).
 *
 * Regras (as mesmas para todos): barras finas (até 24 px) com a ponta arredondada e a base reta, um só
 * eixo por gráfico, cor só para identificar a série (PIN, BOX, ARK) e nunca no texto, legenda sempre que há
 * mais de uma série, dica ao passar o mouse ou focar com o teclado e, embaixo, a tabela com os números.
 */
import { useCallback, useEffect, useRef, useState, type FocusEvent, type PointerEvent, type ReactNode, type RefObject } from 'react';
import { Link } from 'react-router-dom';
import { inteiro } from '../../lib/formato';

// ---------------------------------------------------------------- séries e números

export interface Serie {
  chave: string;
  nome: string;
  /** Cor da marca (CSS), ex.: var(--graf-pin). */
  cor: string;
}

/** PIN, BOX e ARK, sempre nesta ordem e nestas cores (as do sistema antigo). */
export const SERIES_TIPO: Serie[] = [
  { chave: 'pin', nome: 'PIN', cor: 'var(--graf-pin)' },
  { chave: 'box', nome: 'BOX', cor: 'var(--graf-box)' },
  { chave: 'ark', nome: 'ARK', cor: 'var(--graf-ark)' },
];

const fmtDecimal = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function decimal(valor: number): string {
  return fmtDecimal.format(valor);
}

export function porcentagem(valor: number): string {
  return `${fmtDecimal.format(valor)}%`;
}

/** "11/2026" -> "nov/26" */
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
export function mesCurto(mesAno: string): string {
  const [mes, ano] = mesAno.split('/');
  const indice = Number(mes) - 1;
  return MESES[indice] && ano ? `${MESES[indice]}/${ano.slice(-2)}` : mesAno;
}

/** Eixo com números redondos (0 / 5 / 10 / 15), no máximo quatro marcas acima do zero. */
function escalaRedonda(maximo: number): { topo: number; marcas: number[] } {
  if (!(maximo > 0)) return { topo: 1, marcas: [0, 1] };
  const bruto = maximo / 3;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const fracao = bruto / potencia;
  const passo = Math.max(1, Math.round(([1, 2, 5, 10].find((c) => fracao <= c) ?? 10) * potencia));
  const quantidade = Math.ceil(maximo / passo - 1e-9);
  return { topo: quantidade * passo, marcas: Array.from({ length: quantidade + 1 }, (_, i) => i * passo) };
}

// ---------------------------------------------------------------- dica (tooltip)

interface Dica {
  x: number;
  y: number;
  conteudo: ReactNode;
}

/** Dica posicionada dentro do quadro do gráfico, acima do elemento apontado ou focado. */
function useDica(): {
  caixa: RefObject<HTMLDivElement>;
  dica: Dica | null;
  mostrar: (alvo: Element, conteudo: ReactNode) => void;
  esconder: () => void;
} {
  const caixa = useRef<HTMLDivElement>(null);
  const [dica, setDica] = useState<Dica | null>(null);
  const mostrar = useCallback((alvo: Element, conteudo: ReactNode) => {
    const quadro = caixa.current?.getBoundingClientRect();
    const marca = alvo.getBoundingClientRect();
    if (!quadro) return;
    setDica({ x: marca.left + marca.width / 2 - quadro.left, y: marca.top - quadro.top, conteudo });
  }, []);
  const esconder = useCallback(() => setDica(null), []);
  return { caixa, dica, mostrar, esconder };
}

function CaixaDica({ dica }: { dica: Dica | null }) {
  if (!dica) return null;
  return (
    <div className="graf-dica" style={{ left: dica.x, top: dica.y }} role="presentation">
      {dica.conteudo}
    </div>
  );
}

/** Linha da dica: o valor em destaque, o nome da série depois, com um traço da cor da série. */
export function LinhaDica({ cor, valor, nome }: { cor?: string; valor: ReactNode; nome: ReactNode }) {
  return (
    <span className="graf-dica-linha">
      {cor && <span className="graf-dica-traco" style={{ background: cor }} aria-hidden="true" />}
      <strong>{valor}</strong> <span>{nome}</span>
    </span>
  );
}

/** Eventos de mouse e teclado que abrem a dica de uma marca. */
function eventosDica(mostrar: (alvo: Element, conteudo: ReactNode) => void, esconder: () => void, conteudo: ReactNode) {
  return {
    onPointerEnter: (e: PointerEvent<Element>) => mostrar(e.currentTarget, conteudo),
    onPointerLeave: esconder,
    onFocus: (e: FocusEvent<Element>) => mostrar(e.currentTarget, conteudo),
    onBlur: esconder,
  };
}

// ---------------------------------------------------------------- legenda e tabela

export function Legenda({ series, extra }: { series: Serie[]; extra?: (s: Serie) => ReactNode }) {
  return (
    <ul className="graf-legenda" aria-label="Legenda">
      {series.map((s) => (
        <li key={s.chave}>
          <span className="graf-amostra" style={{ background: s.cor }} aria-hidden="true" />
          {s.nome}
          {extra && <span className="graf-legenda-extra">{extra(s)}</span>}
        </li>
      ))}
    </ul>
  );
}

/** Os números do gráfico em tabela, recolhida (a dica nunca é o único jeito de ver um valor). */
export function TabelaDados({ legenda, colunas, linhas }: { legenda: string; colunas: string[]; linhas: (string | number)[][] }) {
  return (
    <details className="graf-tabela">
      <summary>Ver os números</summary>
      <div className="tabela-rolagem">
        <table className="tabela">
          <caption className="so-leitor">{legenda}</caption>
          <thead>
            <tr>
              {colunas.map((c, i) => (
                <th key={c} scope="col" className={i > 0 ? 'num' : undefined}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {linhas.map((linha, i) => (
              <tr key={i}>
                {linha.map((valor, j) => (
                  <td key={j} className={j > 0 ? 'num' : undefined}>
                    {typeof valor === 'number' ? inteiro(valor) : valor}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** Quadro de um gráfico: título, texto de apoio, o gráfico (ou a mensagem de vazio). */
export function CartaoGrafico({
  titulo,
  apoio,
  vazio,
  children,
  classe,
}: {
  titulo: string;
  apoio?: ReactNode;
  /** Mensagem no lugar do gráfico quando não há dados. */
  vazio?: string | false;
  children: ReactNode;
  classe?: string;
}) {
  return (
    <section className={`cartao graf-cartao ${classe ?? ''}`}>
      <div>
        <h3 className="graf-titulo">{titulo}</h3>
        {apoio && <p className="apoio">{apoio}</p>}
      </div>
      {vazio ? <p className="graf-vazio">{vazio}</p> : children}
    </section>
  );
}

// ---------------------------------------------------------------- barras horizontais (categorias)

export interface ItemBarra {
  chave: string;
  rotulo: string;
  /** Em cada categoria, um valor por série (na ordem de `series`). */
  valores: number[];
  /** Texto na ponta de cada barra; sem ele, o valor. */
  textos?: string[];
  /** Conteúdo da dica de cada barra. */
  dicas?: ReactNode[];
  link?: string;
}

/**
 * Uma barra por categoria (uma série) ou um grupo de barras por categoria (várias séries, ex.: PIN/BOX/ARK).
 * O comprimento é proporcional ao maior valor do gráfico; o número vai na ponta.
 */
export function BarrasHorizontais({ itens, series, legenda }: { itens: ItemBarra[]; series: Serie[]; legenda: string }) {
  const { caixa, dica, mostrar, esconder } = useDica();
  const maximo = Math.max(0, ...itens.flatMap((i) => i.valores));
  const variasSeries = series.length > 1;
  return (
    <div className="graf-quadro" ref={caixa}>
      {variasSeries && <Legenda series={series} />}
      <ul className="graf-barras" aria-label={legenda}>
        {itens.map((item) => (
          <li key={item.chave} className={`graf-barras-item ${variasSeries ? 'graf-barras-grupo' : ''}`}>
            <span className="graf-barras-rotulo">{item.link ? <Link to={item.link}>{item.rotulo}</Link> : item.rotulo}</span>
            <span className="graf-barras-trilhos">
              {series.map((serie, k) => {
                const valor = item.valores[k] ?? 0;
                const texto = item.textos?.[k] ?? inteiro(valor);
                const conteudo = item.dicas?.[k] ?? <LinhaDica cor={serie.cor} valor={texto} nome={variasSeries ? `${serie.nome} · ${item.rotulo}` : item.rotulo} />;
                return (
                  <span key={serie.chave} className="graf-trilho">
                    <span
                      className="graf-barra"
                      style={{ width: maximo > 0 ? `calc((100% - 9.5rem) * ${valor / maximo})` : 0, background: serie.cor }}
                      tabIndex={0}
                      role="img"
                      aria-label={`${variasSeries ? `${serie.nome}, ` : ''}${item.rotulo}: ${texto}`}
                      {...eventosDica(mostrar, esconder, conteudo)}
                    />
                    <span className="graf-barra-valor" aria-hidden="true">
                      {texto}
                    </span>
                  </span>
                );
              })}
            </span>
          </li>
        ))}
      </ul>
      <CaixaDica dica={dica} />
    </div>
  );
}

// ---------------------------------------------------------------- colunas por mês

function useLargura(): [RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [largura, setLargura] = useState(0);
  useEffect(() => {
    const elemento = ref.current;
    if (!elemento) return;
    const observador = new ResizeObserver((entradas) => {
      const entrada = entradas[0];
      if (entrada) setLargura(Math.round(entrada.contentRect.width));
    });
    observador.observe(elemento);
    setLargura(Math.round(elemento.getBoundingClientRect().width));
    return () => observador.disconnect();
  }, []);
  return [ref, largura];
}

/** Coluna com o topo arredondado (4 px) e a base reta, apoiada na linha do zero. */
function caminhoColuna(x: number, base: number, largura: number, altura: number): string {
  const r = Math.min(4, altura, largura / 2);
  const topo = base - altura;
  return `M${x},${base}V${topo + r}Q${x},${topo} ${x + r},${topo}H${x + largura - r}Q${x + largura},${topo} ${x + largura},${topo + r}V${base}Z`;
}

export interface MesColunas {
  chave: string;
  /** "MM/AAAA" */
  mes: string;
  /** Um valor por série (na ordem de `series`). */
  valores: number[];
}

const ESQUERDA = 44;
const DIREITA = 12;
const TOPO = 22;
const ALTURA = 230;
const RODAPE = 26;

/**
 * Colunas por mês: uma série (ex.: databooks enviados) ou várias lado a lado (peças de PIN, BOX e ARK).
 * A dica do mês mostra todas as séries (e o total, quando há mais de uma).
 */
export function ColunasMensais({
  meses,
  series,
  legenda,
  unidade,
}: {
  meses: MesColunas[];
  series: Serie[];
  legenda: string;
  /** "databooks", "peças": vai na dica e no eixo. */
  unidade: string;
}) {
  const [medida, largura] = useLargura();
  const { caixa, dica, mostrar, esconder } = useDica();
  const n = meses.length;
  const maximo = Math.max(0, ...meses.flatMap((m) => m.valores));
  const escala = escalaRedonda(maximo);
  const util = Math.max(largura - ESQUERDA - DIREITA, 60);
  const banda = n > 0 ? util / n : util;
  const vao = 2;
  const larguraBarra = Math.max(2, Math.min(24, (banda * 0.78 - vao * (series.length - 1)) / series.length));
  const grupo = larguraBarra * series.length + vao * (series.length - 1);
  const base = TOPO + ALTURA;
  const y = (v: number) => base - (v / escala.topo) * ALTURA;
  const cadaQuantos = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(util / 48))));
  // Rótulo no topo da coluna só onde interessa: o maior valor e o último mês (uma série só)
  const indiceMaior = meses.reduce((melhor, m, i) => ((m.valores[0] ?? 0) > (meses[melhor]?.valores[0] ?? 0) ? i : melhor), 0);

  function conteudoMes(m: MesColunas): ReactNode {
    const total = m.valores.reduce((s, v) => s + v, 0);
    return (
      <>
        <span className="graf-dica-titulo">{m.mes}</span>
        {series.map((s, k) => (
          <LinhaDica key={s.chave} cor={series.length > 1 ? s.cor : undefined} valor={inteiro(m.valores[k] ?? 0)} nome={series.length > 1 ? s.nome : unidade} />
        ))}
        {series.length > 1 && <LinhaDica valor={inteiro(total)} nome={`${unidade} no mês`} />}
      </>
    );
  }

  return (
    <div className="graf-quadro" ref={caixa}>
      {series.length > 1 && <Legenda series={series} />}
      <div ref={medida} className="graf-svg">
        {largura > 0 && (
          <svg width={largura} height={base + RODAPE} role="img" aria-label={legenda}>
            {escala.marcas.map((marca) => (
              <g key={marca}>
                <line x1={ESQUERDA} x2={largura - DIREITA} y1={y(marca)} y2={y(marca)} className={marca === 0 ? 'graf-base' : 'graf-grade'} />
                <text x={ESQUERDA - 6} y={y(marca)} className="graf-eixo" textAnchor="end" dominantBaseline="middle">
                  {inteiro(marca)}
                </text>
              </g>
            ))}
            {meses.map((m, i) => {
              const inicio = ESQUERDA + banda * i + (banda - grupo) / 2;
              const mostrarRotulo = i % cadaQuantos === (n - 1) % cadaQuantos;
              const valorUnico = m.valores[0] ?? 0;
              const rotuloTopo = series.length === 1 && valorUnico > 0 && (i === indiceMaior || i === n - 1);
              return (
                <g key={m.chave}>
                  {/* Área de toque: a faixa inteira do mês, não só a coluna */}
                  <rect
                    x={ESQUERDA + banda * i}
                    y={TOPO - 16}
                    width={banda}
                    height={ALTURA + 16}
                    className="graf-alvo"
                    tabIndex={0}
                    role="img"
                    aria-label={`${m.mes}: ${series.map((s, k) => `${series.length > 1 ? `${s.nome} ` : ''}${inteiro(m.valores[k] ?? 0)}`).join(', ')} ${unidade}`}
                    {...eventosDica(mostrar, esconder, conteudoMes(m))}
                  />
                  {series.map((s, k) => {
                    const valor = m.valores[k] ?? 0;
                    if (valor <= 0) return null;
                    const altura = Math.max(1, base - y(valor));
                    return (
                      <path
                        key={s.chave}
                        d={caminhoColuna(inicio + k * (larguraBarra + vao), base, larguraBarra, altura)}
                        fill={s.cor}
                        className="graf-coluna"
                      />
                    );
                  })}
                  {rotuloTopo && (
                    <text x={inicio + grupo / 2} y={y(valorUnico) - 6} className="graf-valor" textAnchor="middle">
                      {inteiro(valorUnico)}
                    </text>
                  )}
                  {mostrarRotulo && (
                    <text x={ESQUERDA + banda * (i + 0.5)} y={base + 17} className="graf-eixo" textAnchor="middle">
                      {mesCurto(m.mes)}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <CaixaDica dica={dica} />
    </div>
  );
}

// ---------------------------------------------------------------- barra dividida (parte de um todo)

/** Um todo dividido em partes (ex.: o mix PIN / BOX / ARK), com a % dentro de cada parte quando cabe. */
export function BarraDividida({ partes, unidade, legenda }: { partes: (Serie & { valor: number })[]; unidade: string; legenda: string }) {
  const { caixa, dica, mostrar, esconder } = useDica();
  const total = partes.reduce((s, p) => s + p.valor, 0);
  const visiveis = partes.filter((p) => p.valor > 0);
  const pctDe = (valor: number) => (total > 0 ? Math.round((valor * 100) / total) : 0);
  return (
    <div className="graf-quadro" ref={caixa}>
      <div className="graf-dividida" role="list" aria-label={legenda}>
        {visiveis.map((p) => (
          <span
            key={p.chave}
            role="listitem"
            className="graf-parte"
            style={{ flexGrow: p.valor, background: p.cor }}
            tabIndex={0}
            aria-label={`${p.nome}: ${inteiro(p.valor)} ${unidade} (${pctDe(p.valor)}%)`}
            {...eventosDica(mostrar, esconder, <LinhaDica cor={p.cor} valor={`${inteiro(p.valor)} ${unidade}`} nome={`${p.nome} · ${pctDe(p.valor)}%`} />)}
          >
            {pctDe(p.valor) >= 12 && <span aria-hidden="true">{pctDe(p.valor)}%</span>}
          </span>
        ))}
      </div>
      <Legenda series={partes} extra={(s) => {
        const parte = partes.find((p) => p.chave === s.chave);
        return parte ? `${inteiro(parte.valor)} (${pctDe(parte.valor)}%)` : null;
      }} />
      <CaixaDica dica={dica} />
    </div>
  );
}
