import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { EnvioArquivos } from '../../componentes/EnvioArquivos';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { Confirmacao } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, enderecoApi, enviarArquivos, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataCurta, dataHoraLocal, inteiro, pecas, TRACO } from '../../lib/formato';
import { useSessao } from '../../lib/sessao';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useCarga } from '../../lib/useCarga';
import { porcento, tomRefugo, tomRetrabalho, tomSaldo, type Tom } from './calculos';
import { formularioDe, ModalCorrida } from './FormCorrida';
import { SeloCarimbado, SeloStatusCorrida } from './ListaCorridas';
import { ModalMotivo } from './ModalMotivo';
import type {
  AnexoCorrida,
  Corrida,
  DetalheCorrida as Detalhe,
  LoteVinculavel,
  RespostaCarimbo,
  RespostaLoteCriado,
  RespostaMensagem,
} from './tipos';

type Janela =
  | { tipo: 'editar' }
  | { tipo: 'cancelar' }
  | { tipo: 'reabrir' }
  | { tipo: 'remover'; anexo: AnexoCorrida }
  | { tipo: 'carimbar'; anexo: AnexoCorrida }
  | { tipo: 'vincular'; lote: LoteVinculavel };

function enderecoAnexo(id: number): string {
  return enderecoApi(`/materia-prima/anexos/${id}/arquivo`);
}

// ---------------------------------------------------------------- números da corrida

function Numero({ rotulo, valor, tom = '', dica }: { rotulo: string; valor: string; tom?: Tom; dica?: string }) {
  return (
    <div className="mp-numero" title={dica}>
      <span className={`mp-numero-valor ${tom ? `mp-tom-${tom}` : ''}`}>{valor}</span>
      <span className="mp-numero-rotulo">{rotulo}</span>
    </div>
  );
}

function Resumo({ c }: { c: Corrida }) {
  return (
    <section className="cartao" aria-labelledby="mp-titulo-resumo">
      <h2 id="mp-titulo-resumo">Resumo</h2>
      <div className="mp-numeros">
        <Numero rotulo="QT-Fund." valor={inteiro(c.qt_fund)} dica="Quantidade fundida pelo fornecedor" />
        <Numero rotulo="QT-Real" valor={inteiro(c.qt_real)} dica="Peças recebidas" />
        <Numero rotulo="QT-OK" valor={inteiro(c.qt_ok)} tom="ok" dica="Aprovadas na inspeção de recebimento" />
        <Numero rotulo="QT-Rej." valor={inteiro(c.qt_rej)} tom="erro" dica="Refugo (sucata)" />
        <Numero rotulo="QT-Retrab." valor={inteiro(c.qt_retrab)} tom="alerta" dica="Retrabalhadas" />
        <Numero rotulo="CP-T.T." valor={inteiro(c.qt_cp_tt)} dica="Corpos de prova para ensaios" />
        <Numero rotulo="Disponível" valor={inteiro(c.qt_disponivel)} tom="info" dica="QT-OK menos os corpos de prova" />
        <Numero rotulo="Consumida" valor={inteiro(c.qt_consumida)} dica="Usada pelos lotes desta corrida" />
        <Numero rotulo="Saldo" valor={inteiro(c.qt_saldo)} tom={tomSaldo(c.qt_saldo)} dica="Disponível menos consumida" />
      </div>
      <div className="mp-numeros">
        <Numero rotulo="Refugo" valor={porcento(c.pct_refugo)} tom={tomRefugo(c.pct_refugo)} dica="QT-Rej. ÷ QT-Real" />
        <Numero rotulo="Retrabalho" valor={porcento(c.pct_retrab)} tom={tomRetrabalho(c.pct_retrab)} dica="QT-Retrab. ÷ QT-Real" />
        <Numero rotulo="Aprovação" valor={porcento(c.pct_aprov)} tom="ok" dica="QT-OK ÷ QT-Real" />
        <Numero rotulo="Rendimento" valor={porcento(c.rendimento)} dica="QT-OK ÷ QT-Fund." />
      </div>
      {c.observacoes && (
        <p className="mp-observacoes">
          <strong>Observações:</strong> {c.observacoes}
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- decisão da Qualidade

function Decisao({ c, podeAprovar, aoReabrir, aoDecidido }: { c: Corrida; podeAprovar: boolean; aoReabrir: () => void; aoDecidido: () => void }) {
  const { usuario } = useSessao();
  const avisos = useAvisos();
  const [decisao, setDecisao] = useState('');
  const [observacao, setObservacao] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function registrar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const r = await api<RespostaMensagem>(`/materia-prima/${c.id}/decisao`, { metodo: 'POST', corpo: { decisao, observacao } });
      avisos.sucesso(r.mensagem);
      setDecisao('');
      setObservacao('');
      aoDecidido();
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  if (c.status === 'aprovada' || c.status === 'reprovada') {
    const aprovada = c.status === 'aprovada';
    return (
      <section className={`cartao mp-decisao mp-decisao-${aprovada ? 'ok' : 'erro'}`} aria-label="Decisão da Qualidade">
        <div className="cartao-topo">
          <div>
            <h2>{aprovada ? '✓ Corrida APROVADA' : '✕ Corrida REPROVADA'}</h2>
            <p className="apoio">
              {aprovada ? 'Aprovada' : 'Reprovada'} por <strong>{c.aprovado_por || TRACO}</strong> em {dataHoraLocal(c.aprovado_em)}
            </p>
          </div>
          {podeAprovar && (
            <button type="button" className="botao" onClick={aoReabrir}>
              Reabrir decisão
            </button>
          )}
        </div>
        {c.obs_aprovacao && (
          <p>
            <strong>{aprovada ? 'Observação:' : 'Motivo:'}</strong> {c.obs_aprovacao}
          </p>
        )}
      </section>
    );
  }

  return (
    <section className="cartao mp-decisao mp-decisao-alerta" aria-labelledby="mp-titulo-decisao">
      <h2 id="mp-titulo-decisao">Aprovação pendente</h2>
      <p className="apoio">Avalie os resultados da corrida e decida: aprovar ou reprovar para uso em produção.</p>
      {!podeAprovar ? (
        <p className="dica">Aguardando a decisão de quem pode aprovar pela Qualidade.</p>
      ) : (
        <form className="form-grade" onSubmit={(e) => void registrar(e)}>
          <Campo rotulo="Decisão" para="mp-decisao" obrigatorio classe="col-2">
            <select id="mp-decisao" required value={decisao} onChange={(e) => setDecisao(e.target.value)}>
              <option value="">Selecione…</option>
              <option value="aprovada">Aprovar corrida (liberada para produção)</option>
              <option value="reprovada">Reprovar corrida (não usar)</option>
            </select>
          </Campo>
          <Campo rotulo="Responsável pela decisão" para="mp-decisor" classe="col-2" dica="Sempre o usuário que está logado.">
            <div id="mp-decisor" className="automatico">
              {usuario?.nome ?? TRACO}
            </div>
          </Campo>
          <Campo
            rotulo="Observação / motivo"
            para="mp-obs-decisao"
            obrigatorio={decisao === 'reprovada'}
            classe="col-4"
            dica="Obrigatório se reprovar."
          >
            <textarea
              id="mp-obs-decisao"
              rows={2}
              maxLength={2000}
              required={decisao === 'reprovada'}
              value={observacao}
              onChange={(e) => setObservacao(e.target.value)}
            />
          </Campo>
          {erro && (
            <p className="erro-formulario col-4" role="alert">
              {erro}
            </p>
          )}
          <div className="col-4">
            <button type="submit" className="botao botao-primario" disabled={enviando}>
              {enviando ? 'Gravando…' : 'Registrar decisão'}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- criar lote a partir da corrida

function CriarLote({ d, aoCriar }: { d: Detalhe; aoCriar: (r: RespostaLoteCriado) => void }) {
  const c = d.corrida;
  const [op, setOp] = useState('');
  const [numero, setNumero] = useState('');
  const [numeroTocado, setNumeroTocado] = useState(false);
  const [qtd, setQtd] = useState('');
  const [coditem, setCoditem] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const coditemDaOp = useMemo(() => new Map(d.ops.map((o) => [o.op, o.coditem])), [d.ops]);

  function mudarOp(valor: string) {
    setOp(valor);
    // Igual ao sistema antigo: o número do lote acompanha a OP até ser digitado à mão; o CODITEM vem do cadastro
    if (!numeroTocado) setNumero(valor.trim());
    setCoditem(coditemDaOp.get(valor.trim()) ?? '');
  }

  async function criar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const corpo = { op: op.trim(), numero: numero.trim(), qtd: Number.parseInt(qtd, 10) || 0, coditem: coditem.trim(), tipo: c.tipo_destino || null };
      const r = await api<RespostaLoteCriado>(`/materia-prima/${c.id}/lotes`, { metodo: 'POST', corpo });
      setOp('');
      setNumero('');
      setNumeroTocado(false);
      setQtd('');
      setCoditem('');
      aoCriar(r);
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <details className="recolhivel mp-bloco">
      <summary>+ Criar lote a partir desta corrida</summary>
      {c.status === 'reprovada' && (
        <Faixa tipo="erro">Corrida REPROVADA. Criar lote assim mesmo é desaconselhado.</Faixa>
      )}
      {c.status === 'pendente' && (
        <Faixa tipo="alerta">
          Corrida ainda PENDENTE de aprovação. O lote será criado, mas só deve ser usado depois da aprovação formal.
        </Faixa>
      )}
      <form id="form-criar-lote-corrida" className="form-grade mp-form-lote" onSubmit={(e) => void criar(e)} onKeyDown={enterVaiParaProximo}>
        <Campo rotulo="Nº da OP" para="mp-lote-op" obrigatorio>
          <input id="mp-lote-op" type="text" className="mono" list="mp-ops-tipo" required maxLength={20} placeholder="Ex.: 900001"
            value={op} onChange={(e) => mudarOp(e.target.value)} />
          <datalist id="mp-ops-tipo">
            {d.ops.map((o) => (
              <option key={o.op} value={o.op}>
                {[o.coditem, o.descricao].filter(Boolean).join(' - ')}
              </option>
            ))}
          </datalist>
        </Campo>
        <Campo rotulo="Nº do lote" para="mp-lote-numero" obrigatorio>
          <input id="mp-lote-numero" type="text" className="mono" required maxLength={40} placeholder="Ex.: 900001" value={numero}
            onChange={(e) => { setNumero(e.target.value); setNumeroTocado(true); }} />
        </Campo>
        <Campo rotulo="Quantidade" para="mp-lote-qtd" obrigatorio dica={`Saldo disponível: ${pecas(c.qt_saldo)}`}>
          <input id="mp-lote-qtd" type="number" inputMode="numeric" className="num" required min={1} max={Math.max(c.qt_saldo, 1)} step={1}
            placeholder={`máx. ${c.qt_saldo}`} value={qtd} onChange={(e) => setQtd(e.target.value)} />
        </Campo>
        <Campo rotulo="Tipo" para="mp-lote-tipo" dica="Vem da corrida.">
          <div id="mp-lote-tipo" className="automatico">
            {c.tipo_destino ? <SeloTipo tipo={c.tipo_destino} /> : <span className="automatico-vazio">sem tipo</span>}
          </div>
        </Campo>
        <Campo rotulo="CODITEM" para="mp-lote-coditem" classe="col-2" dica="Opcional: vem sozinho ao escolher uma OP do cadastro.">
          <input id="mp-lote-coditem" type="text" className="mono" maxLength={40} value={coditem} onChange={(e) => setCoditem(e.target.value)} />
        </Campo>
        <p className="dica col-4">
          Tipo e corrida vêm automaticamente desta matéria-prima ({c.tipo_destino || 'sem tipo'} · {c.corrida}). Os certificados
          anexados na corrida já entram na etapa Receb. MP do lote novo.
        </p>
        {erro && (
          <p className="erro-formulario col-4" role="alert">
            {erro}
          </p>
        )}
        <div className="col-4">
          <button type="submit" className="botao botao-primario" disabled={enviando || c.qt_saldo <= 0}>
            {enviando ? 'Criando…' : 'Criar lote'}
          </button>
          {c.qt_saldo <= 0 && <span className="dica"> Sem saldo nesta corrida.</span>}
        </div>
      </form>
    </details>
  );
}

function VincularLote({ d, aoEscolher }: { d: Detalhe; aoEscolher: (lote: LoteVinculavel) => void }) {
  const [escolhido, setEscolhido] = useState('');
  if (d.vinculaveis.length === 0) return null;
  const c = d.corrida;

  return (
    <details className="recolhivel mp-bloco">
      <summary>Vincular lote existente a esta corrida</summary>
      <p className="dica">
        Lotes do tipo <strong>{c.tipo_destino}</strong> que não estão vinculados a esta corrida. A operação troca a corrida do lote
        para <strong>{c.corrida}</strong>, substituindo o valor atual, se houver.
      </p>
      <form
        className="filtros"
        onSubmit={(e) => {
          e.preventDefault();
          const lote = d.vinculaveis.find((l) => String(l.id) === escolhido);
          if (lote) aoEscolher(lote);
        }}
      >
        <div className="campo campo-busca">
          <label htmlFor="mp-vincular">Lote</label>
          <select id="mp-vincular" required value={escolhido} onChange={(e) => setEscolhido(e.target.value)}>
            <option value="">Selecione…</option>
            {d.vinculaveis.map((l) => (
              <option key={l.id} value={l.id}>
                OP {l.op} · Lote {l.numero} · {pecas(l.qtd)}
                {l.corrida ? ` (hoje: corrida ${l.corrida})` : ''}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="botao">
          Vincular
        </button>
      </form>
    </details>
  );
}

// ---------------------------------------------------------------- tela

export function DetalheCorrida() {
  const { id } = useParams();
  const { usuario, pode } = useSessao();
  const avisos = useAvisos();
  const navegar = useNavigate();
  const detalhe = useCarga<Detalhe>((sinal) => api(`/materia-prima/${id}`, { sinal }), [id]);
  const [janela, setJanela] = useState<Janela | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erroJanela, setErroJanela] = useState<string | null>(null);
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [anexando, setAnexando] = useState(false);
  const [carimbo, setCarimbo] = useState<RespostaCarimbo | null>(null);
  const [loteCriado, setLoteCriado] = useState<RespostaLoteCriado | null>(null);

  if (detalhe.erro) {
    const naoExiste = detalhe.erro === 'Corrida de matéria-prima não encontrada.';
    return (
      <>
        <Cabecalho titulo="Matéria-prima" />
        {naoExiste ? (
          <Vazio titulo="Esta corrida não existe ou foi cancelada.">
            <Link to="/materia-prima">Voltar para a lista de corridas</Link>
          </Vazio>
        ) : (
          <ErroCarga mensagem={detalhe.erro} aoTentar={detalhe.recarregar} />
        )}
      </>
    );
  }
  if (!detalhe.dados) return <Carregando />;

  const d = detalhe.dados;
  const c = d.corrida;
  const podeCancelar = pode.aprovador || pode.admin;

  function fechar() {
    setJanela(null);
    setErroJanela(null);
    setEnviando(false);
  }

  async function executar(acao: () => Promise<void>) {
    setErroJanela(null);
    setEnviando(true);
    try {
      await acao();
      fechar();
      detalhe.recarregar();
    } catch (falha) {
      setErroJanela(mensagemDeErro(falha));
      setEnviando(false);
    }
  }

  async function anexar() {
    if (arquivos.length === 0) {
      avisos.erro('Escolha um ou mais arquivos.');
      return;
    }
    setAnexando(true);
    try {
      const r = await enviarArquivos<RespostaMensagem>(`/materia-prima/${c.id}/anexos`, { arquivos });
      avisos.sucesso(r.mensagem);
      setArquivos([]);
      detalhe.recarregar();
    } catch (falha) {
      avisos.erro(mensagemDeErro(falha));
    } finally {
      setAnexando(false);
    }
  }

  function carimbar(anexo: AnexoCorrida) {
    // A aba é aberta já no clique (senão o navegador bloqueia) e recebe o PDF quando ele fica pronto
    const aba = window.open('', '_blank');
    if (aba) {
      aba.document.title = 'Carimbando…';
      aba.document.body.textContent = 'Gerando o PDF carimbado… esta aba mostra o arquivo assim que ele ficar pronto.';
    }
    void executar(async () => {
      try {
        const r = await api<RespostaCarimbo>(`/materia-prima/${c.id}/anexos/${anexo.id}/carimbar`, { metodo: 'POST' });
        if (aba && !aba.closed) aba.location.href = new URL(enderecoAnexo(r.anexo_id), window.location.origin).href;
        setCarimbo(r);
        avisos.sucesso(r.mensagem);
      } catch (falha) {
        aba?.close();
        throw falha;
      }
    });
  }

  const lancadaPor = [c.responsavel && `Lançada por ${c.responsavel}`, c.criado_em && `em ${dataHoraLocal(c.criado_em)}`].filter(Boolean).join(' ');
  const apoio = [
    `NF ${c.nf_entrada || TRACO}`,
    `Fornecedor: ${c.fornecedor || TRACO}`,
    `Recebida em ${dataCurta(c.data_recebimento)}`,
    lancadaPor,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <>
      <Cabecalho
        titulo={`Corrida ${c.corrida}`}
        apoio={
          <>
            <span className="acoes-linha mp-titulo-selos">
              {c.tipo_destino && <SeloTipo tipo={c.tipo_destino} />}
              <SeloStatusCorrida status={c.status} />
            </span>{' '}
            {apoio}
          </>
        }
      >
        <Link className="botao" to="/materia-prima">
          ← Matéria-prima
        </Link>
        <button type="button" className="botao" onClick={() => setJanela({ tipo: 'editar' })}>
          Editar dados
        </button>
        {podeCancelar && (
          <button type="button" className="botao botao-perigo-contorno" onClick={() => setJanela({ tipo: 'cancelar' })}>
            Cancelar corrida
          </button>
        )}
      </Cabecalho>

      {pode.aprovador && !d.tenho_assinatura && (
        <Faixa tipo="alerta" papel="note">
          <strong>Você ainda não tem assinatura digital cadastrada.</strong> O carimbo APROVADO precisa da imagem da sua
          assinatura. {pode.admin ? <Link to="/usuarios">Cadastrar em Usuários</Link> : 'Peça ao administrador para cadastrá-la em Usuários.'}
        </Faixa>
      )}

      {carimbo && (
        <div className="mp-carimbado" role="status">
          <span className="mp-carimbado-icone" aria-hidden="true">
            ✓
          </span>
          <div>
            <strong>Certificado carimbado com sucesso!</strong>
            <p className="apoio">{carimbo.mensagem} Abra o PDF e confira o carimbo antes de prosseguir.</p>
          </div>
          <a className="botao botao-primario" href={enderecoAnexo(carimbo.anexo_id)} target="_blank" rel="noopener">
            Abrir PDF carimbado em outra aba
          </a>
          <button type="button" className="botao-icone" aria-label="Fechar aviso" onClick={() => setCarimbo(null)}>
            ×
          </button>
        </div>
      )}

      <Decisao c={c} podeAprovar={pode.aprovador} aoReabrir={() => setJanela({ tipo: 'reabrir' })} aoDecidido={detalhe.recarregar} />

      <Resumo c={c} />

      <section className="cartao" aria-labelledby="mp-titulo-anexos">
        <h2 id="mp-titulo-anexos">Documentos anexados (certificado químico, laudos)</h2>
        {d.anexos.length === 0 ? (
          <p className="dica">Nenhum anexo.</p>
        ) : (
          <ul className="mp-anexos">
            {d.anexos.map((a) => (
              <li key={a.id} className="mp-anexo">
                <div className="mp-anexo-nome">
                  <a href={enderecoAnexo(a.id)} target="_blank" rel="noopener">
                    {a.nome}
                    <span className="so-leitor"> (abre em outra aba)</span>
                  </a>
                  <span className="registro-meta">{dataHoraLocal(a.quando)}</span>
                  {a.carimbado && <SeloCarimbado />}
                </div>
                <span className="acoes-linha">
                  {pode.aprovador && a.pdf && !a.carimbado && c.status !== 'reprovada' && (
                    <button type="button" className="botao botao-pequeno mp-botao-carimbar" title="Gera um PDF novo com o carimbo APROVADO"
                      onClick={() => setJanela({ tipo: 'carimbar', anexo: a })}>
                      ✓ Carimbar{c.status !== 'aprovada' ? ' e aprovar' : ''}
                    </button>
                  )}
                  <button type="button" className="botao botao-pequeno botao-perigo-contorno" onClick={() => setJanela({ tipo: 'remover', anexo: a })}>
                    Remover
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
        {c.status === 'reprovada' && d.anexos.some((a) => a.pdf && !a.carimbado) && (
          <p className="dica">Corrida reprovada: para carimbar o certificado, reabra a decisão antes.</p>
        )}
        <EnvioArquivos arquivos={arquivos} aoMudar={setArquivos} aceita=".pdf,.jpg,.jpeg,.png" rotulo="Anexar documentos"
          dica="PDF, JPG ou PNG, até 25 MB cada. Dá para escolher vários de uma vez." desabilitado={anexando} />
        {arquivos.length > 0 && (
          <button type="button" className="botao botao-primario" onClick={() => void anexar()} disabled={anexando}>
            {anexando ? 'Enviando…' : `Anexar ${arquivos.length} arquivo(s)`}
          </button>
        )}
      </section>

      <section className="cartao" aria-labelledby="mp-titulo-lotes">
        <h2 id="mp-titulo-lotes">
          Lotes fabricados usando esta corrida ({inteiro(d.lotes.length)}){' '}
          <span className="mp-saldo-titulo">
            · Saldo disponível: <strong className={`mp-tom-${tomSaldo(c.qt_saldo)}`}>{pecas(c.qt_saldo)}</strong>
          </span>
        </h2>
        {loteCriado && (
          <Faixa tipo="sucesso" papel="status">
            {loteCriado.mensagem} <Link to={`/lotes/${loteCriado.lote_id}`}>Abrir o lote {loteCriado.numero}</Link>
          </Faixa>
        )}
        {d.lotes.length === 0 ? (
          <p className="dica">Ainda nenhum lote vinculado a esta corrida.</p>
        ) : (
          <div className="tabela-rolagem">
            <table className="tabela">
              <caption className="so-leitor">Lotes desta corrida</caption>
              <thead>
                <tr>
                  <th scope="col">OP</th>
                  <th scope="col">Lote</th>
                  <th scope="col">Tipo</th>
                  <th scope="col" className="num">
                    Qtd
                  </th>
                  <th scope="col">Etapa</th>
                  <th scope="col">Criado em</th>
                  <th scope="col">
                    <span className="so-leitor">Ações</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.lotes.map((l) => (
                  <tr key={l.id}>
                    <td className="mono">
                      <strong>{l.op}</strong>
                    </td>
                    <td className="mono">{l.numero}</td>
                    <td>
                      <SeloTipo tipo={l.tipo} />
                    </td>
                    <td className="num">{inteiro(l.qtd)}</td>
                    <td>{l.concluido ? <span className="selo selo-ok">Concluído</span> : l.etapa}</td>
                    <td>{dataHoraLocal(l.criado_em)}</td>
                    <td>
                      <Link className="botao botao-pequeno" to={`/lotes/${l.id}`}>
                        Abrir
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <CriarLote
          d={d}
          aoCriar={(r) => {
            avisos.sucesso(r.mensagem);
            setLoteCriado(r);
            detalhe.recarregar();
          }}
        />
        <VincularLote d={d} aoEscolher={(lote) => setJanela({ tipo: 'vincular', lote })} />
      </section>

      {janela?.tipo === 'editar' && (
        <ModalCorrida
          titulo={`Editar dados da corrida ${c.corrida}`}
          inicial={formularioDe(c)}
          novo={false}
          fornecedores={d.fornecedores}
          rotuloEnviar="Salvar"
          aoFechar={fechar}
          aoGravar={async (corpo) => {
            const r = await api<RespostaMensagem>(`/materia-prima/${c.id}`, { metodo: 'PUT', corpo });
            avisos.sucesso(r.mensagem);
            fechar();
            detalhe.recarregar();
          }}
        />
      )}

      {janela?.tipo === 'cancelar' && (
        <ModalMotivo
          titulo={`Cancelar a corrida ${c.corrida}`}
          rotulo="Motivo do cancelamento"
          rotuloConfirmar="Cancelar corrida"
          perigo
          aoFechar={fechar}
          aoConfirmar={async (motivo) => {
            const r = await api<RespostaMensagem>(`/materia-prima/${c.id}/cancelar`, { metodo: 'POST', corpo: { motivo } });
            avisos.sucesso(r.mensagem);
            navegar('/materia-prima');
          }}
        >
          <p>
            A corrida some das listas, mas continua guardada no sistema e na auditoria. Só dá para cancelar se nenhum lote estiver
            usando a corrida.
          </p>
        </ModalMotivo>
      )}

      {janela?.tipo === 'reabrir' && (
        <ModalMotivo
          titulo="Reabrir a decisão"
          rotuloConfirmar="Reabrir decisão"
          aoFechar={fechar}
          aoConfirmar={async (motivo) => {
            const r = await api<RespostaMensagem>(`/materia-prima/${c.id}/reabrir`, { metodo: 'POST', corpo: { motivo } });
            avisos.sucesso(r.mensagem);
            fechar();
            detalhe.recarregar();
          }}
        >
          <p>
            A corrida {c.corrida} voltará para o estado <strong>PENDENTE</strong> e precisará de uma nova aprovação.
          </p>
        </ModalMotivo>
      )}

      {janela?.tipo === 'remover' && (
        <ModalMotivo
          titulo="Remover anexo"
          rotuloConfirmar="Remover"
          perigo
          aoFechar={fechar}
          aoConfirmar={async (motivo) => {
            const r = await api<RespostaMensagem>(`/materia-prima/anexos/${janela.anexo.id}/remover`, { metodo: 'POST', corpo: { motivo } });
            avisos.sucesso(r.mensagem);
            fechar();
            detalhe.recarregar();
          }}
        >
          <p>
            Remover <strong>{janela.anexo.nome}</strong> desta corrida? O arquivo continua guardado no servidor. Os lotes que já
            receberam uma cópia não mudam.
          </p>
        </ModalMotivo>
      )}

      {janela?.tipo === 'carimbar' && (
        <Confirmacao
          titulo="Carimbar certificado"
          rotuloConfirmar={c.status !== 'aprovada' ? 'Carimbar e aprovar' : 'Carimbar'}
          enviando={enviando}
          aoFechar={fechar}
          aoConfirmar={() => carimbar(janela.anexo)}
        >
          <p>
            Gerar uma versão <strong>CARIMBADA</strong> de <strong>{janela.anexo.nome}</strong> com APROVADO e a assinatura digital
            de {usuario?.nome}?
          </p>
          <ul className="mp-lista-efeitos">
            <li>O carimbo sai no canto inferior direito de todas as páginas. O arquivo original fica guardado.</li>
            {c.status !== 'aprovada' && <li>Isso também vai APROVAR a corrida {c.corrida}.</li>}
            {d.lotes.length > 0 && (
              <li>O PDF carimbado vai para a etapa Receb. MP {d.lotes.length === 1 ? 'do lote' : `dos ${d.lotes.length} lotes`} desta corrida, no lugar do certificado sem carimbo.</li>
            )}
          </ul>
          {erroJanela && (
            <p className="erro-formulario" role="alert">
              {erroJanela}
            </p>
          )}
        </Confirmacao>
      )}

      {janela?.tipo === 'vincular' && (
        <Confirmacao
          titulo="Vincular lote à corrida"
          rotuloConfirmar="Vincular"
          enviando={enviando}
          aoFechar={fechar}
          aoConfirmar={() =>
            void executar(async () => {
              const r = await api<RespostaMensagem>(`/materia-prima/${c.id}/vincular`, { metodo: 'POST', corpo: { lote_id: janela.lote.id } });
              avisos.sucesso(r.mensagem);
            })
          }
        >
          <p>
            Vincular o lote <strong>{janela.lote.numero}</strong> (OP {janela.lote.op}, {pecas(janela.lote.qtd)}) à corrida{' '}
            <strong>{c.corrida}</strong>?
          </p>
          {janela.lote.corrida && (
            <Faixa tipo="alerta">
              Hoje o lote está na corrida {janela.lote.corrida}: esse valor será substituído por {c.corrida}.
            </Faixa>
          )}
          {erroJanela && (
            <p className="erro-formulario" role="alert">
              {erroJanela}
            </p>
          )}
        </Confirmacao>
      )}
    </>
  );
}
