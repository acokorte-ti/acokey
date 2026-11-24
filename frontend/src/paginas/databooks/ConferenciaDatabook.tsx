import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api, consulta, enderecoApi, ErroApi } from '../../lib/api';
import { dataHoraLocal, inteiro } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import type { ConferenciaDatabook, Inconsistencia } from './tipos';

function Marcas({ valores, esperado }: { valores: string[]; esperado?: string }) {
  if (valores.length === 0) return <span className="sub-linha">nenhum</span>;
  return (
    <span className="db-marcas">
      {valores.map((v) => (
        <span key={v} className={`db-marca ${v === esperado ? 'db-marca-ok' : 'db-marca-erro'}`}>
          {v}
          <span className="so-leitor">{v === esperado ? ' (certo)' : ' (diferente do esperado)'}</span>
        </span>
      ))}
    </span>
  );
}

function Numero({ rotulo, valor, classe = '' }: { rotulo: string; valor: number | undefined; classe?: string }) {
  return (
    <div className={`cartao-numero ${classe}`}>
      <span className="cartao-rotulo">{rotulo}</span>
      <span className="cartao-valor">{inteiro(valor)}</span>
    </div>
  );
}

/** /databooks/conferir/:loteId — páginas do databook que citam OP ou lote diferente do lote (documento trocado). */
export function ConferenciaDatabookTela() {
  const { loteId = '' } = useParams();
  const [parametros] = useSearchParams();
  const arquivo = parametros.get('arquivo') ?? '';
  const idValido = /^\d+$/.test(loteId);
  const carga = useCarga<ConferenciaDatabook>(
    (sinal) =>
      idValido
        ? api(`/databooks/lote/${loteId}/conferencia${consulta({ arquivo })}`, { sinal })
        : Promise.reject(new ErroApi(404, 'Lote não encontrado.')),
    [loteId, arquivo],
  );
  const dados = carga.dados;
  const pdf = enderecoApi(`/databooks/lote/${loteId}/pdf`, { arquivo });
  const r = dados?.resultado;
  const inconsistencias: Inconsistencia[] = r?.inconsistencias ?? [];

  return (
    <>
      <Cabecalho
        titulo="Conferência do databook"
        apoio={dados ? `OP ${dados.lote.op} · Lote ${dados.lote.numero}` : undefined}
      >
        {idValido && (
          <Link to={`/lotes/${loteId}`} className="botao">
            ← Voltar ao lote
          </Link>
        )}
        {dados && (
          <a href={pdf} target="_blank" rel="noopener" className="botao botao-primario">
            Abrir databook<span className="so-leitor"> (abre em outra aba)</span>
          </a>
        )}
      </Cabecalho>

      <Faixa tipo="info">
        Lê cada página do PDF procurando referências de <strong>OP</strong> e de <strong>número de lote completo</strong> e aponta as
        páginas que citam valores diferentes do lote em análise. Serve para pegar documento trocado por engano (ex.: relatório da OP X
        anexado como se fosse da OP Y).
      </Faixa>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={idValido ? carga.recarregar : undefined} />}
      {!carga.erro && !dados && <Carregando texto="Lendo as páginas do databook…" />}

      {dados && r && (
        <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`} style={{ marginTop: 16 }}>
          <section className="cartao" aria-labelledby="db-titulo-arquivo">
            <h2 id="db-titulo-arquivo">Arquivo analisado</h2>
            <p>
              <strong className="mono">{dados.arquivo}</strong> <SeloTipo tipo={dados.lote.tipo} />
              <span className="sub-linha"> · gerado em {dataHoraLocal(dados.gerado_em)}</span>
            </p>
            <p className="dica">
              Esperado em todas as páginas: OP <strong className="mono">{dados.lote.op}</strong> · Lote{' '}
              <strong className="mono">{dados.lote.numero}</strong>
            </p>
          </section>

          {!r.ok ? (
            <Faixa tipo="erro" papel="alert">
              {r.erro}
            </Faixa>
          ) : (
            <>
              <div className="db-numeros">
                <Numero rotulo="Páginas totais" valor={r.total_paginas} />
                <Numero rotulo="Com referência a OP/lote" valor={r.paginas_com_referencia} />
                <Numero rotulo="Páginas OK" valor={r.paginas_ok} classe="db-numero-ok" />
                <Numero rotulo="Inconsistências" valor={inconsistencias.length} classe={inconsistencias.length ? 'db-numero-erro' : ''} />
              </div>

              {inconsistencias.length > 0 ? (
                <section className="cartao" aria-labelledby="db-titulo-inconsistencias">
                  <h2 id="db-titulo-inconsistencias" className="texto-erro">
                    Páginas com OP/lote diferente do esperado
                  </h2>
                  <p className="dica">
                    Cada linha é uma página que cita uma OP ou um lote que não bate com o esperado ({dados.lote.op} / {dados.lote.numero}).
                    Abra o databook na página indicada para conferir: pode ser documento trocado por engano, ou um laudo compartilhado (ex.:
                    Charpy em conjunto com outra OP), e aí a diferença é esperada.
                  </p>
                  <div className="tabela-rolagem">
                    <table className="tabela">
                      <caption className="so-leitor">Páginas com OP ou lote diferente do esperado</caption>
                      <thead>
                        <tr>
                          <th scope="col">Página</th>
                          <th scope="col">OPs encontradas</th>
                          <th scope="col">Lotes encontrados</th>
                          <th scope="col">Trecho</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inconsistencias.map((inc) => (
                          <tr key={inc.pagina} className="db-linha-erro">
                            <td>
                              <a
                                className="db-pagina"
                                href={`${pdf}#page=${inc.pagina}`}
                                target="_blank"
                                rel="noopener"
                                title="Abrir o databook direto nesta página"
                              >
                                {inc.pagina}
                                <span aria-hidden="true">🔍</span>
                                <span className="so-leitor"> (abre o databook nesta página, em outra aba)</span>
                              </a>
                            </td>
                            <td>
                              <Marcas valores={inc.ops_todas} esperado={r.op_esperada} />
                            </td>
                            <td>
                              <Marcas valores={inc.lotes_todos} esperado={r.lote_esperado} />
                            </td>
                            <td className="db-trecho">…{inc.contexto}…</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="dica">
                    Clique no número da página para abrir o databook já nela (funciona no visualizador de PDF do navegador: Chrome/Edge).
                  </p>
                </section>
              ) : (
                <Faixa tipo="sucesso">
                  Todas as {inteiro(r.paginas_com_referencia)} página(s) com referência batem com OP {dados.lote.op} / Lote{' '}
                  {dados.lote.numero}.
                </Faixa>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
