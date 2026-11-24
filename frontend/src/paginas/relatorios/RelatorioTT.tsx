import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, Faixa } from '../../componentes/Estados';
import { Confirmacao } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, consulta, enviarArquivos, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { pecas } from '../../lib/formato';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useCarga } from '../../lib/useCarga';
import {
  decimal,
  ErroRelatorio,
  escolhaInicial,
  numeroDigitado,
  Resumo,
  SeletorEquipamento,
  SeletorPessoa,
  SlotImagem,
} from './Comuns';
import type { LoteTT, RespostaRelatorio, TelaTT } from './tipos';

/** Valores padrão do formulário do sistema antigo (o técnico confere e corrige). */
const TEMPERA_PADRAO = {
  pre_temp: '800',
  pre_tempo: '25',
  z2_temp: '870',
  z2_tempo: '25',
  z3_temp: '870',
  z3_tempo: '25',
  resfr_pre: '-',
  resfr_z2: '-',
  resfr_z3: 'Óleo',
};
const REVENIMENTO_PADRAO = { rev1_temp: '520', rev1_tempo: '180', rev2_temp: '500', rev2_tempo: '180' };

type Tempera = typeof TEMPERA_PADRAO;
type Revenimento = typeof REVENIMENTO_PADRAO;
type Graficos = { tempera: File | null; rev1: File | null; rev2: File | null };

function LinhaLote({ lote, principal = false, aoTirar }: { lote: LoteTT; principal?: boolean; aoTirar?: () => void }) {
  return (
    <li className={`rel-lote ${principal ? 'rel-lote-principal' : ''}`}>
      <div>
        <strong>OP {lote.op}</strong> <SeloTipo tipo={lote.tipo} /> · {pecas(lote.qtd)} · Lote <span className="mono">{lote.numero}</span>
        {principal && <span className="sub-linha"> · lote principal</span>}
        <div className="sub-linha">
          {lote.cliente || '—'} · {lote.item}
        </div>
      </div>
      {aoTirar && (
        <button type="button" className="botao botao-pequeno botao-fantasma" onClick={aoTirar} aria-label={`Tirar a OP ${lote.op} do relatório`}>
          Tirar
        </button>
      )}
    </li>
  );
}

/** Verificação de dureza do técnico depois do TT: os dois valores ou nenhum, mínima ≤ máxima. */
function situacaoPos(minTexto: string, maxTexto: string, espMin: number, espMax: number) {
  const m = numeroDigitado(minTexto);
  const M = numeroDigitado(maxTexto);
  if (m === null && M === null) return { rotulo: '—', classe: '', detalhe: '', bloqueio: null as string | null };
  if (m === null || M === null) {
    const falta = m === null ? 'mínima' : 'máxima';
    return {
      rotulo: 'INCOMPLETO',
      classe: 'rel-status-alerta',
      detalhe: `preencha também a dureza ${falta}, ou apague as duas para não mostrar essa verificação`,
      bloqueio: `Informe a dureza ${falta} também, ou deixe os dois campos em branco se o técnico não fez essa verificação.`,
    };
  }
  if (m > M) {
    return {
      rotulo: 'ERRO',
      classe: 'rel-status-erro',
      detalhe: `a mínima (${decimal(m)}) não pode ser maior que a máxima (${decimal(M)})`,
      bloqueio: 'A dureza mínima não pode ser maior que a máxima. Confira os valores.',
    };
  }
  const ok = m >= espMin && M <= espMax;
  return {
    rotulo: ok ? 'APROVADO' : 'REPROVADO',
    classe: ok ? 'rel-status-ok' : 'rel-status-erro',
    detalhe: `faixa encontrada ${decimal(m)} a ${decimal(M)} HRc (especificação ${espMin}–${espMax})`,
    bloqueio: null,
  };
}

export function RelatorioTT({ loteId, cargaId }: { loteId: number | null; cargaId: number | null }) {
  const navegar = useNavigate();
  const avisos = useAvisos();
  const idLista = useId();
  const tela = useCarga<TelaTT>(
    (sinal) => api(`/relatorios/tt${consulta({ lote: loteId, carga: cargaId })}`, { sinal }),
    [loteId, cargaId],
  );
  const dados = tela.dados;

  const [extras, setExtras] = useState<LoteTT[]>([]);
  const [busca, setBusca] = useState('');
  const [fornoTempera, setFornoTempera] = useState('');
  const [fornoRevenimento, setFornoRevenimento] = useState('');
  const [tempera, setTempera] = useState<Tempera>(TEMPERA_PADRAO);
  const [revenimento, setRevenimento] = useState<Revenimento>(REVENIMENTO_PADRAO);
  const [durMin, setDurMin] = useState('');
  const [durMax, setDurMax] = useState('');
  const [graficos, setGraficos] = useState<Graficos>({ tempera: null, rev1: null, rev2: null });
  const [tecnico, setTecnico] = useState<number | ''>('');
  const [aprovador, setAprovador] = useState<number | ''>('');
  const [dataTratamento, setDataTratamento] = useState('');
  const [dataRegistro, setDataRegistro] = useState('');
  const [dataAprovacao, setDataAprovacao] = useState('');
  const [obs, setObs] = useState('');
  const [confirmando, setConfirmando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (!dados) return;
    const existe = (lista: { codigo: string }[], codigo: string) => lista.some((e) => e.codigo === codigo);
    // Padrão (da carga ou dos parâmetros); sem padrão no cadastro, o primeiro forno da lista, como no antigo
    setFornoTempera(
      existe(dados.fornos_tempera, dados.forno_tempera_padrao) || (dados.carga && dados.forno_tempera_padrao)
        ? dados.forno_tempera_padrao
        : (dados.fornos_tempera[0]?.codigo ?? ''),
    );
    setFornoRevenimento(
      existe(dados.fornos_revenimento, dados.forno_revenimento_padrao) || (dados.carga && dados.forno_revenimento_padrao)
        ? dados.forno_revenimento_padrao
        : (dados.fornos_revenimento[0]?.codigo ?? ''),
    );
    setTecnico(escolhaInicial(dados.tecnicos, dados.usuario_id));
    setAprovador(escolhaInicial(dados.aprovadores, dados.usuario_id));
    setDataTratamento(dados.hoje);
    setDataRegistro(dados.hoje);
    setDataAprovacao(dados.hoje);
    setExtras([]);
    setErro(null);
  }, [dados]);

  const pos = useMemo(
    () => situacaoPos(durMin, durMax, dados?.info.esp_min ?? 0, dados?.info.esp_max ?? 0),
    [durMin, durMax, dados],
  );

  if (tela.erro) {
    return (
      <>
        <Cabecalho titulo="Relatório de Tratamento Térmico" />
        <ErroRelatorio mensagem={tela.erro} loteId={loteId} />
      </>
    );
  }
  if (!dados) return <Carregando />;
  const { lote, info, carga } = dados;
  const principal: LoteTT = { ...lote, ...dados.principal };
  const listaLotes: LoteTT[] = carga ? dados.lotes_carga : [principal, ...extras];
  const disponiveis = dados.outros_lotes.filter((o) => !extras.some((e) => e.id === o.id));

  function incluir(texto: string) {
    const alvo = texto.trim().toLowerCase();
    if (!alvo) return false;
    const porNumero = disponiveis.find((o) => o.numero.toLowerCase() === alvo);
    const porOp = disponiveis.filter((o) => o.op.toLowerCase() === alvo);
    const achado = porNumero ?? (porOp.length === 1 ? porOp[0] : undefined);
    if (!achado) return false;
    setExtras((atual) => [...atual, achado]);
    setBusca('');
    return true;
  }

  function validar(): string | null {
    if (pos.bloqueio) return pos.bloqueio;
    if (dados && dados.fornos_tempera.length > 0 && !fornoTempera) return 'Escolha o forno de têmpera.';
    if (dados && dados.fornos_revenimento.length > 0 && !fornoRevenimento) return 'Escolha o forno de revenimento.';
    if (tecnico === '' || aprovador === '') return 'Escolha quem executou e quem aprova o relatório.';
    return null;
  }

  function aoEnviar(evento: FormEvent) {
    evento.preventDefault();
    const problema = validar();
    setErro(problema);
    if (problema) return;
    if (carga?.status === 'concluida') setConfirmando(true);
    else void gravar();
  }

  async function gravar() {
    if (enviando) return;
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await enviarArquivos<RespostaRelatorio>('/relatorios/tt', {
        lote_id: lote.id,
        carga_id: carga?.id ?? '',
        lotes_extras: carga ? '' : extras.map((e) => e.id).join(','),
        forno_tempera_codigo: fornoTempera,
        forno_revenimento_codigo: fornoRevenimento,
        ...tempera,
        ...revenimento,
        dur_pos_min: durMin,
        dur_pos_max: durMax,
        tecnico: tecnico === '' ? '' : tecnico,
        aprovado_por: aprovador === '' ? '' : aprovador,
        data_tratamento: dataTratamento,
        data_registro: dataRegistro,
        data_aprovacao: dataAprovacao,
        obs,
        grafico_tempera: graficos.tempera,
        grafico_rev1: graficos.rev1,
        grafico_rev2: graficos.rev2,
      });
      avisos.sucesso(resposta.mensagem);
      navegar(`/lotes/${lote.id}`);
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setConfirmando(false);
      setEnviando(false);
    }
  }

  const celula = <K extends keyof Tempera>(chave: K, rotulo: string) => (
    <input type="text" aria-label={rotulo} value={tempera[chave]} maxLength={20} onChange={(e) => setTempera({ ...tempera, [chave]: e.target.value })} />
  );
  const celulaRev = <K extends keyof Revenimento>(chave: K, rotulo: string) => (
    <input
      type="text"
      aria-label={rotulo}
      value={revenimento[chave]}
      maxLength={20}
      onChange={(e) => setRevenimento({ ...revenimento, [chave]: e.target.value })}
    />
  );

  return (
    <>
      <Cabecalho
        titulo="Relatório de Tratamento Térmico"
        apoio={
          <>
            <Link to={`/lotes/${lote.id}`}>Lote {lote.numero}</Link> · Gera o PDF de têmpera e revenimento. Pode incluir mais de um lote
            no mesmo tratamento (o forno tratou os lotes juntos).
          </>
        }
      />
      <div className="pilha rel-pagina">
        {carga && (
          <Faixa tipo="info">
            Relatório da <Link to={`/cargas-tt/${carga.id}`}>carga {carga.numero}</Link>: fornos e lotes vêm da carga. Ao salvar, o PDF é
            anexado em <strong>todos</strong> os lotes da carga, a etapa avança em cada um e a carga fica concluída.
          </Faixa>
        )}
        {carga?.status === 'concluida' && (
          <Faixa tipo="alerta">
            Esta carga já está concluída. Gerar de novo cria um novo anexo e repete a movimentação nos lotes da carga.
          </Faixa>
        )}
        {!carga && dados.carga_do_lote && (
          <Faixa tipo="info">
            Este lote está na <Link to={`/cargas-tt/${dados.carga_do_lote.id}`}>carga {dados.carga_do_lote.numero}</Link>.{' '}
            <Link to={`/relatorios/tt?carga=${dados.carga_do_lote.id}`}>Gerar o relatório pela carga</Link> anexa o PDF em todos os lotes
            dela.
          </Faixa>
        )}

        <Resumo
          itens={[
            ['Material', info.material],
            ['Fornecedor', info.fornecedor],
            ['Esp. dureza', <strong>{info.esp_dureza}</strong>],
            ['Pedido do cliente (PO)', info.po],
          ]}
        />

        <form className="pilha" onSubmit={aoEnviar} onKeyDown={enterVaiParaProximo} noValidate>
          <section className="cartao" aria-labelledby="titulo-lotes">
            <h2 id="titulo-lotes">Lotes incluídos neste tratamento</h2>
            {carga ? (
              <p className="dica">Para mudar os lotes, edite a carga.</p>
            ) : (
              <p className="dica">
                O lote atual já está na lista. Busque pela OP (ou pelo número do lote) de outro lote que entrou junto no mesmo forno.
              </p>
            )}
            <ul className="rel-lotes">
              {listaLotes.map((l) => (
                <LinhaLote
                  key={l.id}
                  lote={l}
                  principal={l.id === lote.id}
                  aoTirar={!carga && l.id !== lote.id ? () => setExtras((atual) => atual.filter((e) => e.id !== l.id)) : undefined}
                />
              ))}
            </ul>
            {!carga &&
              (dados.outros_lotes.length > 0 ? (
                <Campo rotulo="Incluir outra OP no mesmo tratamento" para="tt-busca" dica="Digite a OP e escolha na lista.">
                  <div className="campo-com-botao">
                    <input
                      id="tt-busca"
                      type="search"
                      list={idLista}
                      autoComplete="off"
                      placeholder="Digite a OP…"
                      value={busca}
                      onChange={(e) => {
                        setBusca(e.target.value);
                        incluir(e.target.value);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          e.stopPropagation();
                          if (!incluir(busca) && busca.trim()) setErro(`Nenhum lote disponível com a OP ou o número "${busca.trim()}".`);
                        }
                      }}
                    />
                    <button type="button" className="botao" onClick={() => incluir(busca)} disabled={!busca.trim()}>
                      Incluir
                    </button>
                  </div>
                  <datalist id={idLista}>
                    {disponiveis.map((o) => (
                      <option key={o.id} value={o.numero}>
                        {`OP ${o.op} · ${o.tipo} · ${o.qtd} peças · ${o.cliente} · ${o.item}${o.aguardando_tt ? '' : ' · já passou do TT'}`}
                      </option>
                    ))}
                  </datalist>
                </Campo>
              ) : (
                <p className="dica">Nenhum outro lote cadastrado para incluir no mesmo tratamento.</p>
              ))}
          </section>

          <section className="cartao" aria-labelledby="titulo-tempera">
            <h2 id="titulo-tempera">Têmpera</h2>
            <SeletorEquipamento
              id="tt-forno-tempera"
              rotulo="Forno de têmpera"
              lista={dados.fornos_tempera}
              valor={fornoTempera}
              aoMudar={setFornoTempera}
              obrigatorio={dados.fornos_tempera.length > 0}
              vazio="Nenhum forno de têmpera no cadastro de equipamentos."
            />
            <div className="tabela-rolagem">
              <table className="tabela rel-tabela-tt">
                <thead>
                  <tr>
                    <th scope="col">
                      <span className="so-leitor">Grandeza</span>
                    </th>
                    <th scope="col">Pré aquecimento</th>
                    <th scope="col">Austenitização Z2</th>
                    <th scope="col">Austenitização Z3</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">Temperatura (°C)</th>
                    <td>{celula('pre_temp', 'Temperatura do pré aquecimento')}</td>
                    <td>{celula('z2_temp', 'Temperatura da austenitização Z2')}</td>
                    <td>{celula('z3_temp', 'Temperatura da austenitização Z3')}</td>
                  </tr>
                  <tr>
                    <th scope="row">Tempo (min)</th>
                    <td>{celula('pre_tempo', 'Tempo do pré aquecimento')}</td>
                    <td>{celula('z2_tempo', 'Tempo da austenitização Z2')}</td>
                    <td>{celula('z3_tempo', 'Tempo da austenitização Z3')}</td>
                  </tr>
                  <tr>
                    <th scope="row">Resfriamento</th>
                    <td>{celula('resfr_pre', 'Resfriamento do pré aquecimento')}</td>
                    <td>{celula('resfr_z2', 'Resfriamento da austenitização Z2')}</td>
                    <td>{celula('resfr_z3', 'Resfriamento da austenitização Z3')}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section className="cartao" aria-labelledby="titulo-revenimento">
            <h2 id="titulo-revenimento">Revenimento</h2>
            <SeletorEquipamento
              id="tt-forno-revenimento"
              rotulo="Forno de revenimento"
              lista={dados.fornos_revenimento}
              valor={fornoRevenimento}
              aoMudar={setFornoRevenimento}
              obrigatorio={dados.fornos_revenimento.length > 0}
              vazio="Nenhum forno de revenimento no cadastro de equipamentos."
            />
            <div className="tabela-rolagem">
              <table className="tabela rel-tabela-tt">
                <thead>
                  <tr>
                    <th scope="col">
                      <span className="so-leitor">Revenimento</span>
                    </th>
                    <th scope="col">Temperatura (°C)</th>
                    <th scope="col">Tempo (min)</th>
                    <th scope="col">Dureza esperada</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">1º revenimento</th>
                    <td>{celulaRev('rev1_temp', 'Temperatura do 1º revenimento')}</td>
                    <td>{celulaRev('rev1_tempo', 'Tempo do 1º revenimento')}</td>
                    <td className="automatico">{info.esp_dureza}</td>
                  </tr>
                  <tr>
                    <th scope="row">
                      2º revenimento <span className="sub-linha">(opcional)</span>
                    </th>
                    <td>{celulaRev('rev2_temp', 'Temperatura do 2º revenimento')}</td>
                    <td>{celulaRev('rev2_tempo', 'Tempo do 2º revenimento')}</td>
                    <td className="automatico">{info.esp_dureza}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="dica">Os valores do 2º revenimento já vêm preenchidos: apague os dois campos se o lote não passou por ele.</p>
          </section>

          <section className="cartao" aria-labelledby="titulo-pos">
            <h2 id="titulo-pos">Dureza após o tratamento térmico</h2>
            <p className="dica">
              Verificação do técnico, não substitui o RIP-35. Registre só a <strong>menor</strong> e a <strong>maior</strong> dureza
              encontrada no lote; o status é comparado com a especificação ({info.esp_dureza}). Deixe os dois em branco se não houve
              verificação (o bloco não aparece no PDF).
            </p>
            <div className="linha-campos">
              <Campo rotulo="Dureza mínima encontrada (HRc)" para="tt-dur-min">
                <input
                  id="tt-dur-min"
                  type="text"
                  inputMode="decimal"
                  className="rel-numero-grande"
                  placeholder="Ex.: 35,0"
                  value={durMin}
                  maxLength={8}
                  onChange={(e) => setDurMin(e.target.value)}
                />
              </Campo>
              <Campo rotulo="Dureza máxima encontrada (HRc)" para="tt-dur-max">
                <input
                  id="tt-dur-max"
                  type="text"
                  inputMode="decimal"
                  className="rel-numero-grande"
                  placeholder="Ex.: 37,0"
                  value={durMax}
                  maxLength={8}
                  onChange={(e) => setDurMax(e.target.value)}
                />
              </Campo>
            </div>
            <div className={`rel-status ${pos.classe}`} role="status" aria-live="polite">
              <span>Status da verificação:</span>
              <strong>{pos.rotulo}</strong>
              {pos.detalhe && <span className="sub-linha">{pos.detalhe}</span>}
            </div>
          </section>

          <section className="cartao" aria-labelledby="titulo-graficos">
            <h2 id="titulo-graficos">Gráficos dos fornos</h2>
            <p className="dica">
              Clique na caixa e cole (Ctrl+V) um recorte da tela, ou dê duplo clique para escolher o arquivo. Os gráficos entram nas
              páginas do PDF. PNG ou JPG.
            </p>
            <div className="rel-slots">
              <SlotImagem
                rotulo="Figura 1 — Têmpera (pré aquecimento + austenitização)"
                campo="grafico_tempera"
                arquivo={graficos.tempera}
                aoMudar={(arquivo) => setGraficos((g) => ({ ...g, tempera: arquivo }))}
              />
              <SlotImagem
                rotulo="Figura 2 — Revenimento 1"
                campo="grafico_rev1"
                arquivo={graficos.rev1}
                aoMudar={(arquivo) => setGraficos((g) => ({ ...g, rev1: arquivo }))}
              />
              <SlotImagem
                rotulo="Figura 3 — Revenimento 2"
                campo="grafico_rev2"
                arquivo={graficos.rev2}
                aoMudar={(arquivo) => setGraficos((g) => ({ ...g, rev2: arquivo }))}
              />
            </div>
          </section>

          <section className="cartao" aria-labelledby="titulo-resp-tt">
            <h2 id="titulo-resp-tt">Responsáveis e datas</h2>
            {dados.aprovadores.length === 0 && (
              <Faixa tipo="erro">Nenhum usuário ativo tem “pode aprovar”. Peça ao administrador para marcar quem aprova pela Qualidade.</Faixa>
            )}
            <div className="form-grade">
              <Campo rotulo="Data do tratamento (execução)" para="tt-data-tratamento" classe="col-1">
                <input id="tt-data-tratamento" type="date" value={dataTratamento} onChange={(e) => setDataTratamento(e.target.value)} />
              </Campo>
              <Campo rotulo="Data do registro (emissão)" para="tt-data-registro" classe="col-1">
                <input id="tt-data-registro" type="date" value={dataRegistro} onChange={(e) => setDataRegistro(e.target.value)} />
              </Campo>
              <Campo rotulo="Data de aprovação" para="tt-data-aprovacao" classe="col-2">
                <input id="tt-data-aprovacao" type="date" value={dataAprovacao} onChange={(e) => setDataAprovacao(e.target.value)} />
              </Campo>
              <div className="col-2">
                <SeletorPessoa
                  id="tt-tecnico"
                  rotulo="Executado por — Técnico de Trat. Térmico"
                  lista={dados.tecnicos}
                  valor={tecnico}
                  aoMudar={setTecnico}
                />
              </div>
              <div className="col-2">
                <SeletorPessoa
                  id="tt-aprovador"
                  rotulo="Aprovado por — Gerente da Qualidade"
                  lista={dados.aprovadores}
                  valor={aprovador}
                  aoMudar={setAprovador}
                />
              </div>
              <Campo rotulo="Observações (opcional)" para="tt-obs" classe="col-4">
                <textarea id="tt-obs" rows={2} maxLength={500} placeholder="Ex.: lote compartilhado com outra OP" value={obs} onChange={(e) => setObs(e.target.value)} />
              </Campo>
            </div>
          </section>

          <section className="cartao acoes-form rel-rodape">
            {erro && (
              <p className="erro-formulario" role="alert">
                {erro}
              </p>
            )}
            <div className="acoes">
              <button type="submit" className="botao botao-primario" disabled={enviando || dados.aprovadores.length === 0}>
                {enviando ? 'Gerando o PDF…' : 'Salvar e gerar PDF'}
              </button>
              <Link to={carga ? `/cargas-tt/${carga.id}` : `/lotes/${lote.id}`} className="botao">
                Cancelar
              </Link>
              <span className="dica">
                O PDF é anexado na etapa Trat. térmico{listaLotes.length > 1 ? ` dos ${listaLotes.length} lotes` : ''}.
              </span>
            </div>
          </section>
        </form>
      </div>

      {confirmando && (
        <Confirmacao
          titulo="Gerar o relatório de novo?"
          rotuloConfirmar="Gerar novamente"
          aoConfirmar={() => void gravar()}
          aoFechar={() => setConfirmando(false)}
          enviando={enviando}
        >
          <p>
            A carga {carga?.numero} já está concluída. Gerar novamente cria um novo anexo em todos os lotes da carga e repete a
            movimentação. Confirma?
          </p>
        </Confirmacao>
      )}
    </>
  );
}
