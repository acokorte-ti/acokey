import { Link, useSearchParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Vazio } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api } from '../../lib/api';
import { dataCurta, inteiro, pecas } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import { SeloCarga } from './Comuns';
import type { Aba, CargaResumo, ListaCargas as Lista } from './tipos';

const ABAS: { valor: Aba; rotulo: string; vazio: string }[] = [
  { valor: 'ativas', rotulo: 'Em aberto', vazio: 'Nenhuma carga planejada ou em andamento.' },
  { valor: 'concluidas', rotulo: 'Concluídas', vazio: 'Nenhuma carga concluída.' },
  { valor: 'canceladas', rotulo: 'Canceladas', vazio: 'Nenhuma carga cancelada.' },
];

function CartaoCarga({ carga }: { carga: CargaResumo }) {
  return (
    <li className="cartao ctt-cartao">
      <div className="ctt-cartao-corpo">
        <div className="ctt-cartao-titulo">
          <Link to={`/cargas-tt/${carga.id}`} className="ctt-numero">
            {carga.numero}
          </Link>
          <SeloCarga status={carga.status} />
          <span className="sub-linha">
            {inteiro(carga.n_lotes)} {carga.n_lotes === 1 ? 'lote' : 'lotes'} · {pecas(carga.total_pecas)}
          </span>
        </div>
        <p className="sub-linha">
          Têmpera: <strong>{carga.forno_tempera_desc}</strong> · Revenimento: <strong>{carga.forno_revenimento_desc}</strong>
          {carga.data_planejada && <> · planejada para {dataCurta(carga.data_planejada)}</>}
        </p>
        <ul className="ctt-lotes-linha" aria-label={`Lotes da carga ${carga.numero}`}>
          {carga.lotes.map((l) => (
            <li key={l.id}>
              <Link to={`/lotes/${l.id}`}>OP {l.op}</Link> <SeloTipo tipo={l.tipo} /> {pecas(l.qtd)}
            </li>
          ))}
        </ul>
      </div>
      <Link to={`/cargas-tt/${carga.id}`} className="botao botao-pequeno">
        Abrir
      </Link>
    </li>
  );
}

export function ListaCargas() {
  const [parametros, setParametros] = useSearchParams();
  const aba = (ABAS.find((a) => a.valor === parametros.get('aba'))?.valor ?? 'ativas') as Aba;
  const lista = useCarga<Lista>((sinal) => api(`/cargas-tt?aba=${aba}`, { sinal }), [aba]);
  const atual = ABAS.find((a) => a.valor === aba) ?? ABAS[0];

  return (
    <>
      <Cabecalho
        titulo="Cargas de tratamento térmico"
        apoio="Monte a carga do forno antes de rodar o tratamento, consulte as instruções de trabalho (ITT) e gere o relatório de TT a partir daqui. Um lote pode participar de mais de uma carga (ex.: têmpera em uma, revenimento em outra)."
      >
        <Link to="/cargas-tt/nova" className="botao botao-primario">
          + Nova carga
        </Link>
      </Cabecalho>

      <div className="abas" role="tablist" aria-label="Situação das cargas">
        {ABAS.map((a) => (
          <button
            key={a.valor}
            type="button"
            role="tab"
            aria-selected={a.valor === aba}
            className={`aba ctt-aba ${a.valor === aba ? 'aba-atual' : ''}`}
            onClick={() => setParametros(a.valor === 'ativas' ? {} : { aba: a.valor }, { replace: true })}
          >
            {a.rotulo}
            <span className="ctt-contagem">{lista.dados ? inteiro(lista.dados.contagens[a.valor]) : '…'}</span>
          </button>
        ))}
      </div>
      <div className="cartao cartao-aba" role="tabpanel">
        {lista.erro && <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />}
        {!lista.erro && !lista.dados && <Carregando />}
        {lista.dados && lista.dados.itens.length === 0 && <Vazio titulo={atual.vazio} />}
        {lista.dados && lista.dados.itens.length > 0 && (
          <ul className={`ctt-lista ${lista.carregando ? 'recarregando' : ''}`}>
            {lista.dados.itens.map((c) => (
              <CartaoCarga key={c.id} carga={c} />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
