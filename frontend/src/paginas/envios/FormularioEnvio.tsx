import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api, consulta, enviarArquivos, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { contemTermos, inteiro } from '../../lib/formato';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useAtrasado, useCarga } from '../../lib/useCarga';
import { decimalDe, inteiroDe, NotaNatureza, pesoBr, QuadroEspecificacao, textoDoPeso } from './comum';
import { SlotsFotos } from './SlotsFotos';
import type {
  EnvioDetalhe,
  EnvioEntrada,
  LoteDisponivel,
  OpcoesEnvio,
  PrestadorOpcao,
  PreviaEspecificacao,
  QuantidadesLote,
  RespostaGravacao,
  TipoServico,
} from './tipos';

const VAZIO: QuantidadesLote = { qt_cp_tracao: '', qt_cp_impacto: '', qt_liberar: '', volumes: '', peso_liq: '', peso_bruto: '' };
const TRACAO = new Set(['Ensaio de tração', 'Ensaio de tração + Charpy']);

/** Prestadores que atendem o serviço (sem nenhum cadastrado para ele, todos, como no antigo). */
function prestadoresDo(tipo: TipoServico | undefined, todos: PrestadorOpcao[]): PrestadorOpcao[] {
  if (!tipo || !tipo.tipos_prestador) return todos;
  const filtrados = todos.filter((p) => tipo.tipos_prestador?.includes(p.tipo_servico));
  return filtrados.length ? filtrados : todos;
}

/** Prestador que já vem escolhido: nos ensaios de tração, o laboratório do modelo .docx (parâmetro); senão, o primeiro. */
function prestadorPadrao(tipo: TipoServico | undefined, opcoes: OpcoesEnvio): string {
  const lista = prestadoresDo(tipo, opcoes.prestadores);
  const trecho = opcoes.prestador_preferido.trim().toLowerCase();
  if (tipo && TRACAO.has(tipo.valor) && trecho) {
    const preferido = lista.find((p) => p.razao_social.toLowerCase().includes(trecho));
    if (preferido) return preferido.razao_social;
  }
  return lista[0]?.razao_social ?? '';
}

function quantidadesDoItem(item: EnvioDetalhe['itens'][number]): QuantidadesLote {
  return {
    qt_cp_tracao: item.qt_cp_tracao ? String(item.qt_cp_tracao) : '',
    qt_cp_impacto: item.qt_cp_impacto ? String(item.qt_cp_impacto) : '',
    qt_liberar: String(item.qt_liberar || item.qtd || ''),
    volumes: item.volumes ? String(item.volumes) : '',
    peso_liq: textoDoPeso(item.peso_liq),
    peso_bruto: textoDoPeso(item.peso_bruto),
  };
}

export function FormularioEnvio() {
  const { id } = useParams();
  const envioId = id ? Number(id) : null;
  const editando = envioId !== null;
  const [parametros] = useSearchParams();
  const navegar = useNavigate();
  const avisos = useAvisos();

  const opcoes = useCarga<OpcoesEnvio>((sinal) => api('/envios/opcoes', { sinal }), []);
  const envio = useCarga<EnvioDetalhe | null>((sinal) => (envioId ? api(`/envios/${envioId}`, { sinal }) : Promise.resolve(null)), [envioId]);

  const [tipo, setTipo] = useState('');
  const [prestador, setPrestador] = useState('');
  const [dataEmissao, setDataEmissao] = useState('');
  const [dataEnvio, setDataEnvio] = useState('');
  const [responsavel, setResponsavel] = useState('');
  const [observacoes, setObservacoes] = useState('');
  const [marcados, setMarcados] = useState<Set<number>>(new Set());
  const [quantidades, setQuantidades] = useState<Record<number, QuantidadesLote>>({});
  const [fotos, setFotos] = useState<File[]>([]);
  const [busca, setBusca] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const iniciado = useRef(false);
  const preMarcado = useRef(false);

  // Preenche o formulário uma vez: com os padrões (novo) ou com o envio gravado (editar)
  useEffect(() => {
    if (iniciado.current || !opcoes.dados || (editando && !envio.dados)) return;
    iniciado.current = true;
    const o = opcoes.dados;
    if (envio.dados) {
      const e = envio.dados;
      setTipo(e.tipo_servico);
      setPrestador(e.prestador);
      setDataEmissao(e.data_emissao ?? o.hoje);
      setDataEnvio(e.data_envio ?? o.hoje);
      setResponsavel(e.responsavel);
      setObservacoes(e.observacoes);
      setMarcados(new Set(e.itens.map((i) => i.lote_id)));
      setQuantidades(Object.fromEntries(e.itens.map((i) => [i.lote_id, quantidadesDoItem(i)])));
      return;
    }
    const pedido = o.tipos.find((t) => t.valor === parametros.get('tipo')) ?? o.tipos[0];
    setTipo(pedido?.valor ?? '');
    setPrestador(prestadorPadrao(pedido, o));
    setDataEmissao(o.hoje);
    setDataEnvio(o.hoje);
    setResponsavel(o.usuario);
  }, [opcoes.dados, envio.dados, editando, parametros]);

  const tipoAtual = opcoes.dados?.tipos.find((t) => t.valor === tipo);
  const lotes = useCarga<{ lotes: LoteDisponivel[] }>(
    (sinal) =>
      tipo ? api(`/envios/lotes-disponiveis${consulta({ tipo_servico: tipo, envio_id: envioId })}`, { sinal }) : Promise.resolve({ lotes: [] }),
    [tipo, envioId],
  );
  const listaLotes = useMemo(() => lotes.dados?.lotes ?? [], [lotes.dados]);

  // Lote que saiu da lista (ex.: ARK ao trocar para fosfato) deixa de estar marcado
  useEffect(() => {
    if (!lotes.dados || lotes.carregando) return;
    const disponiveis = new Set(lotes.dados.lotes.map((l) => l.id));
    setMarcados((atual) => {
      const restantes = [...atual].filter((lid) => disponiveis.has(lid));
      return restantes.length === atual.size ? atual : new Set(restantes);
    });
  }, [lotes.dados, lotes.carregando]);

  // Vindo de um lote (/envios/novo?tipo=...&lote=7), ele já chega marcado
  useEffect(() => {
    if (preMarcado.current || editando || !lotes.dados?.lotes.length || lotes.carregando || !tipo || !parametros.get('lote')) return;
    preMarcado.current = true;
    const pedido = lotes.dados.lotes.find((l) => String(l.id) === parametros.get('lote'));
    if (pedido) {
      setMarcados(new Set([pedido.id]));
      setQuantidades((q) => ({ ...q, [pedido.id]: { ...VAZIO, qt_liberar: String(pedido.qtd || '') } }));
    }
  }, [lotes.dados, lotes.carregando, tipo, editando, parametros]);

  const selecionados = useMemo(() => listaLotes.filter((l) => marcados.has(l.id)), [listaLotes, marcados]);
  const visiveis = useMemo(
    () => listaLotes.filter((l) => contemTermos(`${l.op} ${l.numero} ${l.tipo} ${l.cliente} ${l.corrida} ${l.coditem}`, busca)),
    [listaLotes, busca],
  );

  // Especificação ao vivo, conforme o serviço e os lotes marcados
  const chaveSpec = useAtrasado(`${tipo}|${selecionados.map((l) => l.id).join(',')}`, 300);
  const previa = useCarga<PreviaEspecificacao | null>(
    (sinal) => {
      const [servico, ids] = chaveSpec.split('|');
      if (!servico || !ids) return Promise.resolve(null);
      return api(`/envios/especificacao${consulta({ tipo_servico: servico, lote_ids: ids })}`, { sinal });
    },
    [chaveSpec],
  );

  const prestadores = useMemo(() => {
    const lista = prestadoresDo(tipoAtual, opcoes.dados?.prestadores ?? []);
    if (prestador && !lista.some((p) => p.razao_social === prestador)) {
      return [{ razao_social: prestador, codigo: '', tipo_servico: '' }, ...lista];
    }
    return lista;
  }, [tipoAtual, opcoes.dados, prestador]);

  function trocarTipo(novo: string) {
    setTipo(novo);
    if (opcoes.dados) setPrestador(prestadorPadrao(opcoes.dados.tipos.find((t) => t.valor === novo), opcoes.dados));
  }

  function marcar(lote: LoteDisponivel, marcado: boolean) {
    setMarcados((atual) => {
      const novo = new Set(atual);
      if (marcado) novo.add(lote.id);
      else novo.delete(lote.id);
      return novo;
    });
    // Os valores digitados ficam guardados se o lote for desmarcado e marcado de novo; a qtd liberada começa com o lote todo
    if (marcado && !quantidades[lote.id]) setQuantidades((q) => ({ ...q, [lote.id]: { ...VAZIO, qt_liberar: String(lote.qtd || '') } }));
  }

  function mudarQuantidade(loteId: number, campo: keyof QuantidadesLote, valor: string) {
    setQuantidades((q) => ({ ...q, [loteId]: { ...(q[loteId] ?? VAZIO), [campo]: valor } }));
  }

  const pecas = tipoAtual?.modo_pecas ?? false;
  const totais = useMemo(() => {
    const t = { tracao: 0, impacto: 0, liberar: 0, volumes: 0, liq: 0, bruto: 0 };
    for (const lote of selecionados) {
      const q = quantidades[lote.id] ?? VAZIO;
      t.tracao += inteiroDe(q.qt_cp_tracao);
      t.impacto += inteiroDe(q.qt_cp_impacto);
      t.liberar += q.qt_liberar.trim() === '' ? lote.qtd : inteiroDe(q.qt_liberar);
      t.volumes += inteiroDe(q.volumes);
      t.liq += decimalDe(q.peso_liq);
      t.bruto += decimalDe(q.peso_bruto);
    }
    return t;
  }, [selecionados, quantidades]);

  async function gravar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    if (!prestador) return setErro('Selecione o prestador.');
    if (!dataEnvio) return setErro('Informe a data de envio.');
    if (!selecionados.length) return setErro('Marque ao menos um lote.');
    setErro(null);
    setEnviando(true);
    const corpo: EnvioEntrada = {
      tipo_servico: tipo,
      prestador,
      data_emissao: dataEmissao || null,
      data_envio: dataEnvio || null,
      responsavel: responsavel.trim(),
      observacoes,
      itens: selecionados.map((lote) => {
        const q = quantidades[lote.id] ?? VAZIO;
        return {
          lote_id: lote.id,
          qt_cp_tracao: tipoAtual?.mostrar_tracao ? inteiroDe(q.qt_cp_tracao) : 0,
          qt_cp_impacto: tipoAtual?.mostrar_charpy ? inteiroDe(q.qt_cp_impacto) : 0,
          qt_liberar: pecas ? (q.qt_liberar.trim() === '' ? lote.qtd : inteiroDe(q.qt_liberar)) : 0,
          volumes: pecas ? inteiroDe(q.volumes) : 0,
          peso_liq: pecas ? q.peso_liq.trim() : '',
          peso_bruto: pecas ? q.peso_bruto.trim() : '',
        };
      }),
    };
    let gravado: RespostaGravacao;
    try {
      gravado = editando
        ? await api<RespostaGravacao>(`/envios/${envioId}`, { metodo: 'PUT', corpo })
        : await api<RespostaGravacao>('/envios', { metodo: 'POST', corpo });
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setEnviando(false);
      return;
    }
    let textoFotos = '';
    if (fotos.length) {
      try {
        await enviarArquivos(`/envios/${gravado.id}/fotos`, { arquivos: fotos });
        textoFotos = editando ? ` (+${fotos.length} foto(s))` : ` e ${fotos.length} foto(s)`;
      } catch (falha) {
        avisos.erro(`O envio ${gravado.numero} foi gravado, mas as fotos não: ${mensagemDeErro(falha)} Tente de novo no detalhe.`);
      }
    }
    avisos.sucesso(
      editando
        ? `Envio ${gravado.numero} atualizado${textoFotos}.`
        : `Envio ${gravado.numero} registrado com ${selecionados.length} lote(s)${textoFotos}.`,
    );
    navegar(`/envios/${gravado.id}`);
  }

  const titulo = editando ? `Editar envio ${envio.dados?.numero ?? ''}` : 'Novo envio a prestador externo';
  if (opcoes.erro || envio.erro) {
    return (
      <>
        <Cabecalho titulo={titulo} />
        <ErroCarga mensagem={(opcoes.erro || envio.erro) ?? ''} aoTentar={() => (opcoes.erro ? opcoes.recarregar() : envio.recarregar())} />
      </>
    );
  }
  if (!opcoes.dados || (editando && !envio.dados) || !tipo) {
    return (
      <>
        <Cabecalho titulo={titulo} />
        <Carregando />
      </>
    );
  }
  if (envio.dados && !envio.dados.pode_editar) {
    return (
      <>
        <Cabecalho titulo={titulo} />
        <Faixa tipo="erro">Este envio foi cancelado e não pode mais ser alterado.</Faixa>
        <Link to={`/envios/${envio.dados.id}`}>Voltar para o envio</Link>
      </>
    );
  }

  const voltar = editando ? `/envios/${envioId}` : '/envios';
  return (
    <>
      <nav className="env-trilha" aria-label="Você está em">
        <Link to="/envios">Envios a prestador</Link> ›{' '}
        {editando ? (
          <>
            <Link to={voltar}>{envio.dados?.numero}</Link> › <strong>Editar</strong>
          </>
        ) : (
          <strong>Novo envio</strong>
        )}
      </nav>
      <Cabecalho
        titulo={titulo}
        apoio={
          editando
            ? 'Ajuste qualquer campo do envio. Mudar o tipo de serviço ou os tipos de peça refaz a especificação.'
            : 'Registre o lote saindo da fábrica para análise, ensaio ou revestimento externo. O retorno (laudo/certificado) será lançado depois na etapa correspondente do lote.'
        }
      />
      <form className="pilha env-form" onSubmit={(e) => void gravar(e)} onKeyDown={enterVaiParaProximo} noValidate>
        <section className="cartao" aria-labelledby="env-ident">
          <h2 id="env-ident">Identificação</h2>
          <div className="form-grade">
            <Campo rotulo="Número do envio" para="env-numero" dica={editando ? undefined : 'Previsto: o número é reservado ao gravar.'}>
              <div id="env-numero" className="automatico mono">
                {editando ? envio.dados?.numero : opcoes.dados.numero_previsto}
              </div>
            </Campo>
            <Campo rotulo="Data de emissão" para="env-emissao" obrigatorio>
              <input id="env-emissao" type="date" value={dataEmissao} onChange={(e) => setDataEmissao(e.target.value)} required />
            </Campo>
            <Campo rotulo="Data de envio" para="env-data-envio" obrigatorio>
              <input id="env-data-envio" type="date" value={dataEnvio} onChange={(e) => setDataEnvio(e.target.value)} required />
            </Campo>
            <Campo rotulo="Responsável pelo envio" para="env-responsavel" dica="Quem gravou fica registrado também (seu usuário).">
              <input id="env-responsavel" type="text" maxLength={120} value={responsavel} onChange={(e) => setResponsavel(e.target.value)} />
            </Campo>
          </div>
        </section>

        <section className="cartao" aria-labelledby="env-servico">
          <h2 id="env-servico">Serviço solicitado</h2>
          <div className="linha-campos">
            <Campo rotulo="Tipo de serviço" para="env-tipo" obrigatorio>
              <select id="env-tipo" value={tipo} onChange={(e) => trocarTipo(e.target.value)}>
                {opcoes.dados.tipos.map((t) => (
                  <option key={t.valor} value={t.valor}>
                    {t.valor}
                  </option>
                ))}
              </select>
            </Campo>
            <Campo rotulo="Prestador" para="env-prestador" obrigatorio dica="A lista mostra os prestadores do tipo de serviço escolhido.">
              <select id="env-prestador" value={prestador} onChange={(e) => setPrestador(e.target.value)}>
                {!prestador && <option value="">Selecione…</option>}
                {prestadores.map((p) => (
                  <option key={p.razao_social} value={p.razao_social}>
                    {p.razao_social}
                    {p.codigo ? ` (${p.codigo})` : ''}
                  </option>
                ))}
              </select>
            </Campo>
          </div>
          {opcoes.dados.prestadores.length === 0 && (
            <Faixa tipo="alerta">Nenhum prestador cadastrado. Peça para cadastrar em Cadastros › Prestadores.</Faixa>
          )}
          {selecionados.length === 0 ? (
            <p className="env-spec-aviso">Marque pelo menos um lote para ver a especificação aplicável.</p>
          ) : previa.dados && previa.dados.especificacao.length > 0 ? (
            <QuadroEspecificacao
              especificacao={previa.dados.especificacao}
              normaCodigo={previa.dados.norma_codigo}
              clienteCurto={opcoes.dados.cliente_curto}
            />
          ) : previa.dados ? (
            <p className="env-spec-aviso">Este tipo de serviço não tem especificação numérica dedicada (ex.: revestimento, NDT).</p>
          ) : null}
        </section>

        <section className="cartao" aria-labelledby="env-lotes">
          <div className="cartao-topo">
            <h2 id="env-lotes">Lotes incluídos neste envio</h2>
            <span className="sub-linha">
              {inteiro(selecionados.length)} {selecionados.length === 1 ? 'marcado' : 'marcados'}
            </span>
          </div>
          {tipoAtual && <NotaNatureza natureza={tipoAtual.natureza} />}
          <p className="dica">
            Marque todos os lotes que vão entrar nesta solicitação. A escolha é livre: qualquer lote ativo pode ser incluído,
            independentemente da etapa atual.
          </p>
          <div className="campo campo-em-linha">
            <label htmlFor="env-busca-lotes">Buscar lote</label>
            <input
              id="env-busca-lotes"
              type="search"
              placeholder="OP, lote, tipo, cliente, corrida ou código"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>
          {lotes.erro ? (
            <ErroCarga mensagem={lotes.erro} aoTentar={lotes.recarregar} />
          ) : !lotes.dados ? (
            <Carregando texto="Buscando lotes…" />
          ) : (
            <div className="env-lotes" role="group" aria-label="Lotes disponíveis">
              {visiveis.length === 0 && <p className="dica env-lotes-vazio">Nenhum lote ativo {busca ? 'com essa busca' : 'no momento'}.</p>}
              {visiveis.map((lote) => (
                <label key={lote.id} className={`env-lote ${marcados.has(lote.id) ? 'env-lote-marcado' : ''}`}>
                  <input type="checkbox" checked={marcados.has(lote.id)} onChange={(e) => marcar(lote, e.target.checked)} />
                  <span className="env-lote-op">OP {lote.op}</span>
                  <SeloTipo tipo={lote.tipo} />
                  <span className="sub-linha">
                    Lote <strong className="mono">{lote.numero}</strong>
                  </span>
                  {lote.coditem && (
                    <span className="env-pilula env-pilula-cod" title="Código do item">
                      COD {lote.coditem}
                    </span>
                  )}
                  <span className="env-pilula">{lote.etapa_atual}</span>
                  <span className="sub-linha">
                    {lote.cliente}
                    {lote.corrida && <> · corrida {lote.corrida}</>}
                  </span>
                  <span className="env-lote-qtd">{inteiro(lote.qtd)} pçs</span>
                </label>
              ))}
            </div>
          )}
        </section>

        <section className="cartao" aria-labelledby="env-por-op">
          <h2 id="env-por-op">{pecas ? 'Peças por OP (dados de transporte)' : 'Corpos de prova por OP'}</h2>
          <p className="dica">
            {pecas
              ? 'Para cada OP marcada, informe a qtd liberada, os volumes e os pesos. O total é calculado para fins de transporte.'
              : 'Para cada OP marcada, informe quantos CPs estão sendo enviados por ensaio. O total é calculado automaticamente.'}
          </p>
          {selecionados.length === 0 ? (
            <p className="env-spec-aviso">Marque lotes para ver a distribuição por OP.</p>
          ) : (
            <div className="tabela-rolagem">
              <table className="tabela env-tabela-op">
                <caption className="so-leitor">{pecas ? 'Peças por OP' : 'Corpos de prova por OP'}</caption>
                <thead>
                  <tr>
                    <th scope="col">OP</th>
                    {pecas ? (
                      <>
                        <th scope="col">CODITEM</th>
                        <th scope="col" className="num">Qtd liberada</th>
                        <th scope="col" className="num">Volumes</th>
                        <th scope="col" className="num">Peso líq. (kg)</th>
                        <th scope="col" className="num">Peso bruto (kg)</th>
                      </>
                    ) : (
                      <>
                        {tipoAtual?.mostrar_tracao && <th scope="col" className="num">CP Tração</th>}
                        {tipoAtual?.mostrar_charpy && <th scope="col" className="num">CP Impacto Charpy</th>}
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {selecionados.map((lote) => {
                    const q = quantidades[lote.id] ?? VAZIO;
                    const campo = (nome: keyof QuantidadesLote, rotulo: string, decimal = false) => (
                      <td className="num">
                        <input
                          type="text"
                          inputMode={decimal ? 'decimal' : 'numeric'}
                          className="env-num"
                          aria-label={`${rotulo} da OP ${lote.op}`}
                          value={q[nome]}
                          placeholder="0"
                          onChange={(e) => mudarQuantidade(lote.id, nome, decimal ? e.target.value.replace(/[^\d.,]/g, '') : e.target.value.replace(/\D/g, ''))}
                        />
                      </td>
                    );
                    return (
                      <tr key={lote.id}>
                        <td>
                          OP <strong>{lote.op}</strong> <span className="sub-linha">· {lote.tipo}</span>
                        </td>
                        {pecas ? (
                          <>
                            <td className="mono">{lote.coditem || '—'}</td>
                            {campo('qt_liberar', 'Qtd liberada')}
                            {campo('volumes', 'Volumes')}
                            {campo('peso_liq', 'Peso líquido', true)}
                            {campo('peso_bruto', 'Peso bruto', true)}
                          </>
                        ) : (
                          <>
                            {tipoAtual?.mostrar_tracao && campo('qt_cp_tracao', 'CPs de tração')}
                            {tipoAtual?.mostrar_charpy && campo('qt_cp_impacto', 'CPs de impacto Charpy')}
                          </>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="env-total">
                    <th scope="row" colSpan={pecas ? 2 : 1}>
                      {pecas ? 'Total (fins de transporte)' : 'Total'}
                    </th>
                    {pecas ? (
                      <>
                        <td className="num">{inteiro(totais.liberar)}</td>
                        <td className="num">{inteiro(totais.volumes)}</td>
                        <td className="num">{pesoBr(totais.liq)}</td>
                        <td className="num">{pesoBr(totais.bruto)}</td>
                      </>
                    ) : (
                      <>
                        {tipoAtual?.mostrar_tracao && <td className="num">{inteiro(totais.tracao)}</td>}
                        {tipoAtual?.mostrar_charpy && <td className="num">{inteiro(totais.impacto)}</td>}
                      </>
                    )}
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </section>

        <section className="cartao" aria-labelledby="env-titulo-fotos">
          <h2 id="env-titulo-fotos">
            {editando ? 'Adicionar mais fotos' : tipoAtual?.rotulo_fotos} <span className="sub-linha">opcional</span>
          </h2>
          {editando && (
            <p className="dica">
              As fotos já anexadas estão no detalhe do envio (lá também dá para remover). Aqui você anexa fotos <strong>adicionais</strong>.
            </p>
          )}
          <SlotsFotos fotos={fotos} aoMudar={setFotos} desabilitado={enviando} />
        </section>

        <section className="cartao" aria-labelledby="env-titulo-obs">
          <h2 id="env-titulo-obs">Observações</h2>
          <textarea
            id="env-obs"
            aria-labelledby="env-titulo-obs"
            rows={3}
            placeholder="Ex.: 3 CPs por lote, ensaio Charpy a -20 °C, usinagem interna já feita…"
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
            {enviando ? 'Gravando…' : editando ? 'Salvar alterações' : 'Registrar envio'}
          </button>
          <Link className="botao" to={voltar}>
            Cancelar
          </Link>
          <span className="dica">
            {editando ? (
              <>
                A situação atual (<strong>{envio.dados?.status}</strong>) não muda aqui: use o botão próprio no detalhe.
              </>
            ) : (
              <>
                O envio começa como <strong>enviado</strong>. Quando o laudo voltar, marque como <strong>retornado</strong>.
              </>
            )}
          </span>
        </div>
      </form>
    </>
  );
}
