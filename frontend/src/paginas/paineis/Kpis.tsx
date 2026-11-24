/**
 * KPIs de produção (legado: rota /kpis e TEMPLATES["kpis"]): resumo com tendência mês a mês e os gráficos
 * de pipeline, pipeline por tipo, gargalo por setor, databooks enviados por mês, mix de tipos e peças por mês.
 * Filtros de período (pela data de criação do lote) e de tipo, guardados no endereço da página.
 */
import { Link, useSearchParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga } from '../../componentes/Estados';
import { api, consulta } from '../../lib/api';
import { dataHoraLocal, inteiro } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import { CartaoNumero, linkEnviados, pecasTexto, Segmentos, TIPOS } from './comuns';
import {
  BarraDividida,
  BarrasHorizontais,
  CartaoGrafico,
  ColunasMensais,
  decimal,
  LinhaDica,
  SERIES_TIPO,
  TabelaDados,
  type Serie,
} from './graficos';
import type { Periodo, ResumoKpis, RespostaKpis, Totais } from './tipos';

const UMA_SERIE: Serie[] = [{ chave: 'valor', nome: 'Valor', cor: 'var(--graf-um)' }];
const ENVIADOS: Serie[] = [{ chave: 'enviados', nome: 'Databooks enviados', cor: 'var(--graf-enviado)' }];

const PERIODOS: { valor: Periodo; rotulo: string }[] = [
  { valor: 'tudo', rotulo: 'Todo o histórico' },
  { valor: 'ano', rotulo: 'Ano atual' },
  { valor: '12m', rotulo: 'Últimos 12 meses' },
  { valor: '6m', rotulo: 'Últimos 6 meses' },
  { valor: '3m', rotulo: 'Últimos 3 meses' },
];

type FiltroTipoKpi = 'todos' | 'PIN' | 'BOX' | 'ARK';
const OPCOES_TIPO: { valor: FiltroTipoKpi; rotulo: string }[] = [
  { valor: 'todos', rotulo: 'Todos' },
  ...TIPOS.map((t) => ({ valor: t, rotulo: t })),
];

/** "3 lotes · 120 pç" */
function lotesPecas(lotes: number, pecas: number): string {
  return `${inteiro(lotes)} ${lotes === 1 ? 'lote' : 'lotes'} · ${inteiro(pecas)} pç`;
}

/** Pipeline, gargalos, databooks por mês e mix: os gráficos que o dashboard também mostra. */
export function GraficosResumo({ kpis, totais, vazio = 'Sem lotes.' }: { kpis: ResumoKpis; totais: Totais; vazio?: string }) {
  const semLotes = kpis.funil.every((f) => f.lotes === 0);
  const totalEnviados = kpis.linha_do_tempo.reduce((s, m) => s + m.enviados, 0);
  return (
    <div className="graf-grade-cartoes">
      <CartaoGrafico titulo="Pipeline de produção" apoio="Em andamento → Finalizados (concluídos + Enviados-DB)." vazio={semLotes && vazio}>
        <BarrasHorizontais
          legenda="Lotes em andamento e finalizados"
          series={UMA_SERIE}
          itens={kpis.funil.map((f) => ({ chave: f.nome, rotulo: f.nome, valores: [f.lotes], textos: [lotesPecas(f.lotes, f.pecas)] }))}
        />
        <TabelaDados legenda="Pipeline de produção" colunas={['Estado', 'Lotes', 'Peças']} linhas={kpis.funil.map((f) => [f.nome, f.lotes, f.pecas])} />
      </CartaoGrafico>

      <CartaoGrafico
        titulo="Lotes por setor"
        apoio="Lotes em andamento em cada setor. O de cima é o que mais acumula: possível gargalo."
        vazio={kpis.setores.length === 0 && 'Nenhum lote em andamento num setor no momento.'}
      >
        <BarrasHorizontais
          legenda="Lotes em andamento por setor"
          series={UMA_SERIE}
          itens={kpis.setores.map((s) => ({
            chave: s.setor_completo,
            rotulo: s.setor,
            valores: [s.lotes],
            dicas: [<LinhaDica key="l" valor={inteiro(s.lotes)} nome={`${s.lotes === 1 ? 'lote' : 'lotes'} · ${s.setor_completo}`} />],
          }))}
        />
        <TabelaDados
          legenda="Lotes e dias médios por setor"
          colunas={['Setor', 'Lotes', 'Dias médios parados']}
          linhas={kpis.setores.map((s) => [s.setor_completo, s.lotes, decimal(s.dias_medio)])}
        />
      </CartaoGrafico>

      <CartaoGrafico
        titulo="Dias médios parados por setor"
        apoio="Há quantos dias, em média, os lotes estão na etapa atual de cada setor."
        vazio={kpis.setores.length === 0 && 'Nenhum lote em andamento num setor no momento.'}
      >
        <BarrasHorizontais
          legenda="Dias médios parados por setor"
          series={UMA_SERIE}
          itens={[...kpis.setores]
            .sort((a, b) => b.dias_medio - a.dias_medio)
            .map((s) => ({
              chave: s.setor_completo,
              rotulo: s.setor,
              valores: [s.dias_medio],
              textos: [`${decimal(s.dias_medio)} d`],
              dicas: [<LinhaDica key="d" valor={`${decimal(s.dias_medio)} dias`} nome={`em média · ${s.setor_completo}`} />],
            }))}
        />
      </CartaoGrafico>

      <CartaoGrafico
        titulo="Databooks Enviados-DB por mês"
        apoio={
          totalEnviados > 0
            ? `Entregas ao cliente: ${inteiro(totalEnviados)} ${totalEnviados === 1 ? 'databook' : 'databooks'} em ${kpis.linha_do_tempo.length} meses.`
            : 'Histórico de entregas ao cliente.'
        }
        vazio={kpis.linha_do_tempo.length === 0 && 'Nenhum databook enviado ainda.'}
      >
        <ColunasMensais
          legenda="Databooks enviados ao cliente por mês"
          series={ENVIADOS}
          unidade="databooks"
          meses={kpis.linha_do_tempo.map((m) => ({ chave: m.chave, mes: m.mes, valores: [m.enviados] }))}
        />
        <TabelaDados legenda="Databooks enviados por mês" colunas={['Mês', 'Databooks']} linhas={kpis.linha_do_tempo.map((m) => [m.mes, m.enviados])} />
      </CartaoGrafico>

      <CartaoGrafico titulo="Mix PIN / BOX / ARK" apoio="Proporção dos tipos no total de lotes." vazio={totais.lotes === 0 && 'Sem lotes.'}>
        <BarraDividida
          legenda="Lotes de cada tipo"
          unidade="lotes"
          partes={SERIES_TIPO.map((s) => ({ ...s, valor: totais[s.chave as 'pin' | 'box' | 'ark'] }))}
        />
      </CartaoGrafico>
    </div>
  );
}

export function Kpis() {
  const [parametros, setParametros] = useSearchParams();
  const periodo = (PERIODOS.find((p) => p.valor === parametros.get('periodo'))?.valor ?? 'tudo') as Periodo;
  const tipo = (OPCOES_TIPO.find((t) => t.valor === parametros.get('tipo'))?.valor ?? 'todos') as FiltroTipoKpi;
  const carga = useCarga<RespostaKpis>((sinal) => api(`/kpis${consulta({ periodo, tipo })}`, { sinal }), [periodo, tipo]);
  const dados = carga.dados;

  function mudar(chave: 'periodo' | 'tipo', valor: string, padrao: string) {
    const novos = new URLSearchParams(parametros);
    if (valor === padrao) novos.delete(chave);
    else novos.set(chave, valor);
    setParametros(novos, { replace: true });
  }

  const temFiltro = periodo !== 'tudo' || tipo !== 'todos';
  const t = dados?.totais;

  return (
    <>
      <Cabecalho titulo="KPIs de produção" apoio="Indicadores principais com tendência mês a mês: pipeline, gargalos, entregas e mix de produto.">
        <button type="button" className="botao" onClick={carga.recarregar} disabled={carga.carregando}>
          {carga.carregando ? 'Atualizando…' : 'Atualizar'}
        </button>
      </Cabecalho>

      <div className="filtros" role="search" aria-label="Filtros dos KPIs">
        <div className="campo">
          <label htmlFor="kpi-periodo">Período</label>
          <select id="kpi-periodo" value={periodo} onChange={(e) => mudar('periodo', e.target.value, 'tudo')}>
            {PERIODOS.map((p) => (
              <option key={p.valor} value={p.valor}>
                {p.rotulo}
              </option>
            ))}
          </select>
        </div>
        <div className="campo">
          <span className="rotulo" id="kpi-rotulo-tipo">
            Tipo do lote
          </span>
          <Segmentos idRotulo="kpi-rotulo-tipo" opcoes={OPCOES_TIPO} valor={tipo} aoMudar={(v) => mudar('tipo', v, 'todos')} />
        </div>
        {temFiltro && (
          <>
            <span className="chip chip-alerta kpi-filtro-ativo">
              Filtro ativo: {[periodo !== 'tudo' ? PERIODOS.find((p) => p.valor === periodo)?.rotulo : '', tipo !== 'todos' ? `tipo ${tipo}` : '']
                .filter(Boolean)
                .join(' · ')}
            </span>
            <button type="button" className="botao-link" onClick={() => setParametros(new URLSearchParams(), { replace: true })}>
              Limpar filtros
            </button>
          </>
        )}
      </div>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
      {!dados && carga.carregando && <Carregando />}

      {dados && t && (
        <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`} aria-busy={carga.carregando}>
          <div className="pn-cartoes">
            <CartaoNumero rotulo="Em andamento" valor={inteiro(t.andamento)} apoio={pecasTexto(t.pecas_andamento)} classe="pn-numero-andamento" />
            <CartaoNumero
              rotulo="Finalizados"
              valor={inteiro(t.concluidos + t.enviados)}
              tendencia={dados.tendencias.enviados}
              referenciaTendencia="envios vs mês anterior"
              apoio={
                <>
                  {pecasTexto(t.pecas_concluidos + t.pecas_enviados)} · {inteiro(t.concluidos)} {t.concluidos === 1 ? 'concluído' : 'concluídos'} /{' '}
                  {inteiro(t.enviados)} Enviado-DB
                </>
              }
              link={linkEnviados()}
              classe="pn-numero-concluido"
            />
            <CartaoNumero
              rotulo="Lotes totais"
              valor={inteiro(t.lotes)}
              apoio={`${pecasTexto(t.pecas)} · ${inteiro(t.pin)} PIN / ${inteiro(t.box)} BOX / ${inteiro(t.ark)} ARK`}
            />
            <CartaoNumero
              rotulo={`Soma anual ${dados.ano} · peças`}
              valor={inteiro(dados.soma_anual.total)}
              apoio={`${inteiro(dados.soma_anual.pin)} PIN · ${inteiro(dados.soma_anual.box)} BOX · ${inteiro(dados.soma_anual.ark)} ARK`}
            />
          </div>

          <GraficosResumo kpis={dados} totais={t} vazio="Sem lotes no período ou tipo escolhido." />

          <div className="graf-grade-cartoes">
            <CartaoGrafico
              titulo="Pipeline por tipo (PIN / BOX / ARK)"
              apoio="O mesmo pipeline, separado por tipo de peça."
              vazio={dados.funil_tipo.every((f) => f.pin + f.box + f.ark === 0) && 'Sem lotes no período ou tipo escolhido.'}
            >
              <BarrasHorizontais
                legenda="Lotes em andamento e finalizados por tipo"
                series={SERIES_TIPO}
                itens={dados.funil_tipo.map((f) => ({
                  chave: f.nome,
                  rotulo: f.nome,
                  valores: [f.pin, f.box, f.ark],
                  textos: [`${inteiro(f.pin)} · ${inteiro(f.pecas_pin)} pç`, `${inteiro(f.box)} · ${inteiro(f.pecas_box)} pç`, `${inteiro(f.ark)} · ${inteiro(f.pecas_ark)} pç`],
                }))}
              />
              <TabelaDados
                legenda="Pipeline por tipo"
                colunas={['Estado', 'PIN (lotes)', 'PIN (peças)', 'BOX (lotes)', 'BOX (peças)', 'ARK (lotes)', 'ARK (peças)']}
                linhas={dados.funil_tipo.map((f) => [f.nome, f.pin, f.pecas_pin, f.box, f.pecas_box, f.ark, f.pecas_ark])}
              />
            </CartaoGrafico>

            <CartaoGrafico
              titulo="Peças por tipo × mês"
              apoio={`Pela data de criação do lote. Soma anual ${dados.ano}: ${pecasTexto(dados.soma_anual.total)}.`}
              vazio={dados.pecas_mes.length === 0 && 'Sem peças no período ou tipo escolhido.'}
              classe="graf-largo"
            >
              <ColunasMensais
                legenda="Peças de cada tipo por mês"
                series={SERIES_TIPO}
                unidade="peças"
                meses={dados.pecas_mes.map((m) => ({ chave: m.chave, mes: m.mes, valores: [m.pin, m.box, m.ark] }))}
              />
              <TabelaDados
                legenda="Peças por tipo e mês"
                colunas={['Mês', 'PIN', 'BOX', 'ARK', 'Total']}
                linhas={dados.pecas_mes.map((m) => [m.mes, m.pin, m.box, m.ark, m.total])}
              />
            </CartaoGrafico>
          </div>

          <p className="kpi-rodape">
            Atualizado em {dataHoraLocal(dados.gerado_em)} · <Link to="/dashboard">ver as bolhas por setor no dashboard</Link>
          </p>
        </div>
      )}
    </>
  );
}
