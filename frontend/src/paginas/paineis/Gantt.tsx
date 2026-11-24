/**
 * Gantt: linha do processo por OP (legado: rota /gantt e TEMPLATES["gantt"]).
 * Uma linha por OP do cadastro (com o último lote dela), uma coluna por etapa. Por padrão esconde as OPs
 * cujo databook já foi enviado ao cliente (Enviado-DB).
 */
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api } from '../../lib/api';
import { contemTermos, inteiro, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import { CartaoNumero, CartoesTotais, inclui, OPCOES_TIPO, Segmentos, SugestoesCadastro, type FiltroTipo } from './comuns';
import type { LinhaGantt, RespostaGantt, SituacaoCelula } from './tipos';

type FiltroStatus = 'ativos' | 'andamento' | 'concluido' | 'enviado' | 'semlote' | '';

const OPCOES_STATUS: { valor: FiltroStatus; rotulo: string }[] = [
  { valor: 'ativos', rotulo: 'Ativos (esconde os Enviados-DB)' },
  { valor: 'andamento', rotulo: 'Em andamento' },
  { valor: 'concluido', rotulo: 'Concluído (sem enviar)' },
  { valor: 'enviado', rotulo: 'Enviado-DB' },
  { valor: 'semlote', rotulo: 'Sem lote iniciado' },
  { valor: '', rotulo: 'Todos (inclusive enviados)' },
];

const LEGENDA: { s: SituacaoCelula; rotulo: string }[] = [
  { s: 'aprovada', rotulo: 'Aprovada (com a data)' },
  { s: 'atual', rotulo: 'Em andamento' },
  { s: 'reprovada', rotulo: 'Reprovada (não conformidade aberta)' },
  { s: 'pulada', rotulo: 'Pulada' },
  { s: 'futura', rotulo: 'Futura' },
  { s: 'nao_iniciado', rotulo: 'Lote não iniciado' },
  { s: 'na', rotulo: 'Não se aplica ao tipo' },
];

const NOME_CELULA: Record<SituacaoCelula, string> = {
  aprovada: 'aprovada',
  atual: 'em andamento',
  reprovada: 'reprovada',
  pulada: 'pulada',
  futura: 'futura',
  nao_iniciado: 'lote não iniciado',
  na: 'não se aplica',
};

function passaStatus(linha: LinhaGantt, status: FiltroStatus): boolean {
  if (status === 'ativos') return linha.situacao !== 'enviado';
  return status === '' || linha.situacao === status;
}

function LinhaTabela({ linha, etapas }: { linha: LinhaGantt; etapas: RespostaGantt['etapas'] }) {
  return (
    <tr>
      <th scope="row" className="gantt-op">
        <strong className="mono">OP {linha.op}</strong>
        {linha.lote ? (
          <>
            {' '}
            · <Link to={`/lotes/${linha.lote.id}`} className="mono">Lote {linha.lote.numero}</Link>
          </>
        ) : (
          <span className="nota-discreta"> (sem lote)</span>
        )}
        <span className="gantt-op-desc" title={`${linha.coditem || TRACO} · ${linha.descricao || TRACO}`}>
          {linha.coditem || TRACO} · {linha.descricao || TRACO}
        </span>
      </th>
      <td>
        <SeloTipo tipo={linha.tipo} />
      </td>
      <td className="mono">{inteiro(linha.qtd)}</td>
      <td>
        <span className="gantt-progresso">
          <progress className="progresso-barra" max={100} value={linha.pct} aria-label="Etapas aprovadas" />
          <span className="mono">{linha.pct}%</span>
        </span>
      </td>
      {linha.celulas.map((c, i) => {
        const etapa = etapas[i];
        const descricao = `${etapa?.nome ?? ''}: ${NOME_CELULA[c.s]}${c.s === 'aprovada' && c.rotulo ? ` em ${c.rotulo}` : ''}`;
        const texto = c.s === 'na' ? '—' : c.rotulo.slice(0, 10);
        return (
          <td key={etapa?.chave ?? i}>
            {linha.lote && c.s !== 'na' ? (
              <Link to={`/lotes/${linha.lote.id}`} className={`gantt-cel gantt-${c.s}`} title={descricao} aria-label={descricao}>
                <span aria-hidden="true">{texto}</span>
              </Link>
            ) : (
              <span className={`gantt-cel gantt-${c.s}`} title={descricao}>
                <span aria-hidden="true">{texto}</span>
                <span className="so-leitor">{descricao}</span>
              </span>
            )}
          </td>
        );
      })}
    </tr>
  );
}

export function Gantt() {
  const carga = useCarga<RespostaGantt>((sinal) => api('/gantt', { sinal }), []);
  const [tipo, setTipo] = useState<FiltroTipo>('');
  const [op, setOp] = useState('');
  const [coditem, setCoditem] = useState('');
  const [descricao, setDescricao] = useState('');
  const [status, setStatus] = useState<FiltroStatus>('ativos');
  const dados = carga.dados;

  const { visiveis, enviadosOcultos } = useMemo(() => {
    const linhas = dados?.linhas ?? [];
    const passaOutros = (l: LinhaGantt) =>
      (!tipo || l.tipo === tipo) && inclui(l.op, op) && inclui(l.coditem, coditem) && contemTermos(l.descricao, descricao);
    return {
      visiveis: linhas.filter((l) => passaOutros(l) && passaStatus(l, status)),
      // Enviados que só o filtro de status está escondendo (para o aviso)
      enviadosOcultos: linhas.filter((l) => l.situacao === 'enviado' && passaOutros(l) && !passaStatus(l, status)).length,
    };
  }, [dados, tipo, op, coditem, descricao, status]);

  const temFiltro = tipo !== '' || op !== '' || coditem !== '' || descricao !== '' || status !== 'ativos';
  function limpar() {
    setTipo('');
    setOp('');
    setCoditem('');
    setDescricao('');
    setStatus('ativos');
  }

  return (
    <>
      <Cabecalho
        titulo="Gantt"
        apoio="Linha do processo por OP: as etapas por que cada OP do cadastro passa, o que já foi aprovado e o que está em andamento."
      >
        <button type="button" className="botao" onClick={carga.recarregar} disabled={carga.carregando}>
          {carga.carregando ? 'Atualizando…' : 'Atualizar'}
        </button>
      </Cabecalho>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
      {!dados && carga.carregando && <Carregando />}
      {dados && dados.linhas.length === 0 && (
        <Vazio titulo="Nenhuma OP cadastrada ainda.">
          As OPs vêm do <Link to="/ordens-producao">cadastro de ordens de produção</Link>.
        </Vazio>
      )}

      {dados && dados.linhas.length > 0 && (
        <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`} aria-busy={carga.carregando}>
          <CartoesTotais
            totais={dados.totais}
            tendencias={dados.tendencias}
            primeiro={
              <CartaoNumero
                rotulo="OPs"
                valor={inteiro(dados.totais.ops)}
                apoio={`${inteiro(dados.totais.lotes)} com lote · ${inteiro(dados.totais.sem_lote)} sem lote`}
              />
            }
          />

          <div className="filtros" role="search" aria-label="Filtros do Gantt">
            <div className="campo">
              <span className="rotulo" id="gantt-rotulo-tipo">
                Tipo
              </span>
              <Segmentos idRotulo="gantt-rotulo-tipo" opcoes={OPCOES_TIPO} valor={tipo} aoMudar={setTipo} />
            </div>
            <div className="campo">
              <label htmlFor="gantt-op">Nº da OP</label>
              <input id="gantt-op" type="search" className="mono" list="gantt-ops" autoComplete="off" value={op} onChange={(e) => setOp(e.target.value)} />
            </div>
            <div className="campo">
              <label htmlFor="gantt-cod">CODITEM</label>
              <input id="gantt-cod" type="search" className="mono" list="gantt-cods" autoComplete="off" value={coditem} onChange={(e) => setCoditem(e.target.value)} />
            </div>
            <div className="campo campo-busca">
              <label htmlFor="gantt-desc">Descrição do produto</label>
              <input id="gantt-desc" type="search" autoComplete="off" value={descricao} onChange={(e) => setDescricao(e.target.value)} />
            </div>
            <div className="campo campo-em-linha">
              <label htmlFor="gantt-status">Status do lote</label>
              <select id="gantt-status" value={status} onChange={(e) => setStatus(e.target.value as FiltroStatus)}>
                {OPCOES_STATUS.map((o) => (
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
              {inteiro(visiveis.length)} {visiveis.length === 1 ? 'OP visível' : 'OPs visíveis'}
            </span>
            <SugestoesCadastro idOps="gantt-ops" idItens="gantt-cods" ops={dados.ops} />
          </div>

          {enviadosOcultos > 0 && status !== 'enviado' && (
            <Faixa tipo="info" papel="status">
              <span className="pn-aviso-ocultos">
                {enviadosOcultos === 1 ? '1 OP com Enviado-DB está oculta.' : `${inteiro(enviadosOcultos)} OPs com Enviado-DB estão ocultas.`}
                <button type="button" className="botao-link" onClick={() => setStatus('enviado')}>
                  Ver os Enviados-DB
                </button>
              </span>
            </Faixa>
          )}

          <ul className="gantt-legenda" aria-label="Legenda das cores">
            {LEGENDA.map((item) => (
              <li key={item.s}>
                <span className={`gantt-cel gantt-${item.s}`} aria-hidden="true">
                  {item.s === 'na' ? '—' : ''}
                </span>
                {item.rotulo}
              </li>
            ))}
          </ul>

          {visiveis.length === 0 ? (
            <Vazio titulo="Nenhuma OP com esses filtros." />
          ) : (
            <div className="gantt-rolagem">
              <table className="gantt-tabela">
                <caption className="so-leitor">Etapas de cada OP. Clique numa célula para abrir o lote.</caption>
                <thead>
                  <tr>
                    <th scope="col" className="gantt-op">
                      OP · Lote · Item
                    </th>
                    <th scope="col">Tipo</th>
                    <th scope="col">Qtd</th>
                    <th scope="col">Progresso</th>
                    {dados.etapas.map((e, i) => (
                      <th key={e.chave} scope="col" title={e.nome}>
                        {i + 1}. {e.curto}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visiveis.map((linha) => (
                    <LinhaTabela key={linha.op} linha={linha} etapas={dados.etapas} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}
