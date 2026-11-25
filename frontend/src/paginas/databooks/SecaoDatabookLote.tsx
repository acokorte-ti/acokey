/**
 * Bloco "Databook do cliente" da página do lote (só para lote concluído e para quem tem o módulo Qualidade):
 * baixar o databook mais recente, gerar e-mail, conferir, situação de envio (Enviado-DB) e o formulário de gerar
 * (data de aprovação, quem aprova e o nome do produto da capa). Porte de TEMPLATES["lote"] do sistema antigo.
 */
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { api, consulta, enderecoApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataCurta, dataHoraLocal, inteiro, TRACO } from '../../lib/formato';
import { useSessao } from '../../lib/sessao';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useCarga } from '../../lib/useCarga';
import { ModalEnvio } from './ModalEnvio';
import type { DatabookDoLote, ResultadoGeracao } from './tipos';
import './databooks.css';

function textoOuVazio(valor: string | number, aviso: string) {
  const texto = String(valor ?? '').trim();
  return texto ? texto : <span className="automatico-vazio">{aviso}</span>;
}

// ---------------------------------------------------------------- formulário de geração

function FormularioGeracao({ dados, aoGerar }: { dados: DatabookDoLote; aoGerar: () => void }) {
  const avisos = useAvisos();
  const { usuario } = useSessao();
  const { capa, aprovadores } = dados;
  const padraoAprovador =
    aprovadores.find((a) => a.id === usuario?.id)?.id ?? (aprovadores.length === 1 ? aprovadores[0].id : undefined);
  const [dataAprovacao, setDataAprovacao] = useState('');
  const [aprovadorId, setAprovadorId] = useState<string>(padraoAprovador ? String(padraoAprovador) : '');
  const [produto, setProduto] = useState(capa.produto);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const aprovador = aprovadores.find((a) => String(a.id) === aprovadorId);
  const novaRevisao = dados.databook !== null;

  async function gerar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    if (!dataAprovacao) {
      setErro('Digite a DATA DE APROVAÇÃO antes de gerar o databook.');
      document.getElementById('db-data-aprovacao')?.focus();
      return;
    }
    if (!aprovadorId) {
      setErro('Escolha quem aprova o databook (campo "Aprovado por").');
      document.getElementById('db-aprovador')?.focus();
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const resultado = await api<ResultadoGeracao>(`/databooks/lote/${dados.lote.id}/gerar`, {
        metodo: 'POST',
        corpo: { data_aprovacao: dataAprovacao, aprovador_id: Number(aprovadorId), produto: produto.trim() },
      });
      avisos.sucesso(resultado.mensagem);
      if (resultado.alertas.length > 0) {
        avisos.info(`A montagem teve ${resultado.alertas.length} alerta(s): veja a lista no bloco do databook.`);
      }
      aoGerar();
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form className="form-coluna" onSubmit={(e) => void gerar(e)} onKeyDown={enterVaiParaProximo} noValidate>
      <div className="db-data-aprovacao">
        <div className="db-data-aprovacao-texto">
          <strong>
            <label htmlFor="db-data-aprovacao">DIGITE A DATA DE APROVAÇÃO</label>
          </strong>
          <span className="dica">
            Essa data aparece em <strong>DATA DE EMISSÃO</strong> na capa e também sob os nomes nos blocos{' '}
            <strong>Elaborado por</strong> e <strong>Aprovado por</strong>.
          </span>
        </div>
        <input
          id="db-data-aprovacao"
          type="date"
          value={dataAprovacao}
          onChange={(e) => setDataAprovacao(e.target.value)}
          required
          aria-required="true"
        />
      </div>

      <div className="form-grade">
        <Campo
          rotulo="Aprovado por"
          para="db-aprovador"
          obrigatorio
          classe="col-2"
          dica={
            aprovadores.length === 0
              ? 'Nenhum usuário pode aprovar. Peça ao administrador para marcar "pode aprovar" em Usuários.'
              : aprovador && !aprovador.tem_assinatura
                ? 'Sem assinatura digital cadastrada: na capa sai o nome escrito no lugar da assinatura.'
                : 'Quem assina a capa como aprovador (precisa poder aprovar pela Qualidade).'
          }
        >
          <select id="db-aprovador" value={aprovadorId} onChange={(e) => setAprovadorId(e.target.value)} required>
            <option value="">Escolha…</option>
            {aprovadores.map((a) => (
              <option key={a.id} value={a.id}>
                {a.nome}
                {a.cargo ? ` (${a.cargo})` : ''}
              </option>
            ))}
          </select>
        </Campo>
        <Campo
          rotulo="Elaborado por"
          para="db-elaborado"
          classe="col-2"
          dica={
            capa.elaborado_tem_assinatura
              ? 'Você, com a sua assinatura digital.'
              : 'Você. Sem assinatura digital cadastrada: na capa sai o nome escrito.'
          }
        >
          <div id="db-elaborado" className="automatico">
            {capa.elaborado_por}
            {capa.elaborado_cargo && <span className="sub-linha">· {capa.elaborado_cargo}</span>}
          </div>
        </Campo>
        <Campo
          rotulo="Produto (na capa)"
          para="db-produto"
          classe="col-4"
          dica={
            capa.produto_sugestoes.length > 1 ? (
              <span className="db-acoes">
                Sugestões:
                {capa.produto_sugestoes.map((s) => (
                  <button key={s} type="button" className="botao-link" onClick={() => setProduto(s)}>
                    {s}
                  </button>
                ))}
              </span>
            ) : (
              'Vem da descrição da OP. Pode ajustar.'
            )
          }
        >
          <input id="db-produto" type="text" maxLength={200} value={produto} onChange={(e) => setProduto(e.target.value)} />
        </Campo>
      </div>

      <div className="db-capa">
        <p className="etapa-rotulo">O que mais vai na capa (cadastro da OP e do lote)</p>
        <dl className="ficha ficha-linha">
          <div>
            <dt>Cliente</dt>
            <dd>{textoOuVazio(capa.cliente, 'não cadastrado')}</dd>
          </div>
          <div>
            <dt>Especificação / Projeto</dt>
            <dd>{textoOuVazio(capa.projeto, 'vazio no cadastro da OP')}</dd>
          </div>
          <div>
            <dt>Nº do pedido (PO)</dt>
            <dd>{textoOuVazio(capa.pedido, 'vazio no cadastro da OP')}</dd>
          </div>
          <div>
            <dt>Lote</dt>
            <dd className="mono">{capa.lote}</dd>
          </div>
          <div>
            <dt>QTD - Lote</dt>
            <dd>{inteiro(capa.qtd)}</dd>
          </div>
          <div>
            <dt>Nº do documento</dt>
            <dd className="mono">{capa.numero_documento}</dd>
          </div>
          <div>
            <dt>Revisão</dt>
            <dd>{capa.proxima_revisao}</dd>
          </div>
        </dl>
        {!capa.op_cadastrada && (
          <p className="texto-alerta" role="alert">
            A OP {dados.lote.op} não existe no cadastro de OPs, por isso o databook não pode ser gerado. Corrija a OP do lote (Editar lote)
            ou cadastre a OP em Cadastros › Ordens de produção.
          </p>
        )}
      </div>

      {erro && (
        <p className="erro-formulario" role="alert">
          {erro}
        </p>
      )}
      <div className="acoes">
        <button type="submit" className="botao botao-primario" disabled={enviando || !capa.op_cadastrada}>
          {enviando ? 'Gerando o databook…' : novaRevisao ? `Gerar nova revisão (Rev ${capa.proxima_revisao})` : 'Gerar databook'}
        </button>
        {enviando && <span className="dica">Juntando os documentos das etapas. Pode levar alguns segundos.</span>}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- bloco

function Secao({ loteId }: { loteId: number }) {
  const carga = useCarga<DatabookDoLote>((sinal) => api(`/databooks/lote/${loteId}`, { sinal }), [loteId]);
  const [marcando, setMarcando] = useState(false);
  const dados = carga.dados && carga.dados.lote.id === loteId ? carga.dados : null;

  if (carga.erro) {
    return (
      <section className="cartao" id="databook" aria-labelledby="db-titulo-lote">
        <h2 id="db-titulo-lote">Databook do cliente</h2>
        <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />
      </section>
    );
  }
  if (!dados) {
    return (
      <section className="cartao" id="databook" aria-labelledby="db-titulo-lote">
        <h2 id="db-titulo-lote">Databook do cliente</h2>
        <Carregando />
      </section>
    );
  }

  const { lote, databook, envios, pendente_envio: pendente } = dados;
  const pdf = enderecoApi(`/databooks/lote/${lote.id}/pdf`);
  const ultimoEnvio = envios[0];
  const anteriores = dados.revisoes.slice(1);

  /** O antigo abria o PDF (para salvar e anexar) e, logo depois, um rascunho de e-mail com o assunto preenchido. */
  function gerarEmail() {
    window.open(pdf, '_blank', 'noopener');
    const assunto = `DATABOOK DB-${lote.numero}`;
    const corpo = `Prezados,\r\n\r\nSegue em anexo o databook DB-${lote.numero}.\r\n\r\nAtenciosamente,`;
    window.setTimeout(() => {
      window.location.href = `mailto:?subject=${encodeURIComponent(assunto)}&body=${encodeURIComponent(corpo)}`;
    }, 600);
  }

  return (
    <section className={`cartao ${carga.carregando ? 'recarregando' : ''}`} id="databook" aria-labelledby="db-titulo-lote">
      <div className="cartao-topo">
        <h2 id="db-titulo-lote">Databook do cliente</h2>
        <Link to={`/databooks${consulta({ aba: ultimoEnvio && !pendente ? 'enviados' : '' })}`} className="botao-link">
          Ir para Databooks
        </Link>
      </div>
      <p className="dica">
        Dossiê de Qualidade do Produto: PDF com capa, índice e todos os certificados e relatórios do lote, entregue ao cliente final.
        Fotos marcadas como "só registro interno" não entram.
      </p>

      {databook ? (
        <div className="db-pronto">
          <div>
            <span className="db-pronto-titulo">Databook disponível para download</span>
            <span className="sub-linha">
              Rev {databook.revisao ?? TRACO} · gerado em {dataHoraLocal(databook.gerado_em)} · {inteiro(databook.tamanho_kb)} KB
            </span>
            <span className="db-arquivo">{databook.arquivo}</span>
          </div>
          <div className="db-acoes">
            <a className="botao botao-primario" href={pdf} target="_blank" rel="noopener">
              Baixar e visualizar databook (PDF)<span className="so-leitor"> (abre em outra aba)</span>
            </a>
            <button type="button" className="botao" onClick={gerarEmail}>
              Gerar e-mail com databook
            </button>
            <Link className="botao" to={`/databooks/conferir/${lote.id}`} title="Verifica se todas as páginas citam a OP e o lote corretos">
              Conferir databook
            </Link>
            <a className="botao-link" href={enderecoApi(`/lotes/${lote.id}/laser.csv`)}>
              Arquivo laser (CSV)
            </a>
          </div>
          <p className="dica">
            O e-mail abre no seu programa padrão (Outlook etc.) com o assunto preenchido; o PDF abre em outra aba para você salvar e
            anexar.
          </p>

          {dados.alertas.length > 0 ? (
            <Faixa tipo="alerta">
              <strong>Conferência da montagem: {dados.alertas.length} alerta(s)</strong>
              <pre className="db-alertas">{dados.alertas.join('\n')}</pre>
            </Faixa>
          ) : (
            <p className="dica">Conferência da montagem: nenhum alerta (todos os itens do checklist foram encontrados).</p>
          )}

          {ultimoEnvio && (
            <Faixa tipo="sucesso">
              <span className="db-enviado">Enviado-DB em {dataCurta(ultimoEnvio.data_envio)}</span> para{' '}
              <strong>{ultimoEnvio.destinatario || TRACO}</strong> (Rev {ultimoEnvio.revisao}
              {ultimoEnvio.lote !== lote.numero ? `, lote ${ultimoEnvio.lote}` : ''})
              {ultimoEnvio.nf_saida && <> · NF {ultimoEnvio.nf_saida}</>}
              <span className="sub-linha">
                {' '}
                · registrado por {ultimoEnvio.enviado_por || TRACO} em {dataHoraLocal(ultimoEnvio.enviado_em)}
              </span>
            </Faixa>
          )}
          {pendente ? (
            <Faixa tipo="info">
              <span>
                A <strong>Rev {pendente.revisao}</strong> ainda não foi enviada ao cliente.{' '}
              </span>
              <button type="button" className="botao botao-pequeno" onClick={() => setMarcando(true)}>
                Marcar como Enviado-DB
              </button>
            </Faixa>
          ) : (
            !ultimoEnvio && <p className="dica">Envio ao cliente: ainda não registrado.</p>
          )}

          {anteriores.length > 0 && (
            <details className="recolhivel">
              <summary>Revisões anteriores ({anteriores.length})</summary>
              <ul className="db-revisoes">
                {anteriores.map((r) => (
                  <li key={r.arquivo}>
                    <a href={enderecoApi(`/databooks/lote/${lote.id}/pdf`, { arquivo: r.arquivo })} target="_blank" rel="noopener">
                      Rev {r.revisao ?? TRACO}
                      <span className="so-leitor"> (abre em outra aba)</span>
                    </a>
                    <span className="sub-linha">
                      {dataHoraLocal(r.gerado_em)} · {inteiro(r.tamanho_kb)} KB
                    </span>
                    <Link className="botao-link" to={`/databooks/conferir/${lote.id}${consulta({ arquivo: r.arquivo })}`}>
                      Conferir
                    </Link>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      ) : (
        <Faixa tipo="info">Este lote ainda não tem databook. Preencha a data de aprovação e clique em Gerar databook.</Faixa>
      )}

      <details className="recolhivel" open={!databook}>
        <summary>
          <strong>{databook ? 'Gerar nova revisão' : 'Gerar databook'}</strong>
          <span className="sub-linha"> · preencha a data de aprovação e clique em gerar</span>
        </summary>
        <FormularioGeracao key={`${lote.id}-${dados.capa.proxima_revisao}`} dados={dados} aoGerar={carga.recarregar} />
      </details>

      {marcando && pendente && (
        <ModalEnvio
          item={pendente}
          hoje={dados.hoje}
          aoFechar={() => setMarcando(false)}
          aoConcluir={() => {
            setMarcando(false);
            carga.recarregar();
          }}
        />
      )}
    </section>
  );
}

/** Bloco que a página do lote renderiza. Só aparece em lote concluído e para quem tem o módulo Qualidade. */
export function SecaoDatabookLote({ loteId, concluido }: { loteId: number; concluido: boolean }) {
  const { pode } = useSessao();
  if (!concluido || !pode.qualidade) return null;
  return <Secao loteId={loteId} />;
}
