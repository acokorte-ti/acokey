import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api, consulta, foiCancelada, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { contemTermos, inteiro } from '../../lib/formato';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useAtrasado, useCarga } from '../../lib/useCarga';
import { decimalDe, inteiroDe, pesoBr, textoDoPeso } from '../envios/comum';
import type { DadosLoteOF, LoteParaFaturar, OFDetalhe, OFEntrada, OpcoesOF } from './tipos';

interface AvisoPiv {
  tipo: 'ok' | 'erro';
  texto: string;
}

function dadosIniciais(lote: LoteParaFaturar): DadosLoteOF {
  return { qtd_faturada: String(lote.qtd || ''), volumes: '', peso_liq: '', peso_bruto: '', numero: lote.lote_completo };
}

export function FormularioOF() {
  const { id } = useParams();
  const ofId = id ? Number(id) : null;
  const editando = ofId !== null;
  const navegar = useNavigate();
  const avisos = useAvisos();

  const opcoes = useCarga<OpcoesOF>((sinal) => api('/faturamento/opcoes', { sinal }), []);
  const of = useCarga<OFDetalhe | null>((sinal) => (ofId ? api(`/faturamento/${ofId}`, { sinal }) : Promise.resolve(null)), [ofId]);
  const lotes = useCarga<{ lotes: LoteParaFaturar[] }>((sinal) => api(`/faturamento/lotes-disponiveis${consulta({ of_id: ofId })}`, { sinal }), [ofId]);

  const [dataEmissao, setDataEmissao] = useState('');
  const [cliente, setCliente] = useState('');
  const [pedido, setPedido] = useState('');
  const [piv, setPiv] = useState('');
  const [nf, setNf] = useState('');
  const [destinatario, setDestinatario] = useState('');
  const [observacoes, setObservacoes] = useState('');
  const [marcados, setMarcados] = useState<Set<number>>(new Set());
  const [dados, setDados] = useState<Record<number, DadosLoteOF>>({});
  const [busca, setBusca] = useState('');
  const [pivBusca, setPivBusca] = useState<string | null>(null);
  const [avisoPiv, setAvisoPiv] = useState<AvisoPiv | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const iniciado = useRef(false);

  useEffect(() => {
    if (iniciado.current || !opcoes.dados || !lotes.dados || (editando && !of.dados)) return;
    iniciado.current = true;
    if (!of.dados) {
      setDataEmissao(opcoes.dados.hoje);
      return;
    }
    const o = of.dados;
    setDataEmissao(o.data_emissao ?? opcoes.dados.hoje);
    setCliente(o.cliente);
    setPedido(o.pedido_cliente);
    setPiv(o.piv);
    setNf(o.nf_saida);
    setDestinatario(o.destinatario);
    setObservacoes(o.observacoes);
    setMarcados(new Set(o.itens.map((i) => i.lote_id)));
    const porId = new Map(lotes.dados.lotes.map((l) => [l.id, l]));
    setDados(
      Object.fromEntries(
        o.itens.map((i) => [
          i.lote_id,
          {
            qtd_faturada: String(i.qtd_faturada),
            volumes: i.volumes ? String(i.volumes) : '',
            peso_liq: textoDoPeso(i.peso_liq),
            peso_bruto: textoDoPeso(i.peso_bruto),
            numero: porId.get(i.lote_id)?.lote_completo ?? i.lote_completo,
          },
        ]),
      ),
    );
  }, [opcoes.dados, lotes.dados, of.dados, editando]);

  // Ao digitar o PIV, procura o cliente no cadastro de OPs (só quando a pessoa mexe no campo)
  const pivAtrasado = useAtrasado(pivBusca, 400);
  useEffect(() => {
    if (pivAtrasado === null) return;
    const valor = pivAtrasado.trim();
    if (!valor) {
      setAvisoPiv(null);
      return;
    }
    const controle = new AbortController();
    api<{ cliente: string }>(`/faturamento/cliente-por-piv${consulta({ piv: valor })}`, { sinal: controle.signal }).then(
      (r) => {
        if (r.cliente) {
          setCliente(r.cliente);
          setAvisoPiv({ tipo: 'ok', texto: 'Cliente preenchido automaticamente a partir do PIV.' });
        } else {
          setAvisoPiv({ tipo: 'erro', texto: 'PIV não encontrado no cadastro de OPs: preencha o cliente à mão.' });
        }
      },
      (falha: unknown) => {
        if (!foiCancelada(falha)) setAvisoPiv({ tipo: 'erro', texto: mensagemDeErro(falha) });
      },
    );
    return () => controle.abort();
  }, [pivAtrasado]);

  const listaLotes = useMemo(() => lotes.dados?.lotes ?? [], [lotes.dados]);
  const selecionados = useMemo(() => listaLotes.filter((l) => marcados.has(l.id)), [listaLotes, marcados]);
  const visiveis = useMemo(
    () => listaLotes.filter((l) => contemTermos(`${l.op} ${l.numero} ${l.lote_completo} ${l.tipo} ${l.cliente} ${l.coditem} ${l.piv}`, busca)),
    [listaLotes, busca],
  );
  const bloqueadosMarcados = selecionados.filter((l) => !l.pronto);

  function marcar(lote: LoteParaFaturar, marcado: boolean) {
    setMarcados((atual) => {
      const novo = new Set(atual);
      if (marcado) novo.add(lote.id);
      else novo.delete(lote.id);
      return novo;
    });
    if (!marcado) return;
    if (!dados[lote.id]) setDados((d) => ({ ...d, [lote.id]: dadosIniciais(lote) }));
    // Sugere o PIV (e o pedido do cliente) do lote marcado, sem apagar o que já foi digitado
    if (!piv.trim() && lote.piv) {
      setPiv(lote.piv);
      setPivBusca(lote.piv);
    }
    if (!pedido.trim() && lote.pedido_cliente) setPedido(lote.pedido_cliente);
  }

  function mudar(loteId: number, campo: keyof DadosLoteOF, valor: string) {
    setDados((d) => ({ ...d, [loteId]: { ...(d[loteId] ?? { qtd_faturada: '', volumes: '', peso_liq: '', peso_bruto: '', numero: '' }), [campo]: valor } }));
  }

  const totais = useMemo(() => {
    const t = { qtd: 0, liberada: 0, volumes: 0, liq: 0, bruto: 0 };
    for (const lote of selecionados) {
      const d = dados[lote.id];
      t.qtd += lote.qtd;
      t.liberada += !d || d.qtd_faturada.trim() === '' ? lote.qtd : inteiroDe(d.qtd_faturada);
      t.volumes += inteiroDe(d?.volumes);
      t.liq += decimalDe(d?.peso_liq);
      t.bruto += decimalDe(d?.peso_bruto);
    }
    return t;
  }, [selecionados, dados]);

  async function gravar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    if (!selecionados.length) return setErro('Selecione ao menos um lote pronto para faturar.');
    if (bloqueadosMarcados.length) return setErro('Tire da OF os lotes com pendência (em vermelho) antes de salvar.');
    setErro(null);
    setEnviando(true);
    const corpo: OFEntrada = {
      data_emissao: dataEmissao || null,
      cliente,
      pedido_cliente: pedido,
      piv,
      nf_saida: nf,
      destinatario,
      observacoes,
      itens: selecionados.map((lote) => {
        const d = dados[lote.id] ?? dadosIniciais(lote);
        const numero = d.numero.trim();
        return {
          lote_id: lote.id,
          qtd_faturada: d.qtd_faturada.trim() === '' ? null : inteiroDe(d.qtd_faturada),
          volumes: inteiroDe(d.volumes),
          peso_liq: d.peso_liq.trim(),
          peso_bruto: d.peso_bruto.trim(),
          // Só corrige o nº do lote se a pessoa mudou o que o campo mostrava
          numero_corrigido: numero && numero !== lote.lote_completo && numero !== lote.numero ? numero : null,
        };
      }),
    };
    try {
      const r = editando
        ? await api<{ id: number; numero: string }>(`/faturamento/${ofId}`, { metodo: 'PUT', corpo })
        : await api<{ id: number; numero: string }>('/faturamento', { metodo: 'POST', corpo });
      avisos.sucesso(editando ? `OF ${r.numero} atualizada.` : `OF ${r.numero} criada em rascunho com ${selecionados.length} lote(s).`);
      navegar(`/faturamento/${r.id}`);
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setEnviando(false);
    }
  }

  const titulo = editando ? `Editar OF ${of.dados?.numero ?? ''}` : 'Nova ordem de faturamento';
  const falha = opcoes.erro || of.erro || lotes.erro;
  if (falha) {
    return (
      <>
        <Cabecalho titulo={titulo} />
        <ErroCarga
          mensagem={falha}
          aoTentar={() => {
            opcoes.recarregar();
            of.recarregar();
            lotes.recarregar();
          }}
        />
      </>
    );
  }
  if (!opcoes.dados || !lotes.dados || (editando && !of.dados)) {
    return (
      <>
        <Cabecalho titulo={titulo} />
        <Carregando />
      </>
    );
  }
  if (of.dados && !of.dados.pode_editar) {
    return (
      <>
        <Cabecalho titulo={titulo} />
        <Faixa tipo="erro">
          Esta OF está {of.dados.status === 'faturada' ? 'faturada (travada)' : 'cancelada'} e não pode mais ser alterada.
        </Faixa>
        <Link to={`/faturamento/${of.dados.id}`}>Voltar para a OF</Link>
      </>
    );
  }

  const voltar = editando ? `/faturamento/${ofId}` : '/faturamento';
  return (
    <>
      <nav className="env-trilha" aria-label="Você está em">
        <Link to="/faturamento">Ordens de faturamento</Link> ›{' '}
        {editando ? (
          <>
            <Link to={voltar}>{of.dados?.numero}</Link> › <strong>Editar</strong>
          </>
        ) : (
          <strong>Nova OF</strong>
        )}
      </nav>
      <Cabecalho
        titulo={titulo}
        apoio="Monte a OF com os lotes prontos (etapas aprovadas, sem NC aberta). Os bloqueados aparecem em vermelho, com o motivo."
      />
      <form className="pilha" onSubmit={(e) => void gravar(e)} onKeyDown={enterVaiParaProximo} noValidate>
        <section className="cartao" aria-labelledby="of-ident">
          <h2 id="of-ident">Identificação</h2>
          <div className="form-grade">
            <Campo rotulo="Número" para="of-numero" dica={editando ? undefined : 'Previsto: o número é reservado ao gravar.'}>
              <div id="of-numero" className="automatico mono">
                {editando ? of.dados?.numero : opcoes.dados.numero_previsto}
              </div>
            </Campo>
            <Campo rotulo="Data de emissão" para="of-emissao" obrigatorio>
              <input id="of-emissao" type="date" value={dataEmissao} onChange={(e) => setDataEmissao(e.target.value)} required />
            </Campo>
            <Campo rotulo="Cliente" para="of-cliente">
              <input
                id="of-cliente"
                type="text"
                maxLength={160}
                value={cliente}
                placeholder={opcoes.dados.cliente_exemplo ? `Ex.: ${opcoes.dados.cliente_exemplo}` : 'Nome do cliente'}
                onChange={(e) => setCliente(e.target.value)}
              />
            </Campo>
            <Campo rotulo="Pedido do cliente" para="of-pedido">
              <input id="of-pedido" type="text" maxLength={60} placeholder="PO" value={pedido} onChange={(e) => setPedido(e.target.value)} />
            </Campo>
            <Campo rotulo="PIV" para="of-piv" dica="Pedido do cadastro de OPs: ao digitar, o cliente é preenchido sozinho.">
              <input
                id="of-piv"
                type="text"
                maxLength={40}
                value={piv}
                onChange={(e) => {
                  setPiv(e.target.value);
                  setPivBusca(e.target.value);
                }}
              />
            </Campo>
            <Campo rotulo="NF de saída (se já tiver)" para="of-nf">
              <input id="of-nf" type="text" maxLength={40} value={nf} onChange={(e) => setNf(e.target.value)} />
            </Campo>
            <Campo rotulo="Destinatário (nome/contato)" para="of-destinatario" classe="col-2" dica="Se tiver um e-mail aqui, ele vai no “Enviar por e-mail”.">
              <input id="of-destinatario" type="text" maxLength={300} value={destinatario} onChange={(e) => setDestinatario(e.target.value)} />
            </Campo>
          </div>
          {avisoPiv && (
            <p className={avisoPiv.tipo === 'ok' ? 'fat-piv-ok' : 'texto-alerta'} role="status">
              {avisoPiv.tipo === 'ok' ? '✓ ' : '⚠ '}
              {avisoPiv.texto}
            </p>
          )}
        </section>

        <section className="cartao" aria-labelledby="of-lotes">
          <div className="cartao-topo">
            <h2 id="of-lotes">Lotes nesta OF</h2>
            <span className="sub-linha">
              {inteiro(selecionados.length)} {selecionados.length === 1 ? 'marcado' : 'marcados'}
            </span>
          </div>
          <p className="dica">Só marque lotes em VERDE (prontos). Os em VERMELHO têm pendências: resolva-as antes.</p>
          <div className="campo campo-em-linha">
            <label htmlFor="of-busca-lotes">Buscar lote</label>
            <input
              id="of-busca-lotes"
              type="search"
              placeholder="OP, lote, tipo, cliente, código ou PIV"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>
          <div className="env-lotes" role="group" aria-label="Lotes">
            {visiveis.length === 0 && <p className="dica env-lotes-vazio">{busca ? 'Nenhum lote com essa busca.' : 'Nenhum lote cadastrado ainda.'}</p>}
            {visiveis.map((lote) => {
              const marcado = marcados.has(lote.id);
              return (
                <label
                  key={lote.id}
                  className={`env-lote ${lote.pronto ? 'fat-lote-pronto' : 'fat-lote-bloqueado'} ${marcado ? 'env-lote-marcado' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={marcado}
                    disabled={!lote.pronto && !marcado}
                    onChange={(e) => marcar(lote, e.target.checked)}
                  />
                  <span className="fat-lote-op">OP {lote.op}</span>
                  <SeloTipo tipo={lote.tipo} />
                  <span className="sub-linha">
                    Lote <strong className="mono">{lote.lote_com_qtd}</strong>
                  </span>
                  {lote.coditem && (
                    <span className="env-pilula env-pilula-cod" title="Código do item">
                      COD {lote.coditem}
                    </span>
                  )}
                  {lote.piv && <span className="env-pilula env-pilula-cod">PIV {lote.piv}</span>}
                  <span className="sub-linha">{lote.cliente}</span>
                  <span className="env-lote-qtd">{inteiro(lote.qtd)} pçs total</span>
                  {lote.motivos.length > 0 && <span className="fat-motivos">⚠ {lote.motivos.join('; ')}</span>}
                  {lote.ja_faturado && <span className="fat-outra">ℹ já em outra OF</span>}
                </label>
              );
            })}
          </div>
          {bloqueadosMarcados.length > 0 && (
            <Faixa tipo="erro">
              Estes lotes estão na OF mas agora têm pendência — tire-os para poder salvar:{' '}
              {bloqueadosMarcados.map((l) => `${l.numero} (${l.motivos.join('; ')})`).join(', ')}.
            </Faixa>
          )}
        </section>

        <section className="cartao" aria-labelledby="of-pecas">
          <h2 id="of-pecas">
            Peças por OP <span className="sub-linha">(dados de transporte)</span>
          </h2>
          <p className="dica">
            Para cada OP marcada, informe a qtd liberada, os volumes e os pesos. O total é calculado sozinho. Se o nº do lote estiver errado,
            corrija na própria linha (a correção fica registrada na auditoria).
          </p>
          {selecionados.length === 0 ? (
            <p className="env-spec-aviso">Marque lotes para ver a distribuição por OP.</p>
          ) : (
            <div className="tabela-rolagem">
              <table className="tabela env-tabela-op">
                <caption className="so-leitor">Peças por OP</caption>
                <thead>
                  <tr>
                    <th scope="col">OP</th>
                    <th scope="col">Nº do lote</th>
                    <th scope="col">CODITEM</th>
                    <th scope="col" className="num">Qtd liberada</th>
                    <th scope="col" className="num">Volumes</th>
                    <th scope="col" className="num">Peso líq. (kg)</th>
                    <th scope="col" className="num">Peso bruto (kg)</th>
                  </tr>
                </thead>
                <tbody>
                  {selecionados.map((lote) => {
                    const d = dados[lote.id] ?? dadosIniciais(lote);
                    const liberada = d.qtd_faturada.trim() === '' ? lote.qtd : inteiroDe(d.qtd_faturada);
                    const corrigido = d.numero.trim() !== '' && d.numero.trim() !== lote.lote_completo && d.numero.trim() !== lote.numero;
                    const numerico = (campo: 'qtd_faturada' | 'volumes' | 'peso_liq' | 'peso_bruto', rotulo: string, decimal = false) => (
                      <input
                        type="text"
                        inputMode={decimal ? 'decimal' : 'numeric'}
                        className="env-num"
                        aria-label={`${rotulo} da OP ${lote.op}`}
                        placeholder="0"
                        value={d[campo]}
                        onChange={(e) => mudar(lote.id, campo, decimal ? e.target.value.replace(/[^\d.,]/g, '') : e.target.value.replace(/\D/g, ''))}
                      />
                    );
                    return (
                      <tr key={lote.id}>
                        <td>
                          OP <strong>{lote.op}</strong> <span className="sub-linha">· {lote.tipo}</span>
                        </td>
                        <td>
                          <input
                            type="text"
                            maxLength={40}
                            className={`fat-numero ${corrigido ? 'fat-numero-corrigido' : ''}`}
                            aria-label={`Nº do lote da OP ${lote.op}`}
                            title="Corrija aqui se o nº do lote estiver errado"
                            value={d.numero}
                            onChange={(e) => mudar(lote.id, 'numero', e.target.value)}
                          />
                          {corrigido && <span className="fat-aviso-numero">vai corrigir o lote {lote.numero}</span>}
                        </td>
                        <td className="mono">{lote.coditem || '—'}</td>
                        <td className="num">
                          {numerico('qtd_faturada', 'Qtd liberada')}
                          {liberada > lote.qtd && <span className="fat-aviso-numero">maior que o lote ({inteiro(lote.qtd)})</span>}
                        </td>
                        <td className="num">{numerico('volumes', 'Volumes')}</td>
                        <td className="num">{numerico('peso_liq', 'Peso líquido', true)}</td>
                        <td className="num">{numerico('peso_bruto', 'Peso bruto', true)}</td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="env-total">
                    <th scope="row" colSpan={3}>
                      Total
                    </th>
                    <td className="num">{inteiro(totais.liberada)}</td>
                    <td className="num">{inteiro(totais.volumes)}</td>
                    <td className="num">{pesoBr(totais.liq)}</td>
                    <td className="num">{pesoBr(totais.bruto)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </section>

        <section className="cartao" aria-labelledby="of-titulo-obs">
          <h2 id="of-titulo-obs">Observações</h2>
          <textarea
            id="of-obs"
            aria-labelledby="of-titulo-obs"
            rows={3}
            placeholder="Ex.: embalagem especial, prazo de entrega…"
            value={observacoes}
            onChange={(e) => setObservacoes(e.target.value)}
          />
        </section>

        {erro && (
          <p className="erro-formulario" role="alert">
            {erro}
          </p>
        )}
        <div className="acoes env-rodape">
          <button type="submit" className="botao botao-primario" disabled={enviando}>
            {enviando ? 'Gravando…' : editando ? 'Salvar alterações' : 'Criar OF'}
          </button>
          <Link className="botao" to={voltar}>
            Cancelar
          </Link>
          {!editando && (
            <span className="dica">
              A OF começa como <strong>rascunho</strong>. Emita e marque como faturada depois da NF.
            </span>
          )}
        </div>
      </form>
    </>
  );
}
