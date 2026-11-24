/** Mapa consolidado do lote (legado: /lote/<id>/mapa): etapas, situação, quem aprovou, documentos e histórico, para imprimir. */
import { Link, useParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga } from '../../componentes/Estados';
import { SeloRegistro, SeloTipo } from '../../componentes/Selos';
import { api, enderecoApi, ErroApi } from '../../lib/api';
import { dataHoraLocal, pecas, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import type { MapaDoLote } from './tipos';

export function MapaLote() {
  const { id = '' } = useParams();
  const idValido = /^\d+$/.test(id);
  const carga = useCarga<MapaDoLote>(
    (sinal) => (idValido ? api(`/lotes/${id}/mapa`, { sinal }) : Promise.reject(new ErroApi(404, 'Lote não encontrado.'))),
    [id],
  );
  const dados = carga.dados && carga.dados.lote.id === Number(id) ? carga.dados : null;

  return (
    <div className="lt-mapa">
      <Cabecalho titulo={dados ? `Mapa do lote ${dados.lote.numero}` : 'Mapa do lote'} apoio={dados ? `OP ${dados.lote.op}` : undefined}>
        <Link to={`/lotes/${id}`} className="botao">
          ← Voltar ao lote
        </Link>
        <button type="button" className="botao botao-primario" onClick={() => window.print()} disabled={!dados}>
          Imprimir
        </button>
      </Cabecalho>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={idValido ? carga.recarregar : undefined} />}
      {!carga.erro && !dados && <Carregando />}

      {dados && (
        <div className="pilha">
          <section className="cartao">
            <p className="lt-mapa-resumo">
              <SeloTipo tipo={dados.lote.tipo} /> {pecas(dados.lote.qtd)} · Corrida: <span className="mono">{dados.lote.corrida || TRACO}</span> · Item/desenho:{' '}
              <span className="mono">{dados.lote.coditem || TRACO}</span> · Criado em {dataHoraLocal(dados.lote.criado_em)} ·{' '}
              {dados.concluido ? (
                <strong className="lt-texto-ok">CONCLUÍDO</strong>
              ) : (
                `em andamento, etapa ${dados.etapa_numero} de ${dados.total_etapas}`
              )}
            </p>
          </section>

          <section className="cartao" aria-labelledby="titulo-mapa-etapas">
            <h2 id="titulo-mapa-etapas">Etapas / operações</h2>
            <div className="tabela-rolagem">
              <table className="tabela lt-mapa-tabela">
                <caption className="so-leitor">Etapas do lote, situação e documentos</caption>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Etapa / operação</th>
                    <th scope="col">Setor</th>
                    <th scope="col">Situação</th>
                    <th scope="col">Aprovado em</th>
                    <th scope="col">Por</th>
                    <th scope="col">Documentos anexados</th>
                  </tr>
                </thead>
                <tbody>
                  {dados.linhas.map((linha, i) => (
                    <tr key={`${linha.etapa}-${linha.sub}`} className={`lt-mapa-${linha.status}`}>
                      <td className="num">{i + 1}</td>
                      <td>
                        <strong>{linha.nome}</strong>
                      </td>
                      <td className="sub-linha">{linha.setor}</td>
                      <td>
                        <SeloRegistro status={linha.status} />
                      </td>
                      <td>{linha.quando ? dataHoraLocal(linha.quando) : TRACO}</td>
                      <td>{linha.responsavel || TRACO}</td>
                      <td>
                        {linha.anexos.length === 0
                          ? TRACO
                          : linha.anexos.map((a) => (
                              <div key={a.id}>
                                <a href={enderecoApi(`/anexos/${a.id}/arquivo`)} target="_blank" rel="noopener">
                                  {a.nome}
                                </a>{' '}
                                <span className="registro-meta">{dataHoraLocal(a.quando)}</span>
                              </div>
                            ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="cartao" aria-labelledby="titulo-mapa-historico">
            <h2 id="titulo-mapa-historico">Histórico completo</h2>
            {dados.eventos.length === 0 ? (
              <p className="dica">Nenhum evento registrado.</p>
            ) : (
              <ol className="linha-tempo">
                {dados.eventos.map((evento, indice) => (
                  <li key={indice}>
                    <span className="linha-tempo-quando">{dataHoraLocal(evento.quando)}</span>
                    <span className="linha-tempo-texto">{evento.texto}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
