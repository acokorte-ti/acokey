import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga } from '../componentes/Estados';
import { SeloNc, SeloNcAberta, SeloRegistro, SeloSituacaoEtapa, SeloTipo } from '../componentes/Selos';
import { api, enderecoApi, ErroApi } from '../lib/api';
import { dataHoraLocal, haDias, inteiro, pecas, TRACO } from '../lib/formato';
import type { EtapaDoLote, EventoLote, LoteDetalhe, LoteResumo, NcDoLote, RegistroEtapa } from '../lib/tipos';
import { useCarga } from '../lib/useCarga';

/** A linha do tempo abre com os eventos mais recentes; o resto fica atrás de um botão. */
const LIMITE_EVENTOS = 20;

/** Disposições de não conformidade conhecidas; o que não estiver aqui aparece como veio. */
const DISPOSICOES: Record<string, string> = {
  retrabalho: 'Retrabalho',
  sucata: 'Sucata',
  uso_como_esta: 'Uso como está',
  anulada: 'Anulada (erro de digitação)',
};

function textoOuTraco(texto: string | null | undefined): string {
  return texto && texto.trim() ? texto : TRACO;
}

/** "19/11/2026 07:30 · Fulano": só o que o registro tiver. */
function quandoEQuem(registro: RegistroEtapa): string {
  return [registro.quando ? dataHoraLocal(registro.quando) : '', registro.responsavel.trim()].filter(Boolean).join(' · ');
}

// ---------------------------------------------------------------- dados do lote

function DadosDoLote({ lote }: { lote: LoteResumo }) {
  const { aprovadas, total } = lote.progresso;
  const maximo = Math.max(total, 1);

  return (
    <section className="cartao" aria-labelledby="titulo-dados">
      <div className="cartao-topo">
        <h2 id="titulo-dados">Dados do lote</h2>
        <span className="acoes-linha">
          {lote.concluido ? <span className="selo selo-ok">Concluído</span> : <span className="selo selo-andamento">Em andamento</span>}
          {lote.nc_aberta && <SeloNcAberta />}
        </span>
      </div>
      <dl className="ficha ficha-linha">
        <div>
          <dt>Lote</dt>
          <dd className="mono">{lote.numero}</dd>
        </div>
        <div>
          <dt>OP</dt>
          <dd className="mono">{textoOuTraco(lote.op)}</dd>
        </div>
        <div>
          <dt>Tipo</dt>
          <dd>
            <SeloTipo tipo={lote.tipo} />
          </dd>
        </div>
        <div>
          <dt>Quantidade</dt>
          <dd>{pecas(lote.qtd)}</dd>
        </div>
        <div>
          <dt>Corrida da matéria-prima</dt>
          <dd className="mono">{textoOuTraco(lote.corrida)}</dd>
        </div>
        <div>
          <dt>Item (CODITEM)</dt>
          <dd className="mono">{textoOuTraco(lote.coditem)}</dd>
        </div>
        <div>
          <dt>Criado em</dt>
          <dd>{dataHoraLocal(lote.criado_em)}</dd>
        </div>
        {lote.etapa_atual && (
          <div>
            <dt>Etapa atual</dt>
            <dd>
              {lote.etapa_atual.curto} <span className="sub-linha">· {lote.etapa_atual.setor}</span>
            </dd>
          </div>
        )}
        {!lote.concluido && lote.etapa_desde && (
          <div>
            <dt>Nesta etapa desde</dt>
            <dd>
              {dataHoraLocal(lote.etapa_desde)}
              {lote.dias_na_etapa !== null && <span className="sub-linha"> · {haDias(lote.dias_na_etapa)}</span>}
            </dd>
          </div>
        )}
      </dl>
      <div className="progresso">
        <progress className="progresso-barra" max={maximo} value={Math.min(aprovadas, maximo)} aria-label="Etapas aprovadas" />
        <span className="progresso-texto">
          {inteiro(aprovadas)} de {inteiro(total)} {total === 1 ? 'etapa aprovada' : 'etapas aprovadas'}
        </span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- etapas

function ItemEtapa({ etapa, passo }: { etapa: EtapaDoLote; passo: number }) {
  // Só o laboratório externo tem subdivisão (tração / Charpy); nas outras o nome da "sub" seria repetição
  const comSubdivisao = etapa.subs.some((s) => s.sub !== '');
  const nomeDaSub = (sub: string) => etapa.subs.find((s) => s.sub === sub)?.nome ?? sub;
  // Etapa que ainda vai acontecer e não tem nada lançado: só o título
  const mostrarRegistros =
    etapa.aplicavel && etapa.subs.length > 0 && (etapa.situacao !== 'futura' || etapa.subs.some((s) => s.registro !== null));
  const temCorpo = mostrarRegistros || etapa.anexos.length > 0;

  return (
    <li className={`etapa etapa-${etapa.situacao}`}>
      <div className="etapa-topo">
        <span className="etapa-passo" aria-hidden="true">
          {passo}
        </span>
        <div className="etapa-nome">
          <h3>{etapa.nome}</h3>
          <span className="sub-linha">{etapa.setor}</span>
        </div>
        <SeloSituacaoEtapa situacao={etapa.situacao} />
      </div>
      {temCorpo && (
        <div className="etapa-corpo">
          {mostrarRegistros && (
            <ul className="registros" aria-label={`Registros de ${etapa.curto}`}>
              {etapa.subs.map((s) => (
                <li key={s.sub} className="registro">
                  {comSubdivisao && <span className="registro-nome">{s.nome}</span>}
                  {s.registro ? (
                    <>
                      <SeloRegistro status={s.registro.status} />
                      <span className="registro-meta">{quandoEQuem(s.registro)}</span>
                    </>
                  ) : (
                    <span className="registro-meta">Sem registro ainda</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {etapa.anexos.length > 0 && (
            <div>
              <p className="etapa-rotulo">Anexos</p>
              <ul className="anexos" aria-label={`Anexos de ${etapa.curto}`}>
                {etapa.anexos.map((anexo) => (
                  <li key={anexo.id} className="anexo">
                    <a href={enderecoApi(`/anexos/${anexo.id}/arquivo`)} target="_blank" rel="noopener">
                      {anexo.nome}
                      <span className="so-leitor"> (abre em outra aba)</span>
                    </a>
                    {comSubdivisao && anexo.sub !== '' && <span className="registro-meta">{nomeDaSub(anexo.sub)}</span>}
                    {anexo.quando && <span className="registro-meta">{dataHoraLocal(anexo.quando)}</span>}
                    {anexo.apenas_registro && <span className="rotulo-discreto">só registro interno</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------- não conformidades

function NaoConformidades({ ncs, etapas }: { ncs: NcDoLote[]; etapas: EtapaDoLote[] }) {
  /** "Tração / Charpy · Charpy": a etapa e, quando houver, a subdivisão em que a NC foi aberta. */
  function ondeFoi(nc: NcDoLote): string {
    const etapa = etapas.find((e) => e.chave === nc.etapa);
    if (!etapa) return nc.sub ? `${nc.etapa} · ${nc.sub}` : nc.etapa;
    if (!nc.sub) return etapa.curto;
    return `${etapa.curto} · ${etapa.subs.find((s) => s.sub === nc.sub)?.nome ?? nc.sub}`;
  }

  function disposicao(nc: NcDoLote) {
    if (nc.disposicao) return DISPOSICOES[nc.disposicao] ?? nc.disposicao;
    return nc.status === 'encerrada' ? TRACO : <span className="automatico-vazio">a decidir</span>;
  }

  return (
    <section className="cartao" aria-labelledby="titulo-ncs">
      <h2 id="titulo-ncs">Não conformidades</h2>
      {ncs.length === 0 ? (
        <p className="dica">Nenhuma não conformidade registrada neste lote.</p>
      ) : (
        <div className="tabela-rolagem">
          <table className="tabela">
            <caption className="so-leitor">Não conformidades do lote</caption>
            <thead>
              <tr>
                <th scope="col">Número</th>
                <th scope="col">Etapa</th>
                <th scope="col">Situação</th>
                <th scope="col">Disposição</th>
              </tr>
            </thead>
            <tbody>
              {ncs.map((nc) => (
                <tr key={nc.id}>
                  <td className="mono">{nc.numero}</td>
                  <td>{ondeFoi(nc)}</td>
                  <td>
                    <SeloNc status={nc.status} />
                  </td>
                  <td>{disposicao(nc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- linha do tempo

function LinhaDoTempo({ eventos }: { eventos: EventoLote[] }) {
  const [verTodos, setVerTodos] = useState(false);
  const visiveis = verTodos ? eventos : eventos.slice(0, LIMITE_EVENTOS);

  return (
    <section className="cartao" aria-labelledby="titulo-eventos">
      <h2 id="titulo-eventos">Linha do tempo</h2>
      {eventos.length === 0 ? (
        <p className="dica">Nenhum evento registrado neste lote.</p>
      ) : (
        <>
          <p className="dica">Do mais recente para o mais antigo.</p>
          <ol className="linha-tempo">
            {visiveis.map((evento, indice) => (
              // Os eventos não têm id; a lista só muda de tamanho (nunca de ordem), então a posição serve de chave
              <li key={indice}>
                <span className="linha-tempo-quando">{dataHoraLocal(evento.quando)}</span>
                <span className="linha-tempo-texto">{evento.texto}</span>
              </li>
            ))}
          </ol>
          {eventos.length > LIMITE_EVENTOS && (
            <button type="button" className="botao-link ver-todas" onClick={() => setVerTodos((v) => !v)}>
              {verTodos ? `Mostrar só os ${LIMITE_EVENTOS} mais recentes` : `Mostrar todos os ${inteiro(eventos.length)}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- tela

/** Página do lote (somente leitura): dados, progresso, etapas com registros e anexos, NCs e linha do tempo. */
export function Lote() {
  const { id = '' } = useParams();
  const idValido = /^\d+$/.test(id);
  const carga = useCarga<LoteDetalhe>(
    (sinal) => (idValido ? api(`/lotes/${id}`, { sinal }) : Promise.reject(new ErroApi(404, 'Lote não encontrado.'))),
    [id],
  );
  // Ao trocar de lote, os dados do anterior ficam na memória até o novo chegar: não mostra um lote no endereço de outro
  const dados = carga.dados && carga.dados.lote.id === Number(id) ? carga.dados : null;

  return (
    <>
      <Cabecalho titulo={dados ? `Lote ${dados.lote.numero}` : 'Lote'} apoio={dados ? `OP ${textoOuTraco(dados.lote.op)}` : undefined}>
        <Link to="/" className="botao">
          ← Voltar ao painel
        </Link>
      </Cabecalho>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={idValido ? carga.recarregar : undefined} />}
      {!carga.erro && !dados && <Carregando />}

      {dados && (
        <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`} aria-busy={carga.carregando}>
          <DadosDoLote lote={dados.lote} />

          <section aria-labelledby="titulo-etapas">
            <h2 id="titulo-etapas">Etapas do processo</h2>
            <ol className="etapas">
              {dados.etapas.map((etapa, indice) => (
                <ItemEtapa key={etapa.chave} etapa={etapa} passo={indice + 1} />
              ))}
            </ol>
          </section>

          <NaoConformidades ncs={dados.ncs} etapas={dados.etapas} />
          <LinhaDoTempo eventos={dados.eventos} />
        </div>
      )}
    </>
  );
}
