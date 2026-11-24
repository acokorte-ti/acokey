import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { TabelaOrdenavel, type Coluna } from '../../componentes/Tabela';
import { api } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { contemTermos, inteiro, TRACO } from '../../lib/formato';
import { useUsuario } from '../../lib/sessao';
import { useCarga } from '../../lib/useCarga';
import { porcento, tomRefugo, tomRetrabalho, tomSaldo } from './calculos';
import { formularioVazio, ModalCorrida } from './FormCorrida';
import type { CorridaNaLista, ListaCorridas as Lista, RespostaMensagem, StatusCorrida } from './tipos';

const STATUS: Record<StatusCorrida, { rotulo: string; classe: string }> = {
  pendente: { rotulo: 'Pendente', classe: 'selo-alerta' },
  aprovada: { rotulo: 'Aprovada', classe: 'selo-ok' },
  reprovada: { rotulo: 'Reprovada', classe: 'selo-erro' },
};

export function SeloStatusCorrida({ status }: { status: StatusCorrida }) {
  const aparencia = STATUS[status] ?? { rotulo: status, classe: '' };
  return <span className={`selo ${aparencia.classe}`}>{aparencia.rotulo}</span>;
}

export function SeloCarimbado() {
  return (
    <span className="selo selo-ok mp-selo-carimbado" title="Certificado carimbado APROVADO neste sistema">
      Carimbado
    </span>
  );
}

type FiltroTipo = '' | 'PIN' | 'BOX' | 'ARK';

export function ListaCorridas() {
  const eu = useUsuario();
  const avisos = useAvisos();
  const navegar = useNavigate();
  const lista = useCarga<Lista>((sinal) => api('/materia-prima', { sinal }), []);
  const [busca, setBusca] = useState('');
  const [tipo, setTipo] = useState<FiltroTipo>('');
  const [status, setStatus] = useState<'' | StatusCorrida>('');
  const [lancando, setLancando] = useState(false);

  const filtradas = useMemo(
    () =>
      (lista.dados?.itens ?? []).filter(
        (c) =>
          (!tipo || c.tipo_destino === tipo) &&
          (!status || c.status === status) &&
          contemTermos(`${c.nf_entrada} ${c.corrida} ${c.fornecedor}`, busca),
      ),
    [lista.dados, busca, tipo, status],
  );

  const colunas = useMemo<Coluna<CorridaNaLista>[]>(
    () => [
      { chave: 'nf', titulo: 'NF', mono: true, valor: (c) => c.nf_entrada, celula: (c) => <strong>{c.nf_entrada || TRACO}</strong> },
      {
        chave: 'corrida',
        titulo: 'Corrida',
        mono: true,
        valor: (c) => c.corrida,
        celula: (c) => (
          <Link className="link-forte" to={`/materia-prima/${c.id}`}>
            {c.corrida}
          </Link>
        ),
      },
      { chave: 'fornecedor', titulo: 'Fornecedor', valor: (c) => c.fornecedor, celula: (c) => c.fornecedor || TRACO },
      { chave: 'tipo', titulo: 'Tipo', valor: (c) => c.tipo_destino, celula: (c) => (c.tipo_destino ? <SeloTipo tipo={c.tipo_destino} /> : TRACO) },
      {
        chave: 'status',
        titulo: 'Situação',
        valor: (c) => c.status,
        celula: (c) => (
          <span className="acoes-linha">
            <SeloStatusCorrida status={c.status} />
            {c.tem_carimbado && <SeloCarimbado />}
          </span>
        ),
      },
      { chave: 'fund', titulo: 'QT-Fund.', numerica: true, valor: (c) => c.qt_fund, celula: (c) => inteiro(c.qt_fund) },
      { chave: 'real', titulo: 'QT-Real', numerica: true, valor: (c) => c.qt_real, celula: (c) => inteiro(c.qt_real) },
      { chave: 'ok', titulo: 'QT-OK', numerica: true, valor: (c) => c.qt_ok, celula: (c) => inteiro(c.qt_ok) },
      {
        chave: 'saldo',
        titulo: 'Saldo',
        numerica: true,
        dica: 'Disponível (QT-OK menos corpos de prova) menos o que os lotes já usaram',
        valor: (c) => c.qt_saldo,
        celula: (c) => (
          <strong className={`mp-tom-${tomSaldo(c.qt_saldo)}`} title={`Disponível ${c.qt_disponivel} − consumido ${c.qt_consumida}`}>
            {inteiro(c.qt_saldo)}
          </strong>
        ),
      },
      {
        chave: 'refugo',
        titulo: '% Refugo',
        numerica: true,
        valor: (c) => c.pct_refugo,
        celula: (c) => <strong className={`mp-tom-${tomRefugo(c.pct_refugo)}`}>{porcento(c.pct_refugo)}</strong>,
      },
      {
        chave: 'retrab',
        titulo: '% Retrab.',
        numerica: true,
        valor: (c) => c.pct_retrab,
        celula: (c) => <strong className={`mp-tom-${tomRetrabalho(c.pct_retrab)}`}>{porcento(c.pct_retrab)}</strong>,
      },
      {
        chave: 'lotes',
        titulo: 'Lotes usando',
        numerica: true,
        valor: (c) => c.lotes_usando,
        celula: (c) => (c.lotes_usando ? <span className="selo selo-ok">{c.lotes_usando}</span> : TRACO),
      },
      {
        chave: '_abrir',
        titulo: '',
        ordenavel: false,
        valor: () => null,
        celula: (c) => (
          <Link className="botao botao-pequeno" to={`/materia-prima/${c.id}`}>
            Abrir
          </Link>
        ),
      },
    ],
    [],
  );

  return (
    <>
      <Cabecalho
        titulo="Matéria-prima"
        apoio="Cada linha é uma corrida recebida do fornecedor. Os percentuais são calculados automaticamente. QT-CP-T.T. (corpos de prova) é descontado do total disponível (QT-OK)."
      >
        <Link className="botao" to="/indicadores">
          Indicadores de refugo/retrabalho
        </Link>
        <button type="button" className="botao botao-primario" onClick={() => setLancando(true)}>
          Lançar corrida
        </button>
      </Cabecalho>

      <Faixa tipo="alerta" papel="note">
        <strong>Certificado de qualidade:</strong> anexe na corrida o PDF do fornecedor e, depois da análise da Qualidade, use
        “Carimbar e aprovar”. A versão carimbada (APROVADO + assinatura) é a que vai para a etapa Receb. MP dos lotes e
        alimenta o Databook do cliente.
      </Faixa>

      <section className="cartao" aria-labelledby="mp-titulo-lista">
        <div className="cartao-topo">
          <h2 id="mp-titulo-lista">Corridas cadastradas {lista.dados && `(${inteiro(lista.dados.itens.length)})`}</h2>
        </div>
        <div className="filtros">
          <div className="campo campo-busca">
            <label htmlFor="mp-busca">Buscar</label>
            <input id="mp-busca" type="search" placeholder="NF, corrida ou fornecedor…" value={busca} onChange={(e) => setBusca(e.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor="mp-filtro-tipo">Tipo</label>
            <select id="mp-filtro-tipo" value={tipo} onChange={(e) => setTipo(e.target.value as FiltroTipo)}>
              <option value="">Todos</option>
              <option value="PIN">PIN</option>
              <option value="BOX">BOX</option>
              <option value="ARK">ARK</option>
            </select>
          </div>
          <div className="campo">
            <label htmlFor="mp-filtro-status">Situação</label>
            <select id="mp-filtro-status" value={status} onChange={(e) => setStatus(e.target.value as '' | StatusCorrida)}>
              <option value="">Todas</option>
              <option value="pendente">Pendentes</option>
              <option value="aprovada">Aprovadas</option>
              <option value="reprovada">Reprovadas</option>
            </select>
          </div>
        </div>

        {lista.erro && <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />}
        {!lista.dados && lista.carregando && <Carregando />}
        {lista.dados && filtradas.length === 0 && (
          <Vazio titulo={lista.dados.itens.length === 0 ? 'Nenhuma corrida lançada ainda.' : 'Nenhuma corrida com esses filtros.'} />
        )}
        {lista.dados && filtradas.length > 0 && (
          <div className={lista.carregando ? 'recarregando' : undefined}>
            <TabelaOrdenavel
              legenda="Corridas de matéria-prima"
              colunas={colunas}
              linhas={filtradas}
              chaveLinha={(c) => c.id}
              classeLinha={(c) => (c.status === 'reprovada' ? 'linha-critica' : undefined)}
            />
            <p className="contagem">
              {inteiro(filtradas.length)} de {inteiro(lista.dados.itens.length)}
            </p>
          </div>
        )}
      </section>

      {lancando && (
        <ModalCorrida
          titulo="Lançar corrida de matéria-prima"
          inicial={formularioVazio()}
          novo
          fornecedores={lista.dados?.fornecedores ?? []}
          responsavel={eu.nome}
          rotuloEnviar="Lançar corrida"
          aoFechar={() => setLancando(false)}
          aoGravar={async (corpo) => {
            const r = await api<RespostaMensagem & { id: number }>('/materia-prima', { metodo: 'POST', corpo });
            avisos.sucesso(r.mensagem);
            setLancando(false);
            navegar(`/materia-prima/${r.id}`);
          }}
        />
      )}
    </>
  );
}
