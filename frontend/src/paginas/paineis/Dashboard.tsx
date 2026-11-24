/**
 * Dashboard: a fábrica em um relance (legado: rota /dashboard e TEMPLATES["dashboard"]).
 * Cada setor é um estágio do processo; cada bolha é um lote (cor = tipo, tamanho = quantidade de peças).
 * O setor "Enviado-DB" aparece agregado: uma bolha por tipo, com o total de lotes, que abre a lista de
 * databooks enviados.
 */
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Vazio } from '../../componentes/Estados';
import { SeloNcAberta, SeloTipo } from '../../componentes/Selos';
import { TabelaOrdenavel, type Coluna } from '../../componentes/Tabela';
import { api } from '../../lib/api';
import { contemTermos, haDias, inteiro, TRACO } from '../../lib/formato';
import type { TipoLote } from '../../lib/tipos';
import { useCarga } from '../../lib/useCarga';
import { CartaoNumero, CartoesTotais, inclui, linkEnviados, OPCOES_TIPO, pecasTexto, Segmentos, SugestoesCadastro, TIPOS, type FiltroTipo } from './comuns';
import { GraficosResumo } from './Kpis';
import type { LoteDashboard, RespostaDashboard, Situacao } from './tipos';

type FiltroSituacao = '' | Situacao;

const OPCOES_SITUACAO: { valor: FiltroSituacao; rotulo: string }[] = [
  { valor: '', rotulo: 'Todos' },
  { valor: 'andamento', rotulo: 'Em andamento' },
  { valor: 'concluido', rotulo: 'Concluído' },
  { valor: 'enviado', rotulo: 'Enviado-DB' },
];

export function SeloSituacao({ situacao }: { situacao: Situacao }) {
  if (situacao === 'enviado') return <span className="selo pn-selo-enviado">Enviado-DB</span>;
  if (situacao === 'concluido') return <span className="selo selo-ok">Concluído</span>;
  return <span className="selo selo-andamento">Em andamento</span>;
}

const COLUNAS: Coluna<LoteDashboard>[] = [
  { chave: 'op', titulo: 'OP', mono: true, valor: (l) => l.op },
  {
    chave: 'numero',
    titulo: 'Nº do lote',
    mono: true,
    valor: (l) => l.numero,
    celula: (l) => (
      <Link to={`/lotes/${l.id}`} className="link-forte">
        {l.numero}
      </Link>
    ),
  },
  { chave: 'tipo', titulo: 'Tipo', valor: (l) => l.tipo, celula: (l) => <SeloTipo tipo={l.tipo} /> },
  { chave: 'coditem', titulo: 'CODITEM', mono: true, valor: (l) => l.coditem || null },
  { chave: 'descricao', titulo: 'Descrição do produto', valor: (l) => l.descricao || null },
  { chave: 'qtd', titulo: 'Qtd', numerica: true, valor: (l) => l.qtd, celula: (l) => inteiro(l.qtd) },
  {
    chave: 'etapa',
    titulo: 'Etapa atual',
    valor: (l) => l.etapa,
    celula: (l) => (
      <>
        {l.etapa}
        {l.situacao === 'andamento' && <span className="sub">{haDias(l.dias)}</span>}
      </>
    ),
  },
  {
    chave: 'situacao',
    titulo: 'Status',
    valor: (l) => l.situacao,
    celula: (l) => (
      <>
        <SeloSituacao situacao={l.situacao} /> {l.nc && <SeloNcAberta curto />}
      </>
    ),
  },
];

function tamanhoBolha(qtd: number, maior: number): number {
  return 34 + Math.floor((qtd / Math.max(maior, 1)) * 30);
}

function Bolha({ lote, maior }: { lote: LoteDashboard; maior: number }) {
  const tamanho = tamanhoBolha(lote.qtd, maior);
  const dias = lote.dias ?? 0;
  const dica = [
    `OP ${lote.op} · Lote ${lote.numero}`,
    `${lote.tipo} · ${pecasTexto(lote.qtd)}`,
    `Item: ${lote.coditem || TRACO}`,
    `Etapa: ${lote.etapa}`,
    lote.situacao === 'andamento' ? `${dias} ${dias === 1 ? 'dia' : 'dias'} nesta etapa` : '',
    lote.nc ? 'Não conformidade aberta' : '',
  ]
    .filter(Boolean)
    .join('\n');
  const classes = [
    'dash-bolha',
    `dash-bolha-${lote.tipo.toLowerCase()}`,
    lote.situacao === 'concluido' ? 'dash-bolha-feita' : '',
    lote.nc ? 'dash-bolha-nc' : '',
  ].join(' ');
  return (
    <Link
      to={`/lotes/${lote.id}`}
      className={classes}
      style={{ width: tamanho, height: tamanho, fontSize: Math.floor(tamanho * 0.32) }}
      data-dica={dica}
      aria-label={dica.replace(/\n/g, '. ')}
    >
      <b aria-hidden="true">{lote.op.length > 1 ? lote.op.slice(-2) : lote.op}</b>
      <small aria-hidden="true">{lote.tipo}</small>
    </Link>
  );
}

/** Setor "Enviado-DB": uma bolha por tipo com o total de lotes; abre a lista de databooks enviados. */
function BolhasEnviados({ lotes }: { lotes: LoteDashboard[] }) {
  return (
    <>
      {TIPOS.map((tipo: TipoLote) => {
        const doTipo = lotes.filter((l) => l.tipo === tipo);
        if (doTipo.length === 0) return null;
        const pecas = doTipo.reduce((s, l) => s + l.qtd, 0);
        const dica = `${doTipo.length} ${doTipo.length === 1 ? 'lote' : 'lotes'} ${tipo} Enviado-DB (${pecasTexto(pecas)})\nClique para abrir a lista de ${tipo}`;
        return (
          <Link
            key={tipo}
            to={linkEnviados(tipo)}
            className={`dash-bolha dash-bolha-${tipo.toLowerCase()}`}
            style={{ width: 72, height: 72, fontSize: 22 }}
            data-dica={dica}
            aria-label={dica.replace(/\n/g, '. ')}
          >
            <b aria-hidden="true">{doTipo.length}</b>
            <small aria-hidden="true">{tipo}</small>
          </Link>
        );
      })}
    </>
  );
}

function CartaoSetor({ setor, lotes, maior }: { setor: string; lotes: LoteDashboard[]; maior: number }) {
  const enviado = setor === 'Enviado-DB';
  const concluido = setor === 'Concluído';
  const pecas = lotes.reduce((s, l) => s + l.qtd, 0);
  // Quem está parado há mais tempo aparece primeiro
  const ordenados = [...lotes].sort((a, b) => (b.dias ?? -1) - (a.dias ?? -1));
  return (
    <section className={`cartao dash-setor ${enviado ? 'dash-setor-enviado' : concluido ? 'dash-setor-concluido' : ''}`}>
      <div className="dash-setor-topo">
        <div>
          <h3>{setor}</h3>
          <span className="nota-discreta">
            {inteiro(lotes.length)} {lotes.length === 1 ? 'lote' : 'lotes'} · {pecasTexto(pecas)}
          </span>
        </div>
        <span className="dash-setor-n" aria-hidden="true">
          {inteiro(lotes.length)}
          <small>{lotes.length === 1 ? 'lote' : 'lotes'}</small>
        </span>
      </div>
      <div className="dash-bolhas">{enviado ? <BolhasEnviados lotes={lotes} /> : ordenados.map((l) => <Bolha key={l.id} lote={l} maior={maior} />)}</div>
      {enviado && <span className="nota-discreta">Clique numa bolha para abrir a lista de databooks enviados daquele tipo.</span>}
    </section>
  );
}

export function Dashboard() {
  const carga = useCarga<RespostaDashboard>((sinal) => api('/dashboard', { sinal }), []);
  const [tipo, setTipo] = useState<FiltroTipo>('');
  const [op, setOp] = useState('');
  const [coditem, setCoditem] = useState('');
  const [descricao, setDescricao] = useState('');
  const [situacao, setSituacao] = useState<FiltroSituacao>('');
  const dados = carga.dados;

  const filtrados = useMemo(
    () =>
      (dados?.lotes ?? []).filter(
        (l) =>
          (!tipo || l.tipo === tipo) &&
          inclui(l.op, op) &&
          inclui(l.coditem, coditem) &&
          contemTermos(l.descricao, descricao) &&
          (!situacao || l.situacao === situacao),
      ),
    [dados, tipo, op, coditem, descricao, situacao],
  );
  const porSetor = useMemo(() => {
    const mapa = new Map<string, LoteDashboard[]>();
    for (const l of filtrados) mapa.set(l.setor, [...(mapa.get(l.setor) ?? []), l]);
    return mapa;
  }, [filtrados]);

  const temFiltro = tipo !== '' || op !== '' || coditem !== '' || descricao !== '' || situacao !== '';
  function limpar() {
    setTipo('');
    setOp('');
    setCoditem('');
    setDescricao('');
    setSituacao('');
  }
  const pecasFiltradas = filtrados.reduce((s, l) => s + l.qtd, 0);

  return (
    <>
      <Cabecalho titulo="Dashboard" apoio="A fábrica em um relance: cada setor é um estágio do processo.">
        <button type="button" className="botao" onClick={carga.recarregar} disabled={carga.carregando}>
          {carga.carregando ? 'Atualizando…' : 'Atualizar'}
        </button>
      </Cabecalho>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
      {!dados && carga.carregando && <Carregando />}
      {dados && dados.lotes.length === 0 && (
        <Vazio titulo="Nenhum lote cadastrado ainda.">
          <Link to="/">Volte ao painel</Link> e crie o primeiro.
        </Vazio>
      )}

      {dados && dados.lotes.length > 0 && (
        <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`} aria-busy={carga.carregando}>
          <CartoesTotais
            totais={dados.totais}
            tendencias={dados.tendencias}
            primeiro={<CartaoNumero rotulo="Lotes totais" valor={inteiro(dados.totais.lotes)} apoio={pecasTexto(dados.totais.pecas)} />}
          />

          {dados.kpis && (
            <details className="pn-recolhivel">
              <summary>
                KPIs gerenciais
                <span className="nota-discreta">
                  clique para abrir · <Link to="/kpis">ver em tela cheia, com filtros</Link>
                </span>
              </summary>
              <div className="pn-recolhivel-corpo">
                <GraficosResumo kpis={dados.kpis} totais={dados.totais} />
              </div>
            </details>
          )}

          <div className="filtros" role="search" aria-label="Filtros do dashboard">
            <div className="campo">
              <span className="rotulo" id="dash-rotulo-tipo">
                Tipo
              </span>
              <Segmentos idRotulo="dash-rotulo-tipo" opcoes={OPCOES_TIPO} valor={tipo} aoMudar={setTipo} />
            </div>
            <div className="campo">
              <label htmlFor="dash-op">Nº da OP</label>
              <input id="dash-op" type="search" className="mono" list="dash-ops" autoComplete="off" value={op} onChange={(e) => setOp(e.target.value)} />
            </div>
            <div className="campo">
              <label htmlFor="dash-cod">CODITEM</label>
              <input id="dash-cod" type="search" className="mono" list="dash-cods" autoComplete="off" value={coditem} onChange={(e) => setCoditem(e.target.value)} />
            </div>
            <div className="campo campo-busca">
              <label htmlFor="dash-desc">Descrição do produto</label>
              <input id="dash-desc" type="search" autoComplete="off" value={descricao} onChange={(e) => setDescricao(e.target.value)} />
            </div>
            <div className="campo">
              <label htmlFor="dash-situacao">Status</label>
              <select id="dash-situacao" value={situacao} onChange={(e) => setSituacao(e.target.value as FiltroSituacao)}>
                {OPCOES_SITUACAO.map((o) => (
                  <option key={o.valor} value={o.valor}>
                    {o.rotulo}
                  </option>
                ))}
              </select>
            </div>
            {temFiltro && (
              <button type="button" className="botao-link" onClick={limpar}>
                Limpar filtros
              </button>
            )}
            <span className="contagem filtros-fim" role="status">
              {inteiro(filtrados.length)} {filtrados.length === 1 ? 'lote visível' : 'lotes visíveis'} · {pecasTexto(pecasFiltradas)}
            </span>
            <SugestoesCadastro idOps="dash-ops" idItens="dash-cods" ops={dados.ops} />
          </div>

          <div className="dash-legenda">
            {TIPOS.map((t) => (
              <span key={t}>
                <span className="dash-ponto" style={{ background: `var(--graf-${t.toLowerCase()})` }} aria-hidden="true" />
                {t}
              </span>
            ))}
            <span className="nota-discreta">
              Tamanho da bolha = quantidade de peças · bolha clara = concluído · contorno vermelho = não conformidade aberta. Clique para abrir o lote.
            </span>
          </div>

          {filtrados.length === 0 ? (
            <Vazio titulo="Nenhum lote com esses filtros." />
          ) : (
            <div className="dash-setores">
              {dados.setores
                .filter((s) => (porSetor.get(s)?.length ?? 0) > 0)
                .map((s) => (
                  <CartaoSetor key={s} setor={s} lotes={porSetor.get(s) ?? []} maior={dados.maior_qtd} />
                ))}
            </div>
          )}

          <section className="cartao" aria-labelledby="dash-titulo-lista">
            <div className="cartao-topo">
              <h2 id="dash-titulo-lista">Lista de lotes</h2>
              <span className="nota-discreta">
                {temFiltro ? 'Com os filtros acima' : 'Todos os lotes'} · total de peças: <strong className="mono">{inteiro(pecasFiltradas)}</strong> em{' '}
                {inteiro(filtrados.length)} {filtrados.length === 1 ? 'lote' : 'lotes'}
              </span>
            </div>
            {filtrados.length > 0 && (
              <TabelaOrdenavel
                legenda="Lotes do dashboard"
                colunas={COLUNAS}
                linhas={filtrados}
                chaveLinha={(l) => l.id}
                ordemInicial={{ chave: 'numero', direcao: 'asc' }}
                classeLinha={(l) => (l.nc ? 'linha-critica' : undefined)}
                limite={50}
              />
            )}
          </section>
        </div>
      )}
    </>
  );
}
