/**
 * Indicadores de refugo e retrabalho (legado: rota /indicadores e TEMPLATES["indicadores"]): somas de todas as
 * corridas de matéria-prima lançadas, por fornecedor, por tipo de peça e as 10 corridas com maior refugo.
 */
import { Link } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Vazio } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { TabelaOrdenavel, type Coluna } from '../../componentes/Tabela';
import { api } from '../../lib/api';
import { inteiro, TRACO } from '../../lib/formato';
import type { TipoLote } from '../../lib/tipos';
import { useCarga } from '../../lib/useCarga';
import { CartaoNumero, TIPOS } from './comuns';
import { porcentagem } from './graficos';
import type { CorridaIndicador, Rendimento, RespostaIndicadores } from './tipos';

/** Faixas do sistema antigo: refugo bom abaixo de 5%, atenção até 10%; retrabalho bom abaixo de 15%, atenção até 25%. */
const FAIXAS = { refugo: [5, 10], retrab: [15, 25] } as const;

function Percentual({ valor, faixa }: { valor: number; faixa: keyof typeof FAIXAS }) {
  const [atencao, alto] = FAIXAS[faixa];
  const nivel = valor >= alto ? 'erro' : valor >= atencao ? 'alerta' : 'ok';
  const nome = nivel === 'erro' ? 'alto' : nivel === 'alerta' ? 'atenção' : 'bom';
  return (
    <span className={`selo selo-${nivel} ind-pct`} title={nome}>
      {porcentagem(valor)}
      <span className="so-leitor"> ({nome})</span>
    </span>
  );
}

function colunasRendimento<T extends Rendimento>(primeira: Coluna<T>, comAprovadas: boolean): Coluna<T>[] {
  const colunas: Coluna<T>[] = [
    primeira,
    { chave: 'corridas', titulo: 'Corridas', numerica: true, valor: (d) => d.corridas, celula: (d) => inteiro(d.corridas) },
    { chave: 'qt_fund', titulo: 'QT-Fund.', numerica: true, valor: (d) => d.qt_fund, celula: (d) => inteiro(d.qt_fund), dica: 'Peças fundidas' },
    { chave: 'qt_real', titulo: 'QT-Real', numerica: true, valor: (d) => d.qt_real, celula: (d) => inteiro(d.qt_real), dica: 'Peças recebidas de fato' },
  ];
  if (comAprovadas) {
    colunas.push(
      { chave: 'qt_ok', titulo: 'QT-OK', numerica: true, valor: (d) => d.qt_ok, celula: (d) => inteiro(d.qt_ok), dica: 'Peças aprovadas' },
      {
        chave: 'rendimento',
        titulo: 'Rendimento',
        numerica: true,
        valor: (d) => d.rendimento,
        celula: (d) => <span className="ind-pct">{porcentagem(d.rendimento)}</span>,
        dica: 'QT-OK sobre QT-Fund.',
      },
    );
  }
  colunas.push(
    { chave: 'pct_refugo', titulo: '% Refugo', numerica: true, valor: (d) => d.pct_refugo, celula: (d) => <Percentual valor={d.pct_refugo} faixa="refugo" /> },
    { chave: 'pct_retrab', titulo: '% Retrab.', numerica: true, valor: (d) => d.pct_retrab, celula: (d) => <Percentual valor={d.pct_retrab} faixa="retrab" /> },
  );
  return colunas;
}

const COLUNAS_FORNECEDOR = colunasRendimento<Rendimento & { fornecedor: string }>(
  { chave: 'fornecedor', titulo: 'Fornecedor', valor: (d) => d.fornecedor, celula: (d) => <strong>{d.fornecedor}</strong> },
  true,
);

const COLUNAS_TIPO = colunasRendimento<Rendimento & { tipo: string }>(
  {
    chave: 'tipo',
    titulo: 'Tipo',
    valor: (d) => d.tipo,
    celula: (d) => (TIPOS.includes(d.tipo as TipoLote) ? <SeloTipo tipo={d.tipo as TipoLote} /> : <strong>{d.tipo}</strong>),
  },
  false,
);

const COLUNAS_CORRIDA: Coluna<CorridaIndicador>[] = [
  { chave: 'nf', titulo: 'NF', mono: true, valor: (m) => m.nf_entrada || null },
  {
    chave: 'corrida',
    titulo: 'Corrida',
    mono: true,
    valor: (m) => m.corrida,
    celula: (m) => (
      <Link to={`/materia-prima/${m.id}`} className="link-forte">
        {m.corrida || `#${m.id}`}
      </Link>
    ),
  },
  { chave: 'fornecedor', titulo: 'Fornecedor', valor: (m) => m.fornecedor || null },
  {
    chave: 'tipo',
    titulo: 'Tipo',
    valor: (m) => m.tipo_destino || null,
    celula: (m) => (TIPOS.includes(m.tipo_destino as TipoLote) ? <SeloTipo tipo={m.tipo_destino as TipoLote} /> : m.tipo_destino || TRACO),
  },
  { chave: 'qt_fund', titulo: 'QT-Fund.', numerica: true, valor: (m) => m.qt_fund, celula: (m) => inteiro(m.qt_fund) },
  { chave: 'qt_real', titulo: 'QT-Real', numerica: true, valor: (m) => m.qt_real, celula: (m) => inteiro(m.qt_real) },
  { chave: 'pct_refugo', titulo: '% Refugo', numerica: true, valor: (m) => m.pct_refugo, celula: (m) => <Percentual valor={m.pct_refugo} faixa="refugo" /> },
  { chave: 'pct_retrab', titulo: '% Retrab.', numerica: true, valor: (m) => m.pct_retrab, celula: (m) => <Percentual valor={m.pct_retrab} faixa="retrab" /> },
];

export function Indicadores() {
  const carga = useCarga<RespostaIndicadores>((sinal) => api('/indicadores', { sinal }), []);
  const dados = carga.dados;
  const g = dados?.geral;

  return (
    <>
      <Cabecalho
        titulo="Indicadores"
        apoio="Refugo e retrabalho de todas as corridas lançadas na matéria-prima. Verde = bom, amarelo = atenção, vermelho = alto."
      >
        <Link to="/materia-prima" className="botao">
          Matéria-prima
        </Link>
      </Cabecalho>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
      {!dados && carga.carregando && <Carregando />}
      {dados && dados.total === 0 && (
        <Vazio titulo="Nenhuma corrida lançada ainda.">
          <Link to="/materia-prima">Lance a primeira corrida</Link> para começar a medir.
        </Vazio>
      )}

      {dados && g && dados.total > 0 && (
        <div className="pilha">
          <div className="pn-cartoes">
            <CartaoNumero rotulo="Corridas" valor={inteiro(g.corridas)} apoio={`${inteiro(g.qt_real)} peças reais`} />
            <CartaoNumero rotulo="QT-Fund." valor={inteiro(g.qt_fund)} apoio={`Rendimento: ${porcentagem(g.rendimento)}`} />
            <CartaoNumero rotulo="Aprovadas" valor={inteiro(g.qt_ok)} apoio={`${porcentagem(g.pct_aprov)} das peças reais`} classe="pn-numero-concluido" />
            <CartaoNumero
              rotulo="Refugo"
              valor={inteiro(g.qt_rej)}
              apoio={
                <>
                  <Percentual valor={g.pct_refugo} faixa="refugo" /> do total
                </>
              }
            />
            <CartaoNumero
              rotulo="Retrabalho"
              valor={inteiro(g.qt_retrab)}
              apoio={
                <>
                  <Percentual valor={g.pct_retrab} faixa="retrab" /> do total
                </>
              }
            />
          </div>
          <p className="nota-discreta">
            Refugo e retrabalho são calculados sobre a QT-Real; o rendimento é QT-OK sobre QT-Fund. Faixas: refugo bom abaixo de 5%, atenção de 5% a 10%,
            alto a partir de 10%; retrabalho bom abaixo de 15%, atenção de 15% a 25%, alto a partir de 25%.
          </p>

          <section className="cartao" aria-labelledby="ind-fornecedor">
            <h2 id="ind-fornecedor">Por fornecedor</h2>
            <TabelaOrdenavel
              legenda="Indicadores por fornecedor"
              colunas={COLUNAS_FORNECEDOR}
              linhas={dados.por_fornecedor}
              chaveLinha={(d) => d.fornecedor}
              ordemInicial={{ chave: 'qt_real', direcao: 'desc' }}
            />
          </section>

          <section className="cartao" aria-labelledby="ind-tipo">
            <h2 id="ind-tipo">Por tipo de peça</h2>
            <TabelaOrdenavel legenda="Indicadores por tipo de peça" colunas={COLUNAS_TIPO} linhas={dados.por_tipo} chaveLinha={(d) => d.tipo} />
          </section>

          <section className="cartao" aria-labelledby="ind-top">
            <h2 id="ind-top">As 10 corridas com maior refugo</h2>
            <TabelaOrdenavel
              legenda="Corridas com maior refugo"
              colunas={COLUNAS_CORRIDA}
              linhas={dados.top_refugo}
              chaveLinha={(m) => m.id}
              ordemInicial={{ chave: 'pct_refugo', direcao: 'desc' }}
            />
          </section>
        </div>
      )}
    </>
  );
}
