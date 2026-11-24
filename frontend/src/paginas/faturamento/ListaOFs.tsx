import { Fragment, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Vazio } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api, consulta, enderecoApi } from '../../lib/api';
import { contemTermos, dataCurta, inteiro } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import type { AbaOF, ListaOFs as Lista, OFResumo, StatusOF } from './tipos';

const ABAS: { chave: AbaOF; rotulo: string }[] = [
  { chave: 'ativas', rotulo: 'Em aberto' },
  { chave: 'faturadas', rotulo: 'Faturadas' },
  { chave: 'canceladas', rotulo: 'Canceladas' },
];

const STATUS: Record<StatusOF, { rotulo: string; classe: string }> = {
  rascunho: { rotulo: 'Rascunho', classe: 'selo-espera' },
  emitida: { rotulo: 'Emitida', classe: 'selo-andamento' },
  faturada: { rotulo: 'Faturada', classe: 'selo-ok' },
  cancelada: { rotulo: 'Cancelada', classe: 'selo-inativo' },
};

export function SeloStatusOF({ status }: { status: StatusOF }) {
  const aparencia = STATUS[status] ?? { rotulo: status, classe: '' };
  return <span className={`selo ${aparencia.classe}`}>{aparencia.rotulo}</span>;
}

function CartaoOF({ of }: { of: OFResumo }) {
  return (
    <article className="env-cartao">
      <div className="env-cartao-corpo">
        <div className="env-cartao-topo">
          <Link to={`/faturamento/${of.id}`} className="env-numero">
            {of.numero}
          </Link>
          <SeloStatusOF status={of.status} />
          <span className="sub-linha">
            {inteiro(of.n_lotes)} {of.n_lotes === 1 ? 'lote' : 'lotes'} · {inteiro(of.total_pecas)} peças · {inteiro(of.total_volumes)} volumes
          </span>
        </div>
        <p className="env-cartao-linha">
          <strong>{of.cliente || '—'}</strong>
          {of.pedido_cliente && (
            <>
              {' '}
              · PO: <strong>{of.pedido_cliente}</strong>
            </>
          )}
          {of.piv && <> · PIV {of.piv}</>}
          {of.data_emissao && <> · emitida em {dataCurta(of.data_emissao)}</>}
          {of.nf_saida && (
            <>
              {' '}
              · NF <strong>{of.nf_saida}</strong>
            </>
          )}
        </p>
        <p className="env-cartao-linha">
          Lotes:{' '}
          {of.lotes.map((lote, indice) => (
            <Fragment key={lote.id}>
              {indice > 0 && ' · '}
              <Link to={`/lotes/${lote.id}`}>OP {lote.op}</Link> <SeloTipo tipo={lote.tipo} />
            </Fragment>
          ))}
        </p>
      </div>
      <div className="env-cartao-acoes">
        <Link className="botao botao-pequeno" to={`/faturamento/${of.id}`}>
          Abrir
        </Link>
        <a className="botao botao-pequeno" href={enderecoApi(`/faturamento/${of.id}/pdf`)} target="_blank" rel="noopener">
          PDF<span className="so-leitor"> (abre em outra aba)</span>
        </a>
      </div>
    </article>
  );
}

export function ListaOFs() {
  const [parametros, setParametros] = useSearchParams();
  const aba = (ABAS.find((a) => a.chave === parametros.get('aba'))?.chave ?? 'ativas') as AbaOF;
  const lista = useCarga<Lista>((sinal) => api(`/faturamento${consulta({ aba })}`, { sinal }), [aba]);
  const [busca, setBusca] = useState('');

  const filtradas = useMemo(
    () =>
      (lista.dados?.itens ?? []).filter((o) =>
        contemTermos(`${o.numero} ${o.cliente} ${o.pedido_cliente} ${o.piv} ${o.nf_saida} ${o.lotes.map((l) => `${l.op} ${l.numero}`).join(' ')}`, busca),
      ),
    [lista.dados, busca],
  );

  return (
    <>
      <Cabecalho
        titulo="Ordens de faturamento"
        apoio={
          <>
            Consolida os lotes prontos para sair fisicamente da fábrica. Só aceita lotes <strong>com todas as etapas aprovadas</strong> e{' '}
            <strong>sem NC aberta</strong>. Volumes = número de caixas ou pacotes.
          </>
        }
      >
        <Link className="botao botao-primario" to="/faturamento/nova">
          + Nova OF
        </Link>
      </Cabecalho>

      <div>
        <nav className="abas" aria-label="Situação das ordens">
          {ABAS.map((a) => (
            <button
              key={a.chave}
              type="button"
              className={`aba env-aba ${a.chave === aba ? 'aba-atual' : ''}`}
              aria-current={a.chave === aba ? 'page' : undefined}
              onClick={() => setParametros(a.chave === 'ativas' ? {} : { aba: a.chave })}
            >
              {a.rotulo} <span className="env-aba-contagem">{inteiro(lista.dados?.contagens[a.chave] ?? 0)}</span>
            </button>
          ))}
        </nav>
        <section className="cartao cartao-aba">
          <div className="filtros">
            <div className="campo campo-busca">
              <label htmlFor="of-busca">Buscar</label>
              <input
                id="of-busca"
                type="search"
                placeholder="Número, cliente, PIV, NF ou OP"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
              />
            </div>
          </div>
          {lista.erro ? (
            <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />
          ) : !lista.dados ? (
            <Carregando />
          ) : filtradas.length === 0 ? (
            <Vazio titulo={busca ? 'Nenhuma OF encontrada com essa busca.' : 'Nenhuma OF nesta aba.'} />
          ) : (
            <div className="env-cartoes">
              {filtradas.map((of) => (
                <CartaoOF key={of.id} of={of} />
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
