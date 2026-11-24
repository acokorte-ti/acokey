import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Vazio } from '../../componentes/Estados';
import { SeloNc, SeloTipo } from '../../componentes/Selos';
import { api, consulta } from '../../lib/api';
import { contemTermos, dataHoraLocal, inteiro, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import type { AbaNc, ListaNc, NaoConformidade } from './tipos';

const ABAS: { chave: AbaNc; rotulo: string; vazio: string }[] = [
  { chave: 'abertas', rotulo: 'Em aberto', vazio: 'Nenhuma não conformidade em aberto.' },
  { chave: 'encerradas', rotulo: 'Encerradas', vazio: 'Nenhuma não conformidade encerrada.' },
];

/** "Dureza HRC" ou "Tração / Charpy - Ensaio de tração". */
export function ondeFoi(nc: Pick<NaoConformidade, 'etapa_nome' | 'sub_nome'>): string {
  return nc.sub_nome ? `${nc.etapa_nome} - ${nc.sub_nome}` : nc.etapa_nome;
}

function textoDeBusca(nc: NaoConformidade): string {
  return [nc.numero, nc.lote?.op, nc.lote?.numero, nc.lote?.tipo, ondeFoi(nc), nc.descricao, nc.disposicao_nome, nc.aberta_por]
    .filter(Boolean)
    .join(' ');
}

function ItemNc({ nc }: { nc: NaoConformidade }) {
  return (
    <li className={`nc-item nc-item-${nc.status}`}>
      <div className="nc-item-corpo">
        <div className="nc-item-topo">
          <Link to={`/nao-conformidades/${nc.id}`} className="nc-numero mono">
            {nc.numero}
          </Link>
          <SeloNc status={nc.status} />
        </div>
        <p className="nc-item-onde">
          {nc.lote && (
            <>
              OP <span className="mono">{nc.lote.op || TRACO}</span> · Lote <span className="mono">{nc.lote.numero}</span>{' '}
              <SeloTipo tipo={nc.lote.tipo} /> ·{' '}
            </>
          )}
          {ondeFoi(nc)}
        </p>
        {nc.descricao && <p className="nc-item-descricao">{nc.descricao}</p>}
        <p className="nc-item-meta">
          Aberta em {dataHoraLocal(nc.aberta_em)} por {nc.aberta_por || TRACO}
          {nc.disposicao && <> · Disposição: {nc.disposicao_nome}</>}
        </p>
      </div>
      <Link to={`/nao-conformidades/${nc.id}`} className="botao botao-pequeno">
        Abrir
        <span className="so-leitor"> {nc.numero}</span>
      </Link>
    </li>
  );
}

/** Lista das não conformidades, com as abas Em aberto / Encerradas (como no sistema antigo). */
export function ListaNaoConformidades() {
  const [parametros] = useSearchParams();
  const aba: AbaNc = parametros.get('aba') === 'encerradas' ? 'encerradas' : 'abertas';
  const [busca, setBusca] = useState('');
  const carga = useCarga<ListaNc>((sinal) => api(`/nao-conformidades${consulta({ aba })}`, { sinal }), [aba]);
  const dados = carga.dados && carga.dados.aba === aba ? carga.dados : null;
  const visiveis = useMemo(() => (dados ? dados.itens.filter((nc) => contemTermos(textoDeBusca(nc), busca)) : []), [dados, busca]);
  const infoAba = ABAS.find((a) => a.chave === aba) ?? ABAS[0];

  return (
    <>
      <Cabecalho
        titulo="Não conformidades"
        apoio="Toda etapa reprovada abre uma NC automaticamente. Decida aqui o tratamento: retrabalho (corrige e ensaia de novo), sucata (abate a quantidade do lote), uso como está (aceita com desvio, exige aprovação) ou anulada (erro de digitação)."
      />

      <div>
        <nav className="abas" aria-label="Situação das não conformidades">
          {ABAS.map((a) => (
            <Link
              key={a.chave}
              to={{ pathname: '/nao-conformidades', search: consulta({ aba: a.chave === 'abertas' ? '' : a.chave }) }}
              className={`aba ${a.chave === aba ? 'aba-atual' : ''}`}
              aria-current={a.chave === aba ? 'page' : undefined}
              onClick={() => setBusca('')}
            >
              {a.rotulo}
              {carga.dados && <span className="nc-contagem">{inteiro(carga.dados.contagens[a.chave])}</span>}
            </Link>
          ))}
        </nav>
        <section className="cartao cartao-aba" aria-label={infoAba.rotulo}>
          {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
          {!carga.erro && !dados && <Carregando />}
          {dados && (
            <div className={carga.carregando ? 'recarregando' : ''}>
              {dados.itens.length > 0 && (
                <div className="filtros nc-filtros">
                  <div className="campo campo-busca">
                    <label htmlFor="nc-busca">Procurar</label>
                    <input
                      id="nc-busca"
                      type="search"
                      value={busca}
                      onChange={(e) => setBusca(e.target.value)}
                      placeholder="NC, OP, lote, etapa, motivo…"
                    />
                  </div>
                  {busca && (
                    <button type="button" className="botao botao-fantasma" onClick={() => setBusca('')}>
                      Limpar
                    </button>
                  )}
                </div>
              )}
              {dados.itens.length === 0 ? (
                <Vazio titulo={infoAba.vazio} />
              ) : visiveis.length === 0 ? (
                <Vazio titulo="Nenhuma não conformidade com esse texto.">
                  <button type="button" className="botao-link" onClick={() => setBusca('')}>
                    Mostrar todas
                  </button>
                </Vazio>
              ) : (
                <ul className="nc-lista">
                  {visiveis.map((nc) => (
                    <ItemNc key={nc.id} nc={nc} />
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
