import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { Confirmacao, ModalFormulario } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, baixarArquivo, enderecoApi, enviarArquivos, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataCurta, dataHoraLocal, inteiro } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import { ModalMotivo, NotaNatureza, pesoBr, QuadroEspecificacao, SeloDias, SeloStatusEnvio } from './comum';
import { SlotsFotos } from './SlotsFotos';
import type { EnvioDetalhe, FotoEnvio } from './tipos';

type Acao = { tipo: 'retornado' } | { tipo: 'cancelar' } | { tipo: 'reabrir' } | { tipo: 'remover-foto'; foto: FotoEnvio } | null;

/** Data de hoje no computador de quem usa (AAAA-MM-DD), para o padrão do campo de data. */
function hojeLocal(): string {
  const agora = new Date();
  return `${agora.getFullYear()}-${String(agora.getMonth() + 1).padStart(2, '0')}-${String(agora.getDate()).padStart(2, '0')}`;
}

function TabelaQuantidades({ envio }: { envio: EnvioDetalhe }) {
  const temT = envio.itens.some((i) => i.qt_cp_tracao > 0);
  const temI = envio.itens.some((i) => i.qt_cp_impacto > 0);
  if (!envio.modo_pecas && !temT && !temI && !envio.qtd_cps) return null;
  return (
    <section className="cartao" aria-labelledby="env-det-qtd">
      <h2 id="env-det-qtd">
        {envio.modo_pecas ? (
          <>
            Peças por OP <span className="sub-linha">(dados de transporte)</span>
          </>
        ) : (
          'Corpos de prova por OP'
        )}
      </h2>
      {(envio.modo_pecas || temT || temI) && (
        <div className="tabela-rolagem env-tabela-curta">
          <table className="tabela">
            <caption className="so-leitor">Quantidades por OP</caption>
            <thead>
              <tr>
                <th scope="col">OP</th>
                {envio.modo_pecas ? (
                  <>
                    <th scope="col">CODITEM</th>
                    <th scope="col" className="num">Qtd liberada</th>
                    <th scope="col" className="num">Volumes</th>
                    <th scope="col" className="num">Peso líq. (kg)</th>
                    <th scope="col" className="num">Peso bruto (kg)</th>
                  </>
                ) : (
                  <>
                    {temT && <th scope="col" className="num">CP Tração</th>}
                    {temI && <th scope="col" className="num">CP Impacto Charpy</th>}
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {envio.itens.map((i) => (
                <tr key={i.lote_id}>
                  <td>
                    OP <strong>{i.op}</strong> <span className="sub-linha">· {i.tipo}</span>
                  </td>
                  {envio.modo_pecas ? (
                    <>
                      <td className="mono">{i.coditem || '—'}</td>
                      <td className="num">{inteiro(i.qt_liberar || i.qtd)}</td>
                      <td className="num">{inteiro(i.volumes)}</td>
                      <td className="num">{pesoBr(i.peso_liq)}</td>
                      <td className="num">{pesoBr(i.peso_bruto)}</td>
                    </>
                  ) : (
                    <>
                      {temT && <td className="num">{inteiro(i.qt_cp_tracao)}</td>}
                      {temI && <td className="num">{inteiro(i.qt_cp_impacto)}</td>}
                    </>
                  )}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="env-total">
                <th scope="row" colSpan={envio.modo_pecas ? 2 : 1}>
                  {envio.modo_pecas ? 'Total (fins de transporte)' : 'Total'}
                </th>
                {envio.modo_pecas ? (
                  <>
                    <td className="num">{inteiro(envio.totais.qt_liberar)}</td>
                    <td className="num">{inteiro(envio.totais.volumes)}</td>
                    <td className="num">{pesoBr(envio.totais.peso_liq)}</td>
                    <td className="num">{pesoBr(envio.totais.peso_bruto)}</td>
                  </>
                ) : (
                  <>
                    {temT && <td className="num">{inteiro(envio.totais.qt_cp_tracao)}</td>}
                    {temI && <td className="num">{inteiro(envio.totais.qt_cp_impacto)}</td>}
                  </>
                )}
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {envio.qtd_cps && <p className="dica">Nota antiga: {envio.qtd_cps}</p>}
    </section>
  );
}

export function DetalheEnvio() {
  const { id } = useParams();
  const avisos = useAvisos();
  const envio = useCarga<EnvioDetalhe>((sinal) => api(`/envios/${id}`, { sinal }), [id]);
  const [acao, setAcao] = useState<Acao>(null);
  const [dataRetorno, setDataRetorno] = useState(hojeLocal());
  const [gravando, setGravando] = useState(false);
  const [erroAcao, setErroAcao] = useState<string | null>(null);
  const [novasFotos, setNovasFotos] = useState<File[]>([]);
  const [enviandoFotos, setEnviandoFotos] = useState(false);
  const [baixando, setBaixando] = useState(false);

  if (envio.erro) {
    return (
      <>
        <Cabecalho titulo="Envio a prestador" />
        <ErroCarga mensagem={envio.erro} aoTentar={envio.recarregar} />
        <Link to="/envios">Voltar para a lista de envios</Link>
      </>
    );
  }
  if (!envio.dados) {
    return (
      <>
        <Cabecalho titulo="Envio a prestador" />
        <Carregando />
      </>
    );
  }
  const e = envio.dados;

  function fechar() {
    setAcao(null);
    setErroAcao(null);
    setGravando(false);
  }

  async function mudarStatus(status: string, extra: Record<string, string> = {}, mensagem = '') {
    setGravando(true);
    setErroAcao(null);
    try {
      await api(`/envios/${e.id}/status`, { metodo: 'POST', corpo: { status, ...extra } });
      avisos.sucesso(mensagem || `Envio ${e.numero} marcado como ${status}.`);
      fechar();
      envio.recarregar();
    } catch (falha) {
      setErroAcao(mensagemDeErro(falha));
      setGravando(false);
    }
  }

  async function enviarFotos() {
    if (!novasFotos.length) return;
    setEnviandoFotos(true);
    try {
      const r = await enviarArquivos<{ adicionadas: number }>(`/envios/${e.id}/fotos`, { arquivos: novasFotos });
      avisos.sucesso(`${r.adicionadas} foto(s) adicionada(s) ao envio ${e.numero}.`);
      setNovasFotos([]);
      envio.recarregar();
    } catch (falha) {
      avisos.erro(mensagemDeErro(falha));
    } finally {
      setEnviandoFotos(false);
    }
  }

  async function baixarModelo() {
    setBaixando(true);
    try {
      await baixarArquivo(`/envios/${e.id}/modelo-ensaio`);
    } catch (falha) {
      avisos.erro(mensagemDeErro(falha));
    } finally {
      setBaixando(false);
    }
  }

  const botaoPdf = (
    <a className="botao" href={enderecoApi(`/envios/${e.id}/pdf`)} target="_blank" rel="noopener">
      Gerar PDF do envio<span className="so-leitor"> (abre em outra aba)</span>
    </a>
  );
  const botaoModelo = e.modelo_ensaio && (
    <button type="button" className="botao" onClick={() => void baixarModelo()} disabled={baixando}>
      {baixando ? 'Preparando…' : 'Preencher modelo do laboratório (.docx)'}
    </button>
  );

  return (
    <>
      <nav className="env-trilha" aria-label="Você está em">
        <Link to="/envios">Envios a prestador</Link> › <strong>{e.numero}</strong>
      </nav>
      <Cabecalho
        titulo={`Envio ${e.numero}`}
        apoio={
          <>
            <strong>{e.prestador}</strong> · {e.tipo_servico}
            {e.data_envio && <> · enviado em {dataCurta(e.data_envio)}</>}
            {e.data_retorno && <> · retornado em {dataCurta(e.data_retorno)}</>}
          </>
        }
      >
        {e.pode_editar && (
          <Link className="botao" to={`/envios/${e.id}/editar`}>
            Editar envio
          </Link>
        )}
        {botaoPdf}
        {botaoModelo}
      </Cabecalho>

      <section className="cartao">
        <div className="env-cartao-topo">
          <SeloStatusEnvio status={e.status} />
          {e.status === 'enviado' && <SeloDias dias={e.dias_envio} alerta={e.parado} />}
          <span className="sub-linha">
            Criado em {dataHoraLocal(e.criado_em)} por {e.criado_por || '—'}
            {e.responsavel && <> · responsável pelo envio: {e.responsavel}</>}
            {e.data_emissao && <> · emitido em {dataCurta(e.data_emissao)}</>}
          </span>
        </div>
        <NotaNatureza natureza={e.natureza} />
        {e.status === 'cancelado' && (
          <Faixa tipo="erro">
            Cancelado em {dataHoraLocal(e.cancelado_em)} por {e.cancelado_por || '—'}: {e.cancelado_motivo || 'sem motivo registrado'}.
          </Faixa>
        )}
      </section>

      <section className="cartao" aria-labelledby="env-det-lotes">
        <h2 id="env-det-lotes">Lotes neste envio ({inteiro(e.itens.length)})</h2>
        <p className="dica">
          {e.etapa_referencia ? (
            <>
              O sistema marca <strong className="env-laudo">✓ Laudo lançado</strong> quando a etapa correspondente ({e.etapa_referencia}) do
              lote já tem registro aprovado ou reprovado com data igual ou posterior ao envio.
            </>
          ) : (
            'Este tipo de serviço não tem etapa correspondente no lote: marque o retorno quando o material voltar.'
          )}
        </p>
        <div className="env-grade-lotes">
          {e.itens.map((i) => (
            <div key={i.lote_id} className={`env-lote-item ${i.retornou ? 'env-lote-item-ok' : ''}`}>
              <div>
                <Link to={`/lotes/${i.lote_id}`}>
                  <strong>OP {i.op}</strong>
                </Link>{' '}
                <SeloTipo tipo={i.tipo} />
                {i.cancelado && <span className="selo selo-inativo">Lote cancelado</span>}
              </div>
              <div className="sub-linha">
                Lote <strong className="mono">{i.numero}</strong> · {inteiro(i.qtd)} pçs · {i.cliente}
              </div>
              <div className="sub-linha">Etapa atual: {i.etapa_atual}</div>
              {i.retornou && <div className="env-laudo">✓ Laudo lançado na etapa</div>}
            </div>
          ))}
        </div>
        {e.todos_retornaram && e.status === 'enviado' && (
          <Faixa tipo="sucesso">
            Todos os lotes já têm laudo lançado na etapa. Você pode marcar este envio como <strong>retornado</strong>.{' '}
            <button type="button" className="botao botao-pequeno" onClick={() => setAcao({ tipo: 'retornado' })}>
              Marcar como retornado
            </button>
          </Faixa>
        )}
      </section>

      <TabelaQuantidades envio={e} />

      {e.especificacao.length > 0 && (
        <section className="cartao">
          <QuadroEspecificacao
            titulo="Especificação solicitada"
            especificacao={e.especificacao}
            normaCodigo={e.norma_codigo}
            apoio="Valores congelados no momento do envio: alterações futuras nas especificações não afetam este registro."
          />
        </section>
      )}

      <section className="cartao" aria-labelledby="env-det-fotos">
        <h2 id="env-det-fotos">
          {e.rotulo_fotos} <span className="sub-linha">({inteiro(e.fotos.length)})</span>
        </h2>
        {e.fotos.length === 0 ? (
          <p className="dica">Nenhuma foto adicionada ainda.</p>
        ) : (
          <div className="env-fotos-grade">
            {e.fotos.map((foto) => (
              <figure key={foto.id} className="env-foto">
                <a href={enderecoApi(`/envios/fotos/${foto.id}/arquivo`)} target="_blank" rel="noopener" title="Abrir a foto em outra aba">
                  <img src={enderecoApi(`/envios/fotos/${foto.id}/arquivo`)} alt={foto.nome} loading="lazy" />
                </a>
                <figcaption title={foto.nome}>{foto.nome}</figcaption>
                {e.pode_editar && (
                  <button
                    type="button"
                    className="env-foto-tirar"
                    aria-label={`Remover a foto ${foto.nome}`}
                    onClick={() => setAcao({ tipo: 'remover-foto', foto })}
                  >
                    ×
                  </button>
                )}
              </figure>
            ))}
          </div>
        )}
        {e.pode_editar && (
          <div className="pilha env-fotos-novas">
            <SlotsFotos fotos={novasFotos} aoMudar={setNovasFotos} desabilitado={enviandoFotos} />
            <div>
              <button type="button" className="botao" onClick={() => void enviarFotos()} disabled={!novasFotos.length || enviandoFotos}>
                {enviandoFotos ? 'Enviando…' : `Adicionar ${novasFotos.length || ''} foto(s)`}
              </button>
            </div>
          </div>
        )}
      </section>

      {e.observacoes && (
        <section className="cartao" aria-labelledby="env-det-obs">
          <h2 id="env-det-obs">Observações</h2>
          <p className="env-texto-livre">{e.observacoes}</p>
        </section>
      )}

      <section className="cartao" aria-labelledby="env-det-acoes">
        <h2 id="env-det-acoes">Ações</h2>
        <div className="acoes">
          {e.status === 'enviado' && (
            <>
              <button type="button" className="botao botao-primario" onClick={() => setAcao({ tipo: 'retornado' })}>
                Marcar como retornado
              </button>
              <button type="button" className="botao botao-perigo-contorno" onClick={() => setAcao({ tipo: 'cancelar' })}>
                Cancelar envio
              </button>
            </>
          )}
          {e.status === 'retornado' && (
            <button type="button" className="botao" onClick={() => setAcao({ tipo: 'reabrir' })}>
              Reabrir como enviado
            </button>
          )}
          <Link className="botao botao-fantasma" to="/envios">
            ← Voltar
          </Link>
        </div>
      </section>

      {acao?.tipo === 'retornado' && (
        <ModalFormulario
          titulo={`Marcar o envio ${e.numero} como retornado`}
          aoFechar={fechar}
          aoEnviar={() => void mudarStatus('retornado', { data_retorno: dataRetorno }, `Envio ${e.numero} marcado como retornado.`)}
          enviando={gravando}
          erro={erroAcao}
          rotuloEnviar="Marcar como retornado"
        >
          <Campo rotulo="Data de retorno" para="env-data-retorno" obrigatorio>
            <input id="env-data-retorno" type="date" value={dataRetorno} onChange={(ev) => setDataRetorno(ev.target.value)} required />
          </Campo>
          {!e.todos_retornaram && e.etapa_referencia && (
            <Faixa tipo="alerta">Atenção: ainda há lote sem laudo lançado na etapa ({e.etapa_referencia}).</Faixa>
          )}
        </ModalFormulario>
      )}
      {acao?.tipo === 'reabrir' && (
        <Confirmacao
          titulo={`Reabrir o envio ${e.numero}`}
          rotuloConfirmar="Reabrir como enviado"
          aoFechar={fechar}
          aoConfirmar={() => void mudarStatus('enviado', {}, `Envio ${e.numero} reaberto como enviado.`)}
          enviando={gravando}
        >
          <p>O envio volta para a aba Enviados e a data de retorno é apagada.</p>
          {erroAcao && <p className="erro-formulario">{erroAcao}</p>}
        </Confirmacao>
      )}
      {acao?.tipo === 'cancelar' && (
        <ModalMotivo
          titulo={`Cancelar o envio ${e.numero}`}
          rotuloConfirmar="Cancelar envio"
          perigo
          aoFechar={fechar}
          aoConfirmar={async (motivo) => {
            await api(`/envios/${e.id}/status`, { metodo: 'POST', corpo: { status: 'cancelado', motivo } });
            avisos.sucesso(`Envio ${e.numero} cancelado.`);
            fechar();
            envio.recarregar();
          }}
        >
          <p>
            O envio sai da lista de enviados, mas continua guardado (nada é apagado). Isto não mexe em nada dos lotes.
          </p>
        </ModalMotivo>
      )}
      {acao?.tipo === 'remover-foto' && (
        <ModalMotivo
          titulo="Remover foto"
          rotuloConfirmar="Remover foto"
          perigo
          aoFechar={fechar}
          aoConfirmar={async (motivo) => {
            await api(`/envios/fotos/${acao.foto.id}/remover`, { metodo: 'POST', corpo: { motivo } });
            avisos.sucesso('Foto removida.');
            fechar();
            envio.recarregar();
          }}
        >
          <p>
            A foto <strong>{acao.foto.nome}</strong> sai do envio e do PDF. O arquivo continua guardado no servidor.
          </p>
        </ModalMotivo>
      )}
    </>
  );
}
