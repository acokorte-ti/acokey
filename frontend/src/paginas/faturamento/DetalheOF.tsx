import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { Confirmacao, ModalFormulario } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, enderecoApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataCurta, dataHoraLocal, inteiro, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import { ModalMotivo, pesoBr } from '../envios/comum';
import { SeloStatusOF } from './ListaOFs';
import type { OFDetalhe } from './tipos';

type Acao = 'emitir' | 'faturar' | 'rascunho' | 'cancelar' | null;

/**
 * Abre o PDF numa aba (para salvar e anexar) e um rascunho de e-mail no programa padrão, com destinatário (se houver um
 * e-mail no campo Destinatário), assunto e corpo. O mailto: não deixa anexar arquivo: é limitação do protocolo.
 */
function enviarPorEmail(of: OFDetalhe): void {
  window.open(enderecoApi(`/faturamento/${of.id}/pdf`), '_blank', 'noopener');
  const para = /[\w.+-]+@[\w-]+\.[\w.-]+/.exec(of.destinatario)?.[0] ?? '';
  const cliente = of.cliente || TRACO;
  const ops = [...new Set(of.itens.map((i) => i.op))];
  const assunto = `Ordem de Faturamento ${of.numero} - ${cliente}${of.piv ? ` - PIV ${of.piv}` : ''}`;
  const corpo =
    `Olá,\n\nSegue a Ordem de Faturamento ${of.numero}${of.piv ? ` (PIV ${of.piv})` : ''}.\n\n` +
    `Cliente: ${cliente}\nLotes (OP): ${ops.join(', ') || TRACO}\n\n` +
    'O PDF foi aberto em outra aba — anexe-o a este e-mail antes de enviar.\n\nAtenciosamente.';
  // Clique num link (e não location.href depois): o navegador costuma bloquear mailto: fora do clique original
  const link = document.createElement('a');
  link.href = `mailto:${para}?subject=${encodeURIComponent(assunto)}&body=${encodeURIComponent(corpo)}`;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function DetalheOF() {
  const { id } = useParams();
  const avisos = useAvisos();
  const of = useCarga<OFDetalhe>((sinal) => api(`/faturamento/${id}`, { sinal }), [id]);
  const [acao, setAcao] = useState<Acao>(null);
  const [nf, setNf] = useState('');
  const [gravando, setGravando] = useState(false);
  const [erroAcao, setErroAcao] = useState<string | null>(null);

  if (of.erro) {
    return (
      <>
        <Cabecalho titulo="Ordem de faturamento" />
        <ErroCarga mensagem={of.erro} aoTentar={of.recarregar} />
        <Link to="/faturamento">Voltar para a lista de ordens</Link>
      </>
    );
  }
  if (!of.dados) {
    return (
      <>
        <Cabecalho titulo="Ordem de faturamento" />
        <Carregando />
      </>
    );
  }
  const o = of.dados;

  function fechar() {
    setAcao(null);
    setErroAcao(null);
    setGravando(false);
  }

  async function mudarStatus(status: string, mensagem: string, extra: Record<string, string> = {}) {
    setGravando(true);
    setErroAcao(null);
    try {
      await api(`/faturamento/${o.id}/status`, { metodo: 'POST', corpo: { status, ...extra } });
      avisos.sucesso(mensagem);
      fechar();
      of.recarregar();
    } catch (falha) {
      setErroAcao(mensagemDeErro(falha));
      setGravando(false);
    }
  }

  const pode = (status: string) => o.proximos.includes(status as OFDetalhe['status']);

  return (
    <>
      <nav className="env-trilha" aria-label="Você está em">
        <Link to="/faturamento">Ordens de faturamento</Link> › <strong>{o.numero}</strong>
      </nav>
      <Cabecalho
        titulo={`OF ${o.numero}`}
        apoio={
          <>
            {o.data_emissao && <>Emitida em {dataCurta(o.data_emissao)} · </>}
            criada em {dataHoraLocal(o.criado_em)} por {o.criado_por || TRACO}
          </>
        }
      >
        {o.pode_editar && (
          <Link className="botao" to={`/faturamento/${o.id}/editar`}>
            Editar
          </Link>
        )}
        <a className="botao" href={enderecoApi(`/faturamento/${o.id}/pdf`)} target="_blank" rel="noopener">
          Gerar PDF da OF<span className="so-leitor"> (abre em outra aba)</span>
        </a>
      </Cabecalho>

      <section className="cartao" aria-labelledby="of-det-dados">
        <div className="cartao-topo">
          <h2 id="of-det-dados">Dados</h2>
          <SeloStatusOF status={o.status} />
        </div>
        {o.status === 'faturada' && <Faixa tipo="sucesso">OF faturada: fica travada (não muda mais de situação nem de conteúdo).</Faixa>}
        {o.status === 'cancelada' && (
          <Faixa tipo="erro">
            Cancelada em {dataHoraLocal(o.cancelado_em)} por {o.cancelado_por || TRACO}: {o.cancelado_motivo || 'sem motivo registrado'}.
          </Faixa>
        )}
        <dl className="ficha ficha-linha">
          <div>
            <dt>Cliente</dt>
            <dd>{o.cliente || TRACO}</dd>
          </div>
          <div>
            <dt>Pedido do cliente</dt>
            <dd>{o.pedido_cliente || TRACO}</dd>
          </div>
          <div>
            <dt>PIV</dt>
            <dd className="mono">{o.piv || TRACO}</dd>
          </div>
          <div>
            <dt>Destinatário</dt>
            <dd>{o.destinatario || TRACO}</dd>
          </div>
          <div>
            <dt>NF de saída</dt>
            <dd className="mono">{o.nf_saida || TRACO}</dd>
          </div>
        </dl>
      </section>

      <section className="cartao" aria-labelledby="of-det-itens">
        <h2 id="of-det-itens">Itens da ordem ({inteiro(o.itens.length)})</h2>
        <div className="tabela-rolagem">
          <table className="tabela">
            <caption className="so-leitor">Itens da ordem de faturamento</caption>
            <thead>
              <tr>
                <th scope="col">OP</th>
                <th scope="col">Tipo</th>
                <th scope="col">Nº do lote</th>
                <th scope="col">CODITEM</th>
                <th scope="col">Descrição</th>
                <th scope="col" className="num">Qtd lote</th>
                <th scope="col" className="num">Qtd liberada</th>
                <th scope="col" className="num">Volumes</th>
                <th scope="col" className="num">Peso líq.</th>
                <th scope="col" className="num">Peso bruto</th>
              </tr>
            </thead>
            <tbody>
              {o.itens.map((i) => (
                <tr key={i.lote_id}>
                  <td>
                    <Link to={`/lotes/${i.lote_id}`}>{i.op}</Link>
                  </td>
                  <td>
                    <SeloTipo tipo={i.tipo} />
                  </td>
                  <td className="mono">
                    <strong>{i.lote_com_qtd}</strong>
                  </td>
                  <td className="mono">{i.coditem || TRACO}</td>
                  <td className="sub-linha">{i.descricao || TRACO}</td>
                  <td className="num">{inteiro(i.qtd)}</td>
                  <td className="num">
                    <strong>{inteiro(i.qtd_faturada)}</strong>
                  </td>
                  <td className="num">
                    <strong>{inteiro(i.volumes)}</strong>
                  </td>
                  <td className="num">{pesoBr(i.peso_liq)} kg</td>
                  <td className="num">{pesoBr(i.peso_bruto)} kg</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="env-total">
                <th scope="row" colSpan={5}>
                  TOTAIS
                </th>
                <td className="num">{inteiro(o.totais.qtd)}</td>
                <td className="num">{inteiro(o.totais.qtd_faturada)}</td>
                <td className="num">{inteiro(o.totais.volumes)}</td>
                <td className="num">{pesoBr(o.totais.peso_liq)} kg</td>
                <td className="num">{pesoBr(o.totais.peso_bruto)} kg</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      {o.observacoes && (
        <section className="cartao" aria-labelledby="of-det-obs">
          <h2 id="of-det-obs">Observações</h2>
          <p className="env-texto-livre">{o.observacoes}</p>
        </section>
      )}

      <section className="cartao" aria-labelledby="of-det-acoes">
        <h2 id="of-det-acoes">Ações</h2>
        <div className="acoes">
          <button type="button" className="botao" onClick={() => enviarPorEmail(o)}>
            Enviar por e-mail
          </button>
          {pode('emitida') && (
            <button type="button" className="botao botao-primario" onClick={() => setAcao('emitir')}>
              Emitir OF
            </button>
          )}
          {pode('faturada') && (
            <button
              type="button"
              className="botao botao-primario"
              onClick={() => {
                setNf(o.nf_saida);
                setAcao('faturar');
              }}
            >
              Marcar como faturada
            </button>
          )}
          {pode('rascunho') && (
            <button type="button" className="botao" onClick={() => setAcao('rascunho')}>
              Voltar a rascunho
            </button>
          )}
          {pode('cancelada') && (
            <button type="button" className="botao botao-perigo-contorno" onClick={() => setAcao('cancelar')}>
              Cancelar OF
            </button>
          )}
          <Link className="botao botao-fantasma" to="/faturamento">
            ← Voltar
          </Link>
        </div>
        <p className="dica">
          “Enviar por e-mail” abre o PDF numa aba (para você salvar e anexar) e prepara um rascunho no seu programa de e-mail. O e-mail
          do navegador não consegue anexar o arquivo sozinho: anexe o PDF baixado antes de enviar.
        </p>
      </section>

      {acao === 'emitir' && (
        <Confirmacao
          titulo={`Emitir a OF ${o.numero}`}
          rotuloConfirmar="Emitir OF"
          aoFechar={fechar}
          aoConfirmar={() => void mudarStatus('emitida', `OF ${o.numero} emitida.`)}
          enviando={gravando}
        >
          <p>A OF emitida sinaliza para a Expedição que pode preparar a saída. O sistema confere de novo se os lotes continuam prontos.</p>
          {erroAcao && <p className="erro-formulario">{erroAcao}</p>}
        </Confirmacao>
      )}
      {acao === 'rascunho' && (
        <Confirmacao
          titulo={`Voltar a OF ${o.numero} para rascunho`}
          rotuloConfirmar="Voltar a rascunho"
          aoFechar={fechar}
          aoConfirmar={() => void mudarStatus('rascunho', `OF ${o.numero} voltou a rascunho.`)}
          enviando={gravando}
        >
          <p>A Expedição deixa de ver a OF como liberada até ela ser emitida de novo.</p>
          {erroAcao && <p className="erro-formulario">{erroAcao}</p>}
        </Confirmacao>
      )}
      {acao === 'faturar' && (
        <ModalFormulario
          titulo={`Marcar a OF ${o.numero} como faturada`}
          aoFechar={fechar}
          aoEnviar={() => void mudarStatus('faturada', `OF ${o.numero} marcada como faturada.`, { nf_saida: nf })}
          enviando={gravando}
          erro={erroAcao}
          rotuloEnviar="Marcar como faturada"
        >
          <p>
            Depois de faturada, a OF fica <strong>travada</strong>: não dá mais para editar, voltar ou cancelar.
          </p>
          <Campo rotulo="NF de saída" para="of-nf-faturar" dica="Confira o número da nota fiscal que saiu.">
            <input id="of-nf-faturar" type="text" maxLength={40} value={nf} onChange={(e) => setNf(e.target.value)} />
          </Campo>
        </ModalFormulario>
      )}
      {acao === 'cancelar' && (
        <ModalMotivo
          titulo={`Cancelar a OF ${o.numero}`}
          rotuloConfirmar="Cancelar OF"
          perigo
          aoFechar={fechar}
          aoConfirmar={async (motivo) => {
            await api(`/faturamento/${o.id}/status`, { metodo: 'POST', corpo: { status: 'cancelada', motivo } });
            avisos.sucesso(`OF ${o.numero} cancelada.`);
            fechar();
            of.recarregar();
          }}
        >
          <p>A OF sai da lista em aberto, mas continua guardada (nada é apagado). Os lotes não mudam.</p>
        </ModalMotivo>
      )}
    </>
  );
}
