import { Fragment, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Vazio } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api, consulta, enderecoApi } from '../../lib/api';
import { contemTermos, dataCurta, inteiro } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import { SeloDias, SeloStatusEnvio } from './comum';
import type { AbaEnvios, EnvioResumo, ListaEnvios as Lista } from './tipos';

const ABAS: { chave: AbaEnvios; rotulo: string }[] = [
  { chave: 'ativos', rotulo: 'Enviados' },
  { chave: 'retornados', rotulo: 'Retornados' },
  { chave: 'cancelados', rotulo: 'Cancelados' },
];

function CartaoEnvio({ envio }: { envio: EnvioResumo }) {
  return (
    <article className="env-cartao">
      <div className="env-cartao-corpo">
        <div className="env-cartao-topo">
          <Link to={`/envios/${envio.id}`} className="env-numero">
            {envio.numero}
          </Link>
          <SeloStatusEnvio status={envio.status} />
          {envio.status === 'enviado' && <SeloDias dias={envio.dias_envio} alerta={envio.parado} />}
          <span className="sub-linha">
            {inteiro(envio.n_lotes)} {envio.n_lotes === 1 ? 'lote' : 'lotes'} · {inteiro(envio.total_pecas)} peças
          </span>
        </div>
        <p className="env-cartao-linha">
          <strong>{envio.prestador}</strong> · {envio.tipo_servico} · enviado em {dataCurta(envio.data_envio)}
          {envio.responsavel && <> · por {envio.responsavel}</>}
          {envio.status === 'retornado' && envio.data_retorno && <> · retornou em {dataCurta(envio.data_retorno)}</>}
        </p>
        <p className="env-cartao-linha">
          Lotes:{' '}
          {envio.lotes.map((lote, indice) => (
            <Fragment key={lote.id}>
              {indice > 0 && ' · '}
              <Link to={`/lotes/${lote.id}`}>OP {lote.op}</Link> <SeloTipo tipo={lote.tipo} /> {inteiro(lote.qtd)} pçs
            </Fragment>
          ))}
        </p>
      </div>
      <div className="env-cartao-acoes">
        <Link className="botao botao-pequeno" to={`/envios/${envio.id}`}>
          Abrir
        </Link>
        <a className="botao botao-pequeno" href={enderecoApi(`/envios/${envio.id}/pdf`)} target="_blank" rel="noopener">
          PDF<span className="so-leitor"> (abre em outra aba)</span>
        </a>
      </div>
    </article>
  );
}

export function ListaEnvios() {
  const [parametros, setParametros] = useSearchParams();
  const aba = (ABAS.find((a) => a.chave === parametros.get('aba'))?.chave ?? 'ativos') as AbaEnvios;
  const lista = useCarga<Lista>((sinal) => api(`/envios${consulta({ aba })}`, { sinal }), [aba]);
  const [busca, setBusca] = useState('');

  const filtrados = useMemo(
    () =>
      (lista.dados?.itens ?? []).filter((e) =>
        contemTermos(`${e.numero} ${e.prestador} ${e.tipo_servico} ${e.responsavel} ${e.lotes.map((l) => `${l.op} ${l.numero}`).join(' ')}`, busca),
      ),
    [lista.dados, busca],
  );

  return (
    <>
      <Cabecalho
        titulo="Envios a prestador externo"
        apoio={
          <>
            Registre quando o lote sai para laboratório, revestimento ou NDT externo. Serve de rastro entre o envio físico e a chegada do
            laudo. Quando o resultado voltar e for lançado na etapa correspondente do lote, marque o envio como <strong>retornado</strong>.
          </>
        }
      >
        <Link className="botao botao-primario" to="/envios/novo">
          + Novo envio
        </Link>
      </Cabecalho>

      <div>
        <nav className="abas" aria-label="Situação dos envios">
          {ABAS.map((a) => (
            <button
              key={a.chave}
              type="button"
              className={`aba env-aba ${a.chave === aba ? 'aba-atual' : ''}`}
              aria-current={a.chave === aba ? 'page' : undefined}
              onClick={() => setParametros(a.chave === 'ativos' ? {} : { aba: a.chave })}
            >
              {a.rotulo} <span className="env-aba-contagem">{inteiro(lista.dados?.contagens[a.chave] ?? 0)}</span>
            </button>
          ))}
        </nav>
        <section className="cartao cartao-aba">
          <div className="filtros">
            <div className="campo campo-busca">
              <label htmlFor="env-busca">Buscar</label>
              <input
                id="env-busca"
                type="search"
                placeholder="Número, prestador, OP ou lote"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
              />
            </div>
          </div>
          {lista.erro ? (
            <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />
          ) : !lista.dados ? (
            <Carregando />
          ) : filtrados.length === 0 ? (
            <Vazio titulo={busca ? 'Nenhum envio encontrado com essa busca.' : 'Nenhum envio nesta aba.'} />
          ) : (
            <div className="env-cartoes">
              {filtrados.map((envio) => (
                <CartaoEnvio key={envio.id} envio={envio} />
              ))}
            </div>
          )}
          {aba === 'ativos' && lista.dados && (
            <p className="dica">
              Envio sem retorno há {lista.dados.dias_alerta} dias ou mais aparece com os dias em vermelho (e no painel).
            </p>
          )}
        </section>
      </div>
    </>
  );
}
