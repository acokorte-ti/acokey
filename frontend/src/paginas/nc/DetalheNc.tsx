import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { Confirmacao } from '../../componentes/Modal';
import { SeloNc, SeloRegistro, SeloTipo } from '../../componentes/Selos';
import { api, ErroApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataHoraLocal, pecas, TRACO } from '../../lib/formato';
import { useSessao } from '../../lib/sessao';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useCarga } from '../../lib/useCarga';
import { ondeFoi } from './ListaNc';
import type { DetalheNc, Disposicao, RespostaDecisao } from './tipos';

const OPCOES: { valor: Disposicao; rotulo: string; desvio: boolean }[] = [
  { valor: 'retrabalho', rotulo: 'Retrabalho', desvio: false },
  { valor: 'sucata', rotulo: 'Sucata', desvio: false },
  { valor: 'uso_como_esta', rotulo: 'Uso como está (desvio)', desvio: true },
  { valor: 'anulada', rotulo: 'Anulada (erro de digitação)', desvio: true },
];

/** Pergunta de confirmação de cada disposição (as mesmas do sistema antigo). */
const CONFIRMACAO: Record<Disposicao, string> = {
  retrabalho: 'Confirma a decisão de RETRABALHO para esta NC?',
  sucata: 'Confirma SUCATEAR a quantidade informada? Isso reduz a quantidade do lote.',
  uso_como_esta: 'Confirma aceitar USO COMO ESTÁ, com desvio da especificação?',
  anulada:
    'Confirma ANULAR esta NC (erro de digitação)? O registro reprovado será marcado como anulado e o fluxo vai ignorá-lo. Será preciso gravar um NOVO registro da etapa.',
};

function linkDaEtapa(nc: DetalheNc): string | null {
  if (!nc.lote || !nc.etapa) return null;
  return `/lotes/${nc.lote.id}/etapas/${nc.etapa}${nc.sub ? `?sub=${encodeURIComponent(nc.sub)}` : ''}`;
}

// ---------------------------------------------------------------- resumo

function Resumo({ nc }: { nc: DetalheNc }) {
  const etapa = linkDaEtapa(nc);
  return (
    <section className="cartao" aria-labelledby="nc-titulo-resumo">
      <div className="cartao-topo">
        <h2 id="nc-titulo-resumo">Reprovação</h2>
        <SeloNc status={nc.status} />
      </div>
      <dl className="ficha ficha-linha">
        {nc.lote && (
          <>
            <div>
              <dt>Lote</dt>
              <dd>
                <Link to={`/lotes/${nc.lote.id}`} className="mono">
                  {nc.lote.numero}
                </Link>{' '}
                <SeloTipo tipo={nc.lote.tipo} />
              </dd>
            </div>
            <div>
              <dt>OP</dt>
              <dd className="mono">{nc.lote.op || TRACO}</dd>
            </div>
            <div>
              <dt>Peças no lote</dt>
              <dd>{pecas(nc.lote.qtd)}</dd>
            </div>
          </>
        )}
        <div>
          <dt>Etapa</dt>
          <dd>{ondeFoi(nc)}</dd>
        </div>
        <div>
          <dt>Aberta automaticamente em</dt>
          <dd>
            {dataHoraLocal(nc.aberta_em)}
            {nc.aberta_por && <span className="sub-linha"> · por {nc.aberta_por}</span>}
          </dd>
        </div>
      </dl>
      <div>
        <p className="rotulo">Motivo da reprovação</p>
        <p className="nc-texto">{nc.descricao || TRACO}</p>
      </div>
      {nc.registro && (
        <p className="nc-registro">
          <SeloRegistro status={nc.registro.status} /> Registro #{nc.registro.id} gravado em {dataHoraLocal(nc.registro.quando)}
          {nc.registro.responsavel && <> por {nc.registro.responsavel}</>}
          {etapa && (
            <>
              {' · '}
              <Link to={etapa} className="botao-link">
                Ver etapa do lote
              </Link>
            </>
          )}
        </p>
      )}
      {nc.registro?.anulado && (
        <Faixa tipo="info">
          Este registro foi <strong>anulado</strong> (erro de digitação) em {dataHoraLocal(nc.registro.anulado_em)}
          {nc.registro.anulado_por && <> por {nc.registro.anulado_por}</>}: o fluxo do lote o ignora.
          {nc.registro.anulado_motivo && <> Motivo: {nc.registro.anulado_motivo}</>}
        </Faixa>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- decisão (NC aberta)

interface PropsDecisao {
  nc: DetalheNc;
  aoDecidir: (resposta: RespostaDecisao) => void;
}

function FormDecisao({ nc, aoDecidir }: PropsDecisao) {
  const avisos = useAvisos();
  const [disposicao, setDisposicao] = useState<Disposicao | ''>('');
  const [qtd, setQtd] = useState('');
  const [justificativa, setJustificativa] = useState('');
  const [motivo, setMotivo] = useState('');
  const [observacoes, setObservacoes] = useState('');
  const [erro, setErro] = useState<string | null>(null);
  const [confirmando, setConfirmando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const qtdLote = nc.lote?.qtd ?? 0;
  const podeDesvio = nc.pode_decidir_desvio;

  function validar(): string | null {
    if (!disposicao) return 'Escolha uma disposição.';
    if (disposicao === 'sucata') {
      const n = Number(qtd);
      if (!Number.isInteger(n) || n < 1 || n > qtdLote) return `Informe uma quantidade sucateada válida (entre 1 e ${qtdLote}).`;
    }
    if (disposicao === 'uso_como_esta' && !justificativa.trim()) return 'Informe a justificativa do desvio para aceitar "uso como está".';
    if (disposicao === 'anulada' && !motivo.trim()) return 'Informe o motivo da anulação.';
    return null;
  }

  function pedirConfirmacao(evento: FormEvent) {
    evento.preventDefault();
    const problema = validar();
    setErro(problema);
    if (!problema) setConfirmando(true);
  }

  async function confirmar() {
    if (!disposicao) return;
    setEnviando(true);
    try {
      const resposta = await api<RespostaDecisao>(`/nao-conformidades/${nc.id}/decidir`, {
        metodo: 'POST',
        corpo: {
          disposicao,
          observacoes,
          qtd_afetada: disposicao === 'sucata' ? Number(qtd) : null,
          justificativa: disposicao === 'uso_como_esta' ? justificativa : '',
          motivo_anulacao: disposicao === 'anulada' ? motivo : '',
        },
      });
      setConfirmando(false);
      avisos.sucesso(resposta.mensagem);
      aoDecidir(resposta);
    } catch (e) {
      setConfirmando(false);
      setErro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="cartao" aria-labelledby="nc-titulo-decidir">
      <h2 id="nc-titulo-decidir">Decidir disposição</h2>
      {nc.etapa === 'dureza' && nc.corrigir_dureza_disponivel && podeDesvio && (
        <Faixa tipo="info">
          <strong>Erro de digitação em dureza?</strong> Antes de decidir aqui, se o problema foi um valor digitado errado (ex.: "2,5" em
          vez de "25"), use{' '}
          <Link to={`/nao-conformidades/${nc.id}/corrigir-dureza`} className="link-forte">
            Corrigir valores de dureza
          </Link>
          : abre as leituras atuais para você digitar de novo; se ficar aprovado, a NC fecha sozinha.
        </Faixa>
      )}
      <form onSubmit={pedirConfirmacao} onKeyDown={enterVaiParaProximo} className="form-coluna" noValidate>
        <fieldset className="nc-opcoes">
          <legend className="so-leitor">Disposição</legend>
          {OPCOES.map((opcao) => {
            const bloqueada = opcao.desvio && !podeDesvio;
            const marcada = disposicao === opcao.valor;
            const id = `nc-disp-${opcao.valor}`;
            return (
              <div key={opcao.valor} className={`nc-disp ${marcada ? 'nc-disp-sel' : ''} ${bloqueada ? 'nc-disp-bloqueada' : ''}`}>
                <label htmlFor={id} className="nc-disp-rotulo">
                  <input
                    id={id}
                    type="radio"
                    name="disposicao"
                    value={opcao.valor}
                    checked={marcada}
                    disabled={bloqueada}
                    onChange={() => {
                      setDisposicao(opcao.valor);
                      setErro(null);
                    }}
                  />
                  {opcao.rotulo}
                </label>
                {opcao.valor === 'retrabalho' && (
                  <p className="nc-disp-texto">
                    A peça volta para reprocessamento ou novo ensaio. O lote fica bloqueado nesta etapa até um novo registro ser aprovado — a NC
                    é encerrada automaticamente nesse momento.
                  </p>
                )}
                {opcao.valor === 'sucata' && (
                  <div className="nc-disp-texto">
                    <div className="campo nc-campo-qtd">
                      <label htmlFor="nc-qtd">Quantidade sucateada</label>
                      <input
                        id="nc-qtd"
                        type="number"
                        inputMode="numeric"
                        min={1}
                        max={qtdLote || 1}
                        step={1}
                        value={qtd}
                        placeholder="ex.: 5"
                        onFocus={() => setDisposicao('sucata')}
                        onChange={(e) => setQtd(e.target.value)}
                      />
                    </div>
                    <p>
                      Abate essa quantidade das {pecas(qtdLote)} do lote (o restante segue o fluxo normal).
                      {disposicao === 'sucata' && Number(qtd) >= 1 && Number(qtd) <= qtdLote && (
                        <strong> O lote fica com {pecas(qtdLote - Number(qtd))}.</strong>
                      )}
                    </p>
                  </div>
                )}
                {opcao.valor === 'uso_como_esta' && (
                  <div className="nc-disp-texto">
                    {bloqueada ? (
                      <p className="texto-erro">Só um usuário com permissão de aprovação ("pode aprovar") pode decidir esta disposição.</p>
                    ) : (
                      <div className="campo">
                        <label htmlFor="nc-justificativa">
                          Justificativa do desvio <span className="obrigatorio">*</span>
                        </label>
                        <textarea
                          id="nc-justificativa"
                          rows={2}
                          maxLength={2000}
                          value={justificativa}
                          placeholder="Por que a peça pode ser aceita fora da especificação…"
                          onFocus={() => setDisposicao('uso_como_esta')}
                          onChange={(e) => setJustificativa(e.target.value)}
                        />
                      </div>
                    )}
                  </div>
                )}
                {opcao.valor === 'anulada' && (
                  <div className="nc-disp-texto">
                    {bloqueada ? (
                      <p className="texto-erro">Só um usuário com permissão de aprovação ("pode aprovar") pode anular uma NC.</p>
                    ) : (
                      <>
                        <p>
                          Use quando a reprovação foi causada por <strong>erro de digitação</strong> (não há não conformidade real). O registro fica
                          marcado como anulado — o fluxo o ignora. Depois, grave um NOVO registro da etapa com o valor certo.
                        </p>
                        <div className="campo">
                          <label htmlFor="nc-motivo">
                            Motivo da anulação <span className="obrigatorio">*</span>
                          </label>
                          <textarea
                            id="nc-motivo"
                            rows={2}
                            maxLength={2000}
                            value={motivo}
                            placeholder="Ex.: Digitado 2,5 em vez de 25 na leitura CP-1 do RIP-35"
                            onFocus={() => setDisposicao('anulada')}
                            onChange={(e) => setMotivo(e.target.value)}
                          />
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </fieldset>
        <div className="campo">
          <label htmlFor="nc-observacoes">Observações (opcional)</label>
          <textarea id="nc-observacoes" rows={2} maxLength={2000} value={observacoes} onChange={(e) => setObservacoes(e.target.value)} />
        </div>
        {erro && (
          <p className="erro-formulario" role="alert">
            {erro}
          </p>
        )}
        <div className="acoes acoes-form">
          <button type="submit" className="botao botao-primario" disabled={enviando}>
            Registrar decisão
          </button>
        </div>
      </form>
      {confirmando && disposicao && (
        <Confirmacao
          titulo={`Decisão da ${nc.numero}`}
          rotuloConfirmar="Confirmar decisão"
          aoConfirmar={confirmar}
          aoFechar={() => setConfirmando(false)}
          enviando={enviando}
          perigo={disposicao === 'sucata' || disposicao === 'anulada'}
        >
          <p>{CONFIRMACAO[disposicao]}</p>
          {disposicao === 'sucata' && (
            <p>
              {pecas(Number(qtd))} sucateada(s): o lote passa de {pecas(qtdLote)} para {pecas(qtdLote - Number(qtd))}.
            </p>
          )}
        </Confirmacao>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- em tratamento e encerrada

function EmTratamento({ nc, aoReabrir }: { nc: DetalheNc; aoReabrir: (resposta: RespostaDecisao) => void }) {
  const { pode } = useSessao();
  const avisos = useAvisos();
  const [confirmando, setConfirmando] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);

  async function reabrir() {
    setEnviando(true);
    try {
      const resposta = await api<RespostaDecisao>(`/nao-conformidades/${nc.id}/reabrir`, { metodo: 'POST', corpo: { motivo } });
      setConfirmando(false);
      avisos.sucesso(resposta.mensagem);
      aoReabrir(resposta);
    } catch (e) {
      avisos.erro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="cartao nc-situacao nc-situacao-tratamento" aria-labelledby="nc-titulo-tratamento">
      <h2 id="nc-titulo-tratamento">Decisão: retrabalho</h2>
      <p>Aguardando um novo registro aprovado nesta etapa para encerrar automaticamente.</p>
      {nc.observacoes && <p className="nc-texto">Observações: {nc.observacoes}</p>}
      <p className="dica">
        Decidido em {dataHoraLocal(nc.decidida_em)} por {nc.decidida_por || TRACO}.
      </p>
      <div className="acoes">
        <button type="button" className="botao" onClick={() => setConfirmando(true)} disabled={!pode.aprovador}>
          ↶ Reabrir decisão
        </button>
        {!pode.aprovador && <span className="dica">Só quem pode aprovar (assinar pela Qualidade) reabre a decisão.</span>}
      </div>
      {confirmando && (
        <Confirmacao
          titulo={`Reabrir a ${nc.numero}`}
          rotuloConfirmar="Reabrir decisão"
          aoConfirmar={reabrir}
          aoFechar={() => setConfirmando(false)}
          enviando={enviando}
        >
          <p>Desfazer a decisão de retrabalho e voltar para aberta?</p>
          <div className="campo">
            <label htmlFor="nc-motivo-reabrir">Motivo (opcional)</label>
            <textarea id="nc-motivo-reabrir" rows={2} maxLength={2000} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </div>
        </Confirmacao>
      )}
    </section>
  );
}

function Encerrada({ nc }: { nc: DetalheNc }) {
  return (
    <section className="cartao nc-situacao nc-situacao-encerrada" aria-labelledby="nc-titulo-encerrada">
      <h2 id="nc-titulo-encerrada">Encerrada — disposição: {nc.disposicao_nome || TRACO}</h2>
      {nc.disposicao === 'sucata' && <p>{pecas(nc.qtd_afetada)} sucateada(s).</p>}
      {nc.disposicao === 'uso_como_esta' && (
        <p>
          <strong>Justificativa:</strong> {nc.justificativa}
        </p>
      )}
      {nc.disposicao === 'anulada' && (
        <>
          <p>
            <strong>Motivo da anulação:</strong> {nc.justificativa}
          </p>
          <p className="dica">O registro reprovado foi tratado como erro de digitação — o fluxo do lote o ignora.</p>
        </>
      )}
      {nc.observacoes && <p className="nc-texto">Observações: {nc.observacoes}</p>}
      <p className="dica">
        Decidido em {dataHoraLocal(nc.decidida_em)} por {nc.decidida_por || TRACO} · Encerrada em {dataHoraLocal(nc.encerrada_em)} por{' '}
        {nc.encerrada_por || TRACO}.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- tela

export function DetalheNaoConformidade() {
  const { id = '' } = useParams();
  const idValido = /^\d+$/.test(id);
  const carga = useCarga<DetalheNc>(
    (sinal) => (idValido ? api(`/nao-conformidades/${id}`, { sinal }) : Promise.reject(new ErroApi(404, 'Não conformidade não encontrada.'))),
    [id],
  );
  const nc = carga.dados && carga.dados.id === Number(id) ? carga.dados : null;
  const atualizar = (resposta: RespostaDecisao) => carga.definir(resposta.nc);

  return (
    <>
      <Cabecalho
        titulo={nc ? nc.numero : 'Não conformidade'}
        apoio={nc?.lote ? `OP ${nc.lote.op || TRACO} · Lote ${nc.lote.numero} · ${ondeFoi(nc)}` : undefined}
      >
        <Link to="/nao-conformidades" className="botao">
          ← Não conformidades
        </Link>
        {nc?.lote && (
          <Link to={`/lotes/${nc.lote.id}`} className="botao">
            Abrir o lote
          </Link>
        )}
      </Cabecalho>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={idValido ? carga.recarregar : undefined} />}
      {!carga.erro && !nc && <Carregando />}
      {nc && (
        <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`} aria-busy={carga.carregando}>
          <Resumo nc={nc} />
          {nc.lote?.cancelado && nc.status !== 'encerrada' ? (
            <Faixa tipo="alerta">O lote desta NC foi cancelado: não há disposição a decidir.</Faixa>
          ) : (
            <>
              {nc.status === 'aberta' && <FormDecisao key={nc.id} nc={nc} aoDecidir={atualizar} />}
              {nc.status === 'em_tratamento' && <EmTratamento nc={nc} aoReabrir={atualizar} />}
              {nc.status === 'encerrada' && <Encerrada nc={nc} />}
            </>
          )}
        </div>
      )}
    </>
  );
}
