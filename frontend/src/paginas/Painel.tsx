import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../componentes/Estados';
import { BotaoNovoLote } from './lotes/BotaoNovoLote';
import { SeloNcAberta, SeloTipo } from '../componentes/Selos';
import { TabelaOrdenavel, type Coluna } from '../componentes/Tabela';
import { api, baixarArquivo, mensagemDeErro } from '../lib/api';
import { useAvisos } from '../lib/avisos';
import { contemTermos, dataHoraLocal, haDias, inteiro, pecas, TRACO } from '../lib/formato';
import type { Etapa, ListaLotes, LoteResumo, TipoLote } from '../lib/tipos';
import { useCarga } from '../lib/useCarga';
import type { NivelAlerta, Pendencia, RespostaPainel } from './paineis/tipos';
import './paineis/painel.css';

const TIPOS: TipoLote[] = ['PIN', 'BOX', 'ARK'];
/** A coluna "Concluídos" só cresce: mostra os mais recentes e um botão para ver todos. */
const LIMITE_CONCLUIDOS = 8;
const LIMITE_TABELA = 50;
/** Lista de databooks já enviados ao cliente (módulo Databooks). */
const LINK_ENVIADOS = '/databooks?tab=enviados';

type FiltroTipo = 'todos' | TipoLote;
type FiltroSituacao = 'todos' | 'andamento' | 'concluidos' | 'enviados';

const OPCOES_TIPO: { valor: FiltroTipo; rotulo: string }[] = [
  { valor: 'todos', rotulo: 'Todos' },
  ...TIPOS.map((t) => ({ valor: t, rotulo: t })),
];

const OPCOES_SITUACAO: { valor: FiltroSituacao; rotulo: string }[] = [
  { valor: 'todos', rotulo: 'Todos' },
  { valor: 'andamento', rotulo: 'Em andamento' },
  { valor: 'concluidos', rotulo: 'Concluídos' },
  { valor: 'enviados', rotulo: 'Enviado-DB' },
];

/** O que o painel sabe de cada lote além do /lotes: databook enviado e pronto para avançar. */
interface Marcas {
  enviados: Set<number>;
  prontos: Set<number>;
}

const SEM_MARCAS: Marcas = { enviados: new Set(), prontos: new Set() };

// ---------------------------------------------------------------- ações pendentes (alertas)

/** Ícone de cada alerta (traço 24×24, cor do texto). */
const ICONE_ALERTA: Record<string, ReactNode> = {
  materia_prima: (
    <>
      <path d="M4 8l8-4 8 4-8 4z" />
      <path d="M4 8v8l8 4 8-4V8" />
    </>
  ),
  parados: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  nc: (
    <>
      <path d="M12 3 2 20h20z" />
      <path d="M12 10v4M12 17h.01" />
    </>
  ),
  prontos: <path d="M5 12l5 5 9-10" />,
  sem_databook: (
    <>
      <path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" />
      <path d="M5 17a3 3 0 0 1 3-3h11" />
    </>
  ),
  databook_sem_envio: (
    <>
      <path d="M3 6h18v12H3z" />
      <path d="M3 6l9 7 9-7" />
    </>
  ),
  calibracao: <path d="M14.5 5.5a4 4 0 0 0-5 5L4 16l4 4 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-3-1-1-3z" />,
  calibracao_vencida: <path d="M14.5 5.5a4 4 0 0 0-5 5L4 16l4 4 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-3-1-1-3z" />,
  carga_tt: <path d="M12 3c1 3 4 4.5 4 8.5a4 4 0 0 1-8 0c0-2 1-3 1.5-4 .5 1.5 1.5 2 2 2 .5-2-.5-4.5.5-6.5zM5 21h14" />,
  envio_prestador: (
    <>
      <path d="M3 7l9-4 9 4v10l-9 4-9-4z" />
      <path d="M3 7l9 4 9-4M12 11v10" />
    </>
  ),
};

const NOME_NIVEL: Record<NivelAlerta, string> = { erro: 'Urgente', alerta: 'Atenção', info: 'A fazer', ok: 'Pronto' };

function Alertas({ pendencias }: { pendencias: Pendencia[] }) {
  if (pendencias.length === 0) return null;
  return (
    <section className="cartao painel-alertas" aria-labelledby="painel-titulo-alertas">
      <h2 id="painel-titulo-alertas">Ações pendentes ({inteiro(pendencias.length)})</h2>
      <ul className="painel-alertas-lista">
        {pendencias.map((p) => (
          <li key={p.chave}>
            <Link to={p.link} className={`painel-alerta painel-alerta-${p.nivel}`}>
              <svg className="ic painel-alerta-icone" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                {ICONE_ALERTA[p.chave] ?? <circle cx="12" cy="12" r="9" />}
              </svg>
              <span className="painel-alerta-texto">
                <span className="so-leitor">{NOME_NIVEL[p.nivel]}: </span>
                {p.texto}
              </span>
              <span className="painel-alerta-acao" aria-hidden="true">
                {p.acao} →
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------- quadro (kanban)

interface Quadro {
  /** Lotes em andamento, pela chave da etapa em que estão. */
  porEtapa: Map<string, LoteResumo[]>;
  /** Concluídos que ainda não tiveram o databook enviado ao cliente. */
  concluidos: LoteResumo[];
  /** Concluídos com databook já enviado (Enviado-DB). */
  enviados: LoteResumo[];
  /** Lotes em andamento cuja etapa atual não está na lista de etapas (não deveria acontecer). */
  semColuna: number;
}

function montarQuadro(etapas: Etapa[], lotes: LoteResumo[], marcas: Marcas): Quadro {
  const porEtapa = new Map<string, LoteResumo[]>(etapas.map((e) => [e.chave, []]));
  const concluidos: LoteResumo[] = [];
  const enviados: LoteResumo[] = [];
  let semColuna = 0;

  for (const lote of lotes) {
    if (lote.concluido) {
      (marcas.enviados.has(lote.id) ? enviados : concluidos).push(lote);
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

  return { porEtapa, concluidos, enviados, semColuna };
}

/** "Controle de qualidade · só PIN e BOX" (quando a etapa não vale para todos os tipos). */
function apoioDaEtapa(etapa: Etapa): string {
  if (etapa.tipos.length === 0 || etapa.tipos.length >= TIPOS.length) return etapa.setor;
  return `${etapa.setor} · só ${etapa.tipos.join(' e ')}`;
}

function CartaoLote({ lote, pronto }: { lote: LoteResumo; pronto: boolean }) {
  return (
    <Link to={`/lotes/${lote.id}`} className={`cartao-lote ${lote.nc_aberta ? 'cartao-lote-nc' : ''} ${pronto ? 'painel-cartao-pronto' : ''}`}>
      <span className="cartao-lote-topo">
        <SeloTipo tipo={lote.tipo} />
        <span className="cartao-lote-numero">{lote.numero}</span>
      </span>
      <span>
        OP {lote.op} · {pecas(lote.qtd)}
      </span>
      {(lote.dias_na_etapa !== null || lote.nc_aberta || pronto) && (
        <span className="cartao-lote-linha">
          <span className="cartao-lote-tempo">{lote.dias_na_etapa !== null && !lote.concluido ? haDias(lote.dias_na_etapa) : ''}</span>
          {lote.nc_aberta && <SeloNcAberta curto />}
          {pronto && !lote.nc_aberta && <span className="selo selo-ok painel-selo-pronto">Pronto p/ avançar</span>}
        </span>
      )}
    </Link>
  );
}

interface PropsColuna {
  /** Posição da etapa no processo (as colunas finais não têm). */
  passo?: number;
  /** id da coluna, para os links "/#etapa-<chave>" (ex.: o cartão de TT do início). */
  id?: string;
  titulo: string;
  nomeCompleto?: string;
  apoio: string;
  lotes: LoteResumo[];
  prontos: Set<number>;
  classe?: string;
  /** Mostra só os primeiros N, com um botão para ver todos. */
  limite?: number;
}

function ColunaQuadro({ passo, id, titulo, nomeCompleto, apoio, lotes, prontos, classe, limite }: PropsColuna) {
  const [verTodos, setVerTodos] = useState(false);
  const visiveis = limite !== undefined && !verTodos ? lotes.slice(0, limite) : lotes;

  return (
    <li id={id} className={`quadro-coluna ${classe ?? ''}`}>
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
              <CartaoLote lote={lote} pronto={prontos.has(lote.id)} />
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

/** Coluna "Enviado-DB": os lotes cujo databook já foi enviado, agregados por tipo (como no sistema antigo). */
function ColunaEnviados({ lotes }: { lotes: LoteResumo[] }) {
  const pecasTotal = lotes.reduce((s, l) => s + l.qtd, 0);
  return (
    <li className="quadro-coluna painel-coluna-enviados">
      <div className="quadro-topo">
        <div className="quadro-titulo">
          <h3>Enviado-DB</h3>
          <span className="quadro-contagem">
            {inteiro(lotes.length)}
            <span className="so-leitor">{lotes.length === 1 ? ' lote' : ' lotes'}</span>
          </span>
        </div>
        <span className="quadro-setor">Databook enviado ao cliente</span>
      </div>
      {lotes.length === 0 ? (
        <p className="quadro-vazio">Nenhum databook enviado ainda.</p>
      ) : (
        <>
          <ul className="quadro-cartoes">
            {TIPOS.map((tipo) => {
              const n = lotes.filter((l) => l.tipo === tipo).length;
              if (n === 0) return null;
              return (
                <li key={tipo}>
                  <Link
                    to={`${LINK_ENVIADOS}&tipo=${tipo}`}
                    className="painel-chip-enviado"
                    title={`Abrir a lista de databooks enviados de ${tipo}`}
                  >
                    <SeloTipo tipo={tipo} />
                    <span className="painel-chip-contagem">
                      {inteiro(n)}
                      <span className="so-leitor">{n === 1 ? ' lote' : ' lotes'}</span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          <p className="quadro-vazio">{pecas(pecasTotal)} · clique para abrir a lista</p>
        </>
      )}
    </li>
  );
}

// ---------------------------------------------------------------- tabela de lotes

function colunas(marcas: Marcas): Coluna<LoteResumo>[] {
  return [
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
      // Ordena pela posição no processo; os concluídos ficam depois da última etapa (e os enviados por último)
      valor: (l) => (l.concluido ? Number.MAX_SAFE_INTEGER - (marcas.enviados.has(l.id) ? 0 : 1) : (l.etapa_atual?.indice ?? null)),
      celula: (l) => {
        if (l.concluido) {
          return marcas.enviados.has(l.id) ? (
            <span className="selo painel-selo-enviado">Concluído · Enviado-DB</span>
          ) : (
            <span className="selo selo-ok">Concluído</span>
          );
        }
        if (!l.etapa_atual) return TRACO;
        return (
          <>
            {l.etapa_atual.curto}
            <span className="sub">{marcas.prontos.has(l.id) && !l.nc_aberta ? 'pronto para avançar' : l.etapa_atual.setor}</span>
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
}

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

// ---------------------------------------------------------------- resumo e exportação

function Resumo({ painel }: { painel: RespostaPainel }) {
  const r = painel.resumo;
  return (
    <div className="painel-resumo" role="list" aria-label="Resumo dos lotes">
      <div className="cartao-numero" role="listitem">
        <span className="cartao-rotulo">Lotes</span>
        <span className="cartao-valor">{inteiro(r.total)}</span>
      </div>
      <div className="cartao-numero" role="listitem">
        <span className="cartao-rotulo">Em andamento</span>
        <span className="cartao-valor">{inteiro(r.andamento)}</span>
      </div>
      <div className={`cartao-numero ${r.nc > 0 ? 'painel-numero-erro' : ''}`} role="listitem">
        <span className="cartao-rotulo">Com não conformidade</span>
        <span className="cartao-valor">{inteiro(r.nc)}</span>
      </div>
      <div className="cartao-numero painel-numero-ok" role="listitem">
        <span className="cartao-rotulo">Concluídos</span>
        <span className="cartao-valor">{inteiro(r.concluidos)}</span>
        <span className="cartao-apoio">databook ainda não enviado</span>
      </div>
      <Link to={LINK_ENVIADOS} className="cartao-numero painel-numero-enviado" role="listitem" title="Ver a lista de databooks enviados">
        <span className="cartao-rotulo">Enviados-DB</span>
        <span className="cartao-valor">{inteiro(r.enviados)}</span>
        <span className="cartao-apoio">{pecas(painel.enviados.pecas)} · ver a lista</span>
      </Link>
    </div>
  );
}

function BotaoExportar() {
  const avisos = useAvisos();
  const [gerando, setGerando] = useState(false);
  async function exportar() {
    setGerando(true);
    try {
      await baixarArquivo('/painel/exportar.xlsx');
    } catch (erro) {
      avisos.erro(`Não foi possível gerar a planilha: ${mensagemDeErro(erro)}`);
    } finally {
      setGerando(false);
    }
  }
  return (
    <button type="button" className="botao" onClick={() => void exportar()} disabled={gerando} title="Lista completa de lotes em Excel (para reuniões)">
      {gerando ? 'Gerando planilha…' : 'Exportar Excel'}
    </button>
  );
}

// ---------------------------------------------------------------- tela

export function Painel() {
  const etapas = useCarga<Etapa[]>((sinal) => api('/etapas', { sinal }), []);
  const lotes = useCarga<ListaLotes>((sinal) => api('/lotes', { sinal }), []);
  // Alertas, resumo e Enviado-DB: se falhar, o quadro continua funcionando (só sem esses extras)
  const extras = useCarga<RespostaPainel>((sinal) => api('/painel', { sinal }), []);
  const [busca, setBusca] = useState('');
  const [tipo, setTipo] = useState<FiltroTipo>('todos');
  const [situacao, setSituacao] = useState<FiltroSituacao>('todos');
  const local = useLocation();

  const listaEtapas = etapas.dados;
  const itens = lotes.dados?.itens;
  const painel = extras.dados;
  const erro = etapas.erro ?? lotes.erro;
  const carregando = etapas.carregando || lotes.carregando;

  const marcas = useMemo<Marcas>(
    () => (painel ? { enviados: new Set(painel.enviados.lote_ids), prontos: new Set(painel.prontos) } : SEM_MARCAS),
    [painel],
  );
  const quadro = useMemo(
    () => (listaEtapas && itens ? montarQuadro(listaEtapas, itens, marcas) : null),
    [listaEtapas, itens, marcas],
  );
  const colunasTabela = useMemo(() => colunas(marcas), [marcas]);

  const filtrados = useMemo(
    () =>
      (itens ?? []).filter((l) => {
        if (tipo !== 'todos' && l.tipo !== tipo) return false;
        if (situacao === 'andamento' && l.concluido) return false;
        if (situacao === 'concluidos' && (!l.concluido || marcas.enviados.has(l.id))) return false;
        if (situacao === 'enviados' && !marcas.enviados.has(l.id)) return false;
        return contemTermos(`${l.numero} ${l.op} ${l.corrida}`, busca);
      }),
    [itens, busca, tipo, situacao, marcas],
  );

  // Link "/#etapa-<chave>" (ex.: cartão "Tratamento Térmico" do início): leva até a coluna da etapa
  const ancora = local.hash.slice(1);
  useEffect(() => {
    if (!ancora || !quadro) return;
    const coluna = document.getElementById(ancora);
    coluna?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }, [ancora, quadro]);

  function atualizar() {
    etapas.recarregar();
    lotes.recarregar();
    extras.recarregar();
  }

  const temFiltro = busca.trim() !== '' || tipo !== 'todos' || situacao !== 'todos';
  const comNc = itens ? itens.filter((l) => l.nc_aberta).length : 0;

  return (
    <>
      <Cabecalho titulo="Painel" apoio="Onde está cada lote no processo de fabricação.">
        <button type="button" className="botao" onClick={atualizar} disabled={carregando}>
          {carregando ? 'Atualizando…' : 'Atualizar'}
        </button>
        <Link to="/dashboard" className="botao">
          Abrir dashboard
        </Link>
        <BotaoExportar />
        <BotaoNovoLote aoCriar={atualizar} />
      </Cabecalho>

      {erro && <ErroCarga mensagem={erro} aoTentar={atualizar} />}
      {!erro && !quadro && carregando && <Carregando />}

      {!erro && painel && <Alertas pendencias={painel.pendencias} />}
      {!erro && extras.erro && (
        <Faixa tipo="alerta" papel="status">
          Não foi possível carregar as ações pendentes e o resumo ({extras.erro}). O quadro abaixo continua valendo.{' '}
          <button type="button" className="botao-link" onClick={extras.recarregar}>
            Tentar de novo
          </button>
        </Faixa>
      )}

      {!erro && quadro && listaEtapas && itens && itens.length === 0 && (
        <Vazio titulo="Nenhum lote cadastrado ainda.">Quando houver lotes, eles aparecem aqui, na etapa em que estão.</Vazio>
      )}

      {!erro && quadro && listaEtapas && itens && itens.length > 0 && (
        <div className={`pilha ${carregando ? 'recarregando' : ''}`} aria-busy={carregando}>
          {painel && <Resumo painel={painel} />}

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
                {inteiro(itens.length - quadro.concluidos.length - quadro.enviados.length)} em andamento · {inteiro(quadro.concluidos.length)}{' '}
                {quadro.concluidos.length === 1 ? 'concluído' : 'concluídos'} · {inteiro(quadro.enviados.length)} Enviado-DB · {inteiro(comNc)} com NC
                aberta
              </span>
            </div>
            <ol className="quadro" aria-label="Etapas do processo, na ordem">
              {listaEtapas.map((etapa, indice) => (
                <ColunaQuadro
                  key={etapa.chave}
                  id={`etapa-${etapa.chave}`}
                  passo={indice + 1}
                  titulo={etapa.curto}
                  nomeCompleto={etapa.nome}
                  apoio={apoioDaEtapa(etapa)}
                  lotes={quadro.porEtapa.get(etapa.chave) ?? []}
                  prontos={marcas.prontos}
                />
              ))}
              <ColunaQuadro
                id="etapa-concluidos"
                titulo="Concluídos"
                apoio="Databook pronto · ainda não enviado"
                lotes={quadro.concluidos}
                prontos={marcas.prontos}
                classe="quadro-concluidos"
                limite={LIMITE_CONCLUIDOS}
              />
              {painel && <ColunaEnviados lotes={quadro.enviados} />}
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
                <Segmentos
                  idRotulo="rotulo-situacao"
                  opcoes={painel ? OPCOES_SITUACAO : OPCOES_SITUACAO.filter((o) => o.valor !== 'enviados')}
                  valor={situacao}
                  aoMudar={setSituacao}
                />
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
                colunas={colunasTabela}
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
