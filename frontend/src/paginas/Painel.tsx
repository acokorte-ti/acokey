import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../componentes/Estados';
import { SeloNcAberta, SeloTipo } from '../componentes/Selos';
import { TabelaOrdenavel, type Coluna } from '../componentes/Tabela';
import { api } from '../lib/api';
import { contemTermos, dataHoraLocal, haDias, inteiro, pecas, TRACO } from '../lib/formato';
import type { Etapa, ListaLotes, LoteResumo, TipoLote } from '../lib/tipos';
import { useCarga } from '../lib/useCarga';

const TIPOS: TipoLote[] = ['PIN', 'BOX', 'ARK'];
/** A coluna "Concluídos" só cresce: mostra os mais recentes e um botão para ver todos. */
const LIMITE_CONCLUIDOS = 8;
const LIMITE_TABELA = 50;

type FiltroTipo = 'todos' | TipoLote;
type FiltroSituacao = 'todos' | 'andamento' | 'concluidos';

const OPCOES_TIPO: { valor: FiltroTipo; rotulo: string }[] = [
  { valor: 'todos', rotulo: 'Todos' },
  ...TIPOS.map((t) => ({ valor: t, rotulo: t })),
];

const OPCOES_SITUACAO: { valor: FiltroSituacao; rotulo: string }[] = [
  { valor: 'todos', rotulo: 'Todos' },
  { valor: 'andamento', rotulo: 'Em andamento' },
  { valor: 'concluidos', rotulo: 'Concluídos' },
];

// ---------------------------------------------------------------- quadro (kanban)

interface Quadro {
  /** Lotes em andamento, pela chave da etapa em que estão. */
  porEtapa: Map<string, LoteResumo[]>;
  concluidos: LoteResumo[];
  /** Lotes em andamento cuja etapa atual não está na lista de etapas (não deveria acontecer). */
  semColuna: number;
}

function montarQuadro(etapas: Etapa[], lotes: LoteResumo[]): Quadro {
  const porEtapa = new Map<string, LoteResumo[]>(etapas.map((e) => [e.chave, []]));
  const concluidos: LoteResumo[] = [];
  let semColuna = 0;

  for (const lote of lotes) {
    if (lote.concluido) {
      concluidos.push(lote);
      continue;
    }
    const coluna = lote.etapa_atual ? porEtapa.get(lote.etapa_atual.chave) : undefined;
    if (coluna) coluna.push(lote);
    else semColuna += 1;
  }

  // Em cada etapa, quem está parado há mais tempo aparece primeiro
  for (const lista of porEtapa.values()) {
    lista.sort((a, b) => (b.dias_na_etapa ?? -1) - (a.dias_na_etapa ?? -1) || a.numero.localeCompare(b.numero, 'pt-BR', { numeric: true }));
  }
  // Concluídos: os mais recentes primeiro
  concluidos.sort((a, b) => (b.etapa_desde ?? '').localeCompare(a.etapa_desde ?? ''));

  return { porEtapa, concluidos, semColuna };
}

/** "Controle de qualidade · só PIN e BOX" (quando a etapa não vale para todos os tipos). */
function apoioDaEtapa(etapa: Etapa): string {
  if (etapa.tipos.length === 0 || etapa.tipos.length >= TIPOS.length) return etapa.setor;
  return `${etapa.setor} · só ${etapa.tipos.join(' e ')}`;
}

function CartaoLote({ lote }: { lote: LoteResumo }) {
  return (
    <Link to={`/lotes/${lote.id}`} className={`cartao-lote ${lote.nc_aberta ? 'cartao-lote-nc' : ''}`}>
      <span className="cartao-lote-topo">
        <SeloTipo tipo={lote.tipo} />
        <span className="cartao-lote-numero">{lote.numero}</span>
      </span>
      <span>
        OP {lote.op} · {pecas(lote.qtd)}
      </span>
      {(lote.dias_na_etapa !== null || lote.nc_aberta) && (
        <span className="cartao-lote-linha">
          <span className="cartao-lote-tempo">{lote.dias_na_etapa !== null ? haDias(lote.dias_na_etapa) : ''}</span>
          {lote.nc_aberta && <SeloNcAberta curto />}
        </span>
      )}
    </Link>
  );
}

interface PropsColuna {
  /** Posição da etapa no processo (a coluna "Concluídos" não tem). */
  passo?: number;
  titulo: string;
  nomeCompleto?: string;
  apoio: string;
  lotes: LoteResumo[];
  classe?: string;
  /** Mostra só os primeiros N, com um botão para ver todos. */
  limite?: number;
}

function ColunaQuadro({ passo, titulo, nomeCompleto, apoio, lotes, classe, limite }: PropsColuna) {
  const [verTodos, setVerTodos] = useState(false);
  const visiveis = limite !== undefined && !verTodos ? lotes.slice(0, limite) : lotes;

  return (
    <li className={`quadro-coluna ${classe ?? ''}`}>
      <div className="quadro-topo">
        <div className="quadro-titulo">
          <h3 title={nomeCompleto}>
            {passo !== undefined && (
              <span className="quadro-passo" aria-hidden="true">
                {passo}
              </span>
            )}
            {titulo}
          </h3>
          <span className="quadro-contagem">
            {inteiro(lotes.length)}
            <span className="so-leitor">{lotes.length === 1 ? ' lote' : ' lotes'}</span>
          </span>
        </div>
        <span className="quadro-setor">{apoio}</span>
      </div>
      {lotes.length === 0 ? (
        <p className="quadro-vazio">Nenhum lote.</p>
      ) : (
        <ul className="quadro-cartoes">
          {visiveis.map((lote) => (
            <li key={lote.id}>
              <CartaoLote lote={lote} />
            </li>
          ))}
        </ul>
      )}
      {limite !== undefined && lotes.length > limite && (
        <button type="button" className="botao-link quadro-mais" onClick={() => setVerTodos((v) => !v)}>
          {verTodos ? `Mostrar só os ${limite} mais recentes` : `Mostrar todos os ${inteiro(lotes.length)}`}
        </button>
      )}
    </li>
  );
}

// ---------------------------------------------------------------- tabela de lotes

const COLUNAS: Coluna<LoteResumo>[] = [
  {
    chave: 'numero',
    titulo: 'Lote',
    mono: true,
    valor: (l) => l.numero,
    celula: (l) => (
      <Link to={`/lotes/${l.id}`} className="link-forte">
        {l.numero}
      </Link>
    ),
  },
  { chave: 'op', titulo: 'OP', mono: true, valor: (l) => l.op },
  { chave: 'tipo', titulo: 'Tipo', valor: (l) => l.tipo, celula: (l) => <SeloTipo tipo={l.tipo} /> },
  { chave: 'qtd', titulo: 'Peças', numerica: true, valor: (l) => l.qtd, celula: (l) => inteiro(l.qtd) },
  { chave: 'corrida', titulo: 'Corrida', mono: true, valor: (l) => l.corrida, dica: 'Corrida da matéria-prima' },
  { chave: 'coditem', titulo: 'Item', mono: true, valor: (l) => l.coditem, dica: 'Código do item (CODITEM)' },
  {
    chave: 'etapa',
    titulo: 'Etapa atual',
    dica: 'Ordena pela sequência do processo',
    // Ordena pela posição no processo; os concluídos ficam depois da última etapa
    valor: (l) => (l.concluido ? Number.MAX_SAFE_INTEGER : (l.etapa_atual?.indice ?? null)),
    celula: (l) => {
      if (l.concluido) return <span className="selo selo-ok">Concluído</span>;
      if (!l.etapa_atual) return TRACO;
      return (
        <>
          {l.etapa_atual.curto}
          <span className="sub">{l.etapa_atual.setor}</span>
        </>
      );
    },
  },
  {
    chave: 'dias',
    titulo: 'Na etapa',
    numerica: true,
    dica: 'Há quantos dias o lote está na etapa atual',
    valor: (l) => (l.concluido ? null : l.dias_na_etapa),
    celula: (l) => (l.concluido ? TRACO : haDias(l.dias_na_etapa)),
  },
  {
    chave: 'progresso',
    titulo: 'Progresso',
    dica: 'Etapas aprovadas, entre as que valem para o tipo do lote',
    valor: (l) => (l.progresso.total > 0 ? l.progresso.aprovadas / l.progresso.total : null),
    celula: (l) => (
      <span className="progresso-mini">
        <progress
          className="progresso-barra"
          max={Math.max(l.progresso.total, 1)}
          value={Math.min(l.progresso.aprovadas, Math.max(l.progresso.total, 1))}
          aria-label="Etapas aprovadas"
        />
        <span className="mono">
          {inteiro(l.progresso.aprovadas)}/{inteiro(l.progresso.total)}
        </span>
      </span>
    ),
  },
  {
    chave: 'nc',
    titulo: 'NC',
    dica: 'Não conformidade aberta ou em tratamento',
    valor: (l) => l.nc_aberta,
    celula: (l) => (l.nc_aberta ? <SeloNcAberta /> : TRACO),
  },
  {
    chave: 'criado',
    titulo: 'Criado em',
    mono: true,
    valor: (l) => l.criado_em,
    celula: (l) => dataHoraLocal(l.criado_em),
  },
];

interface PropsSegmentos<T extends string> {
  /** id do texto que serve de rótulo ao grupo. */
  idRotulo: string;
  opcoes: { valor: T; rotulo: string }[];
  valor: T;
  aoMudar: (valor: T) => void;
}

/** Controle segmentado: uma opção marcada por vez. */
function Segmentos<T extends string>({ idRotulo, opcoes, valor, aoMudar }: PropsSegmentos<T>) {
  return (
    <div className="segmentos" role="group" aria-labelledby={idRotulo}>
      {opcoes.map((opcao) => (
        <button
          key={opcao.valor}
          type="button"
          className={`segmento ${valor === opcao.valor ? 'segmento-ativo' : ''}`}
          aria-pressed={valor === opcao.valor}
          onClick={() => aoMudar(opcao.valor)}
        >
          {opcao.rotulo}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- tela

export function Painel() {
  const etapas = useCarga<Etapa[]>((sinal) => api('/etapas', { sinal }), []);
  const lotes = useCarga<ListaLotes>((sinal) => api('/lotes', { sinal }), []);
  const [busca, setBusca] = useState('');
  const [tipo, setTipo] = useState<FiltroTipo>('todos');
  const [situacao, setSituacao] = useState<FiltroSituacao>('todos');

  const listaEtapas = etapas.dados;
  const itens = lotes.dados?.itens;
  const erro = etapas.erro ?? lotes.erro;
  const carregando = etapas.carregando || lotes.carregando;

  const quadro = useMemo(() => (listaEtapas && itens ? montarQuadro(listaEtapas, itens) : null), [listaEtapas, itens]);

  const filtrados = useMemo(
    () =>
      (itens ?? []).filter((l) => {
        if (tipo !== 'todos' && l.tipo !== tipo) return false;
        if (situacao === 'andamento' && l.concluido) return false;
        if (situacao === 'concluidos' && !l.concluido) return false;
        return contemTermos(`${l.numero} ${l.op} ${l.corrida}`, busca);
      }),
    [itens, busca, tipo, situacao],
  );

  function atualizar() {
    etapas.recarregar();
    lotes.recarregar();
  }

  const temFiltro = busca.trim() !== '' || tipo !== 'todos' || situacao !== 'todos';
  const comNc = itens ? itens.filter((l) => l.nc_aberta).length : 0;

  return (
    <>
      <Cabecalho titulo="Painel" apoio="Onde está cada lote no processo de fabricação.">
        <button type="button" className="botao" onClick={atualizar} disabled={carregando}>
          {carregando ? 'Atualizando…' : 'Atualizar'}
        </button>
      </Cabecalho>

      {erro && <ErroCarga mensagem={erro} aoTentar={atualizar} />}
      {!erro && !quadro && carregando && <Carregando />}

      {!erro && quadro && listaEtapas && itens && itens.length === 0 && (
        <Vazio titulo="Nenhum lote cadastrado ainda.">Quando houver lotes, eles aparecem aqui, na etapa em que estão.</Vazio>
      )}

      {!erro && quadro && listaEtapas && itens && itens.length > 0 && (
        <div className={`pilha ${carregando ? 'recarregando' : ''}`} aria-busy={carregando}>
          {quadro.semColuna > 0 && (
            <Faixa tipo="alerta" papel="status">
              {quadro.semColuna === 1
                ? '1 lote em andamento está numa etapa que não faz parte da lista de etapas e por isso não aparece no quadro.'
                : `${inteiro(quadro.semColuna)} lotes em andamento estão numa etapa que não faz parte da lista de etapas e por isso não aparecem no quadro.`}{' '}
              Eles continuam na tabela abaixo.
            </Faixa>
          )}

          <section aria-labelledby="titulo-quadro">
            <div className="cartao-topo">
              <h2 id="titulo-quadro">Lotes por etapa</h2>
              <span className="nota-discreta">
                {inteiro(itens.length - quadro.concluidos.length)} em andamento · {inteiro(quadro.concluidos.length)}{' '}
                {quadro.concluidos.length === 1 ? 'concluído' : 'concluídos'} · {inteiro(comNc)} com NC aberta
              </span>
            </div>
            <ol className="quadro" aria-label="Etapas do processo, na ordem">
              {listaEtapas.map((etapa, indice) => (
                <ColunaQuadro
                  key={etapa.chave}
                  passo={indice + 1}
                  titulo={etapa.curto}
                  nomeCompleto={etapa.nome}
                  apoio={apoioDaEtapa(etapa)}
                  lotes={quadro.porEtapa.get(etapa.chave) ?? []}
                />
              ))}
              <ColunaQuadro
                titulo="Concluídos"
                apoio="Todas as etapas aprovadas"
                lotes={quadro.concluidos}
                classe="quadro-concluidos"
                limite={LIMITE_CONCLUIDOS}
              />
            </ol>
          </section>

          <section className="cartao" aria-labelledby="titulo-lotes">
            <h2 id="titulo-lotes">Todos os lotes</h2>
            <div className="filtros" role="search" aria-label="Filtros dos lotes">
              <div className="campo campo-busca">
                <label htmlFor="lotes-busca">Buscar</label>
                <input
                  id="lotes-busca"
                  type="search"
                  placeholder="Número do lote, OP ou corrida"
                  autoComplete="off"
                  spellCheck={false}
                  value={busca}
                  onChange={(e) => setBusca(e.target.value)}
                />
              </div>
              <div className="campo">
                <span className="rotulo" id="rotulo-tipo">
                  Tipo
                </span>
                <Segmentos idRotulo="rotulo-tipo" opcoes={OPCOES_TIPO} valor={tipo} aoMudar={setTipo} />
              </div>
              <div className="campo">
                <span className="rotulo" id="rotulo-situacao">
                  Situação
                </span>
                <Segmentos idRotulo="rotulo-situacao" opcoes={OPCOES_SITUACAO} valor={situacao} aoMudar={setSituacao} />
              </div>
              {temFiltro && (
                <button
                  type="button"
                  className="botao-link"
                  onClick={() => {
                    setBusca('');
                    setTipo('todos');
                    setSituacao('todos');
                  }}
                >
                  Limpar filtros
                </button>
              )}
            </div>
            <p className="contagem" role="status">
              {temFiltro
                ? `${inteiro(filtrados.length)} de ${inteiro(itens.length)} lotes`
                : `${inteiro(itens.length)} ${itens.length === 1 ? 'lote' : 'lotes'}`}
            </p>
            {filtrados.length === 0 ? (
              <Vazio titulo="Nenhum lote com esses filtros." />
            ) : (
              <TabelaOrdenavel
                legenda="Todos os lotes"
                colunas={COLUNAS}
                linhas={filtrados}
                chaveLinha={(l) => l.id}
                ordemInicial={{ chave: 'criado', direcao: 'desc' }}
                classeLinha={(l) => (l.nc_aberta ? 'linha-critica' : undefined)}
                limite={LIMITE_TABELA}
              />
            )}
          </section>
        </div>
      )}
    </>
  );
}
