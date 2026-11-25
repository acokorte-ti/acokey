/**
 * Página do lote (legado: /lote/<id>): dados, matéria-prima e carga de TT ligadas, etapas (cada uma abre a sua
 * página de registro), concluir a etapa atual, arquivos avulsos, importação em massa, databook, não conformidades,
 * editar/cancelar o lote e a linha do tempo.
 */
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { EnvioArquivos } from '../../componentes/EnvioArquivos';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { ModalFormulario } from '../../componentes/Modal';
import { SeloNc, SeloNcAberta, SeloRegistro, SeloSituacaoEtapa, SeloTipo } from '../../componentes/Selos';
import { api, enderecoApi, enviarArquivos, ErroApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataCurta, dataHoraLocal, haDias, inteiro, pecas, TRACO } from '../../lib/formato';
import { useSessao } from '../../lib/sessao';
import type { AnexoEtapa, EventoLote, LoteResumo, NcDoLote, RegistroEtapa, TipoLote } from '../../lib/tipos';
import { useCarga } from '../../lib/useCarga';
import { SecaoDatabookLote } from '../databooks/SecaoDatabookLote';
import { ModalRemoverAnexo, usePodeRegistrar } from './comum';
import type { EtapaDoLoteCompleta, LoteDetalheCompleto } from './tipos';

/** A linha do tempo abre com os eventos mais recentes; o resto fica atrás de um botão. */
const LIMITE_EVENTOS = 20;

/** Disposições de não conformidade conhecidas; o que não estiver aqui aparece como veio. */
const DISPOSICOES: Record<string, string> = {
  retrabalho: 'Retrabalho',
  sucata: 'Sucata',
  uso_como_esta: 'Uso como está',
  anulada: 'Anulada (erro de digitação)',
};

const STATUS_CARGA: Record<string, string> = { planejada: 'planejada', em_andamento: 'em andamento', concluida: 'concluída', cancelada: 'cancelada' };

function textoOuTraco(texto: string | null | undefined): string {
  return texto && texto.trim() ? texto : TRACO;
}

/** "19/11/2026 07:30 · Fulano": só o que o registro tiver. */
function quandoEQuem(registro: RegistroEtapa): string {
  return [registro.quando ? dataHoraLocal(registro.quando) : '', registro.responsavel.trim()].filter(Boolean).join(' · ');
}

// ---------------------------------------------------------------- dados do lote

function DadosDoLote({ dados }: { dados: LoteDetalheCompleto }) {
  const lote = dados.lote;
  const { aprovadas, total } = lote.progresso;
  const maximo = Math.max(total, 1);

  return (
    <section className="cartao" aria-labelledby="titulo-dados">
      <div className="cartao-topo">
        <h2 id="titulo-dados">Dados do lote</h2>
        <span className="acoes-linha">
          {lote.concluido ? <span className="selo selo-ok">Concluído</span> : <span className="selo selo-andamento">Em andamento</span>}
          {lote.nc_aberta && <SeloNcAberta />}
        </span>
      </div>
      <dl className="ficha ficha-linha">
        <div>
          <dt>Lote</dt>
          <dd className="mono">{lote.numero}</dd>
        </div>
        <div>
          <dt>OP</dt>
          <dd className="mono">{textoOuTraco(lote.op)}</dd>
        </div>
        <div>
          <dt>Tipo</dt>
          <dd>
            <SeloTipo tipo={lote.tipo} />
          </dd>
        </div>
        <div>
          <dt>Quantidade</dt>
          <dd>{pecas(lote.qtd)}</dd>
        </div>
        <div>
          <dt>Corrida da matéria-prima</dt>
          <dd className="mono">{textoOuTraco(lote.corrida)}</dd>
        </div>
        <div>
          <dt>Item (CODITEM)</dt>
          <dd className="mono">
            {textoOuTraco(lote.coditem)}
            {dados.desenho && (
              <>
                {' · '}
                <a href={enderecoApi(`/recursos/desenhos/${encodeURIComponent(dados.desenho.coditem)}`)} target="_blank" rel="noopener">
                  ver desenho<span className="so-leitor"> (abre em outra aba)</span>
                </a>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Criado em</dt>
          <dd>{dataHoraLocal(lote.criado_em)}</dd>
        </div>
        {lote.etapa_atual && (
          <div>
            <dt>Etapa atual</dt>
            <dd>
              {lote.etapa_atual.curto} <span className="sub-linha">· {lote.etapa_atual.setor}</span>
            </dd>
          </div>
        )}
        {!lote.concluido && lote.etapa_desde && (
          <div>
            <dt>Nesta etapa desde</dt>
            <dd>
              {dataHoraLocal(lote.etapa_desde)}
              {lote.dias_na_etapa !== null && <span className="sub-linha"> · {haDias(lote.dias_na_etapa)}</span>}
            </dd>
          </div>
        )}
      </dl>
      <div className="progresso">
        <progress className="progresso-barra" max={maximo} value={Math.min(aprovadas, maximo)} aria-label="Etapas aprovadas" />
        <span className="progresso-texto">
          {inteiro(aprovadas)} de {inteiro(total)} {total === 1 ? 'etapa aprovada' : 'etapas aprovadas'}
        </span>
      </div>
    </section>
  );
}

/** Corrida ligada ao lote em Matéria-prima (aprovada, pendente ou reprovada) e a carga de forno em que ele está. */
function Vinculos({ dados }: { dados: LoteDetalheCompleto }) {
  const { pode } = useSessao();
  const mp = dados.materia_prima;
  const carga = dados.carga_tt;
  return (
    <>
      {mp ? (
        <Faixa tipo={mp.status === 'reprovada' ? 'erro' : mp.status === 'pendente' ? 'alerta' : 'sucesso'}>
          <strong>
            Matéria-prima {mp.status === 'reprovada' ? 'REPROVADA' : mp.status === 'pendente' ? 'pendente de aprovação' : 'aprovada'}
          </strong>
          <span className="lt-faixa-linha">
            Corrida <strong className="mono">{mp.corrida}</strong> · NF <strong>{textoOuTraco(mp.nf_entrada)}</strong> · Fornecedor:{' '}
            <strong>{textoOuTraco(mp.fornecedor)}</strong> · Tipo: <strong>{textoOuTraco(mp.tipo_destino)}</strong> · QT-OK: <strong>{inteiro(mp.qt_ok)}</strong> · Refugo:{' '}
            <strong>{mp.pct_refugo.toLocaleString('pt-BR')}%</strong>
          </span>
          {mp.status === 'reprovada' && mp.obs_aprovacao && <span className="lt-faixa-linha">Motivo: {mp.obs_aprovacao}</span>}
          {pode.qualidade && (
            <span className="lt-faixa-linha">
              <Link to={`/materia-prima/${mp.id}`}>Abrir corrida</Link>
            </span>
          )}
        </Faixa>
      ) : (
        dados.lote.corrida && (
          <Faixa tipo="info">
            A corrida <strong className="mono">{dados.lote.corrida}</strong> ainda não está cadastrada em Matéria-prima. Cadastre para vincular o certificado e os
            indicadores.
          </Faixa>
        )
      )}
      {carga && (
        <Faixa tipo="info">
          <strong>
            Carga de TT{' '}
            {pode.tt ? (
              <Link to={`/cargas-tt/${carga.id}`} className="mono">
                {carga.numero}
              </Link>
            ) : (
              <span className="mono">{carga.numero}</span>
            )}{' '}
            — {STATUS_CARGA[carga.status] ?? carga.status}
          </strong>
          <span className="lt-faixa-linha">
            Este lote está na carga {carga.numero}
            {carga.data_planejada && ` (planejada para ${dataCurta(carga.data_planejada)})`}.
          </span>
        </Faixa>
      )}
    </>
  );
}

// ---------------------------------------------------------------- etapas

function ItemEtapa({ etapa, passo, loteId }: { etapa: EtapaDoLoteCompleta; passo: number; loteId: number }) {
  // Só o laboratório externo tem subdivisão (tração / Charpy); nas outras o nome da "sub" seria repetição
  const comSubdivisao = etapa.subs.some((s) => s.sub !== '');
  const nomeDaSub = (sub: string) => etapa.subs.find((s) => s.sub === sub)?.nome ?? sub;
  // Etapa que ainda vai acontecer e não tem nada lançado: só o título
  const mostrarRegistros =
    etapa.aplicavel &&
    etapa.subs.length > 0 &&
    ((etapa.situacao !== 'futura' && etapa.situacao !== 'opcional') || etapa.subs.some((s) => s.registro !== null));
  const anexos = etapa.anexos;
  const temCorpo = mostrarRegistros || anexos.length > 0 || etapa.nc_pendente !== null;

  return (
    <li className={`etapa etapa-${etapa.situacao}`}>
      <div className="etapa-topo">
        <span className="etapa-passo" aria-hidden="true">
          {passo > 0 ? passo : '–'}
        </span>
        <div className="etapa-nome">
          <h3>
            {etapa.aplicavel ? (
              <Link to={`/lotes/${loteId}/etapas/${etapa.chave}`} className="lt-link-etapa">
                {etapa.nome}
              </Link>
            ) : (
              etapa.nome
            )}
          </h3>
          <span className="sub-linha">
            {etapa.setor}
            {etapa.n_documentos > 0 && ` · ${etapa.n_documentos} documento${etapa.n_documentos > 1 ? 's' : ''}`}
          </span>
        </div>
        <SeloSituacaoEtapa situacao={etapa.situacao} />
        {etapa.aplicavel && (
          <Link to={`/lotes/${loteId}/etapas/${etapa.chave}`} className="botao botao-pequeno">
            Abrir etapa
          </Link>
        )}
      </div>
      {temCorpo && (
        <div className="etapa-corpo">
          {etapa.nc_pendente && (
            <Link to={`/nao-conformidades/${etapa.nc_pendente.id}`} className="lt-nc" title="Decidir o tratamento desta não conformidade">
              Ver NC {etapa.nc_pendente.numero} <SeloNc status={etapa.nc_pendente.status} />
            </Link>
          )}
          {mostrarRegistros && (
            <ul className="registros" aria-label={`Registros de ${etapa.curto}`}>
              {etapa.subs.map((s) => (
                <li key={s.sub} className="registro">
                  {comSubdivisao && <span className="registro-nome">{s.nome}</span>}
                  {s.registro ? (
                    <>
                      <SeloRegistro status={s.registro.status} />
                      <span className="registro-meta">{quandoEQuem(s.registro)}</span>
                    </>
                  ) : (
                    <span className="registro-meta">Sem registro ainda</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {anexos.length > 0 && (
            <div>
              <p className="etapa-rotulo">Anexos</p>
              <ul className="anexos" aria-label={`Anexos de ${etapa.curto}`}>
                {anexos.map((anexo) => (
                  <li key={anexo.id} className="anexo">
                    <a href={enderecoApi(`/anexos/${anexo.id}/arquivo`)} target="_blank" rel="noopener">
                      {anexo.nome}
                      <span className="so-leitor"> (abre em outra aba)</span>
                    </a>
                    {comSubdivisao && anexo.sub !== '' && <span className="registro-meta">{nomeDaSub(anexo.sub)}</span>}
                    {anexo.quando && <span className="registro-meta">{dataHoraLocal(anexo.quando)}</span>}
                    {anexo.apenas_registro && <span className="rotulo-discreto">só registro interno</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/** "Concluir etapa atual e liberar para a próxima". Com a matéria-prima reprovada, só quem pode aprovar libera (com motivo). */
function ConcluirEtapaAtual({ dados, aoMudar }: { dados: LoteDetalheCompleto; aoMudar: () => void }) {
  const avisos = useAvisos();
  const { pode } = useSessao();
  const podeRegistrar = usePodeRegistrar();
  const [enviando, setEnviando] = useState(false);
  const [forcar, setForcar] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [erro, setErro] = useState<string | null>(null);
  const mpReprovada = dados.materia_prima?.status === 'reprovada';
  if (dados.cursor >= dados.etapas.length) return null;

  async function avancar(comForca: boolean) {
    setEnviando(true);
    setErro(null);
    try {
      const r = await api<{ mensagem: string }>(`/lotes/${dados.lote.id}/avancar`, { metodo: 'POST', corpo: comForca ? { forcar: true, motivo: motivo.trim() } : {} });
      avisos.sucesso(r.mensagem);
      setForcar(false);
      setMotivo('');
      aoMudar();
    } catch (e) {
      if (comForca) setErro(mensagemDeErro(e));
      else avisos.erro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="lt-concluir">
      {podeRegistrar && (
        <button type="button" className="botao botao-primario" disabled={!dados.pode_avancar || enviando} onClick={() => avancar(false)}>
          Concluir etapa atual{dados.cursor_curto && ` (${dados.cursor_curto})`} e liberar para a próxima
        </button>
      )}
      {!dados.pode_avancar && <span className="dica">Disponível quando todos os registros da etapa atual estiverem APROVADOS.</span>}
      {dados.pode_avancar && mpReprovada && (
        <span className="dica texto-erro">
          A corrida está REPROVADA em Matéria-prima: o avanço fica travado.
          {pode.aprovador && (
            <>
              {' '}
              <button type="button" className="botao-link" onClick={() => setForcar(true)}>
                Avançar mesmo assim
              </button>
            </>
          )}
        </span>
      )}
      {forcar && (
        <ModalFormulario
          titulo="Avançar com a matéria-prima reprovada"
          aoFechar={() => setForcar(false)}
          aoEnviar={() => avancar(true)}
          enviando={enviando}
          erro={erro}
          rotuloEnviar="Avançar mesmo assim"
          perigo
        >
          <p>A corrida {dados.lote.corrida} está reprovada. O avanço fica registrado com o seu nome e o motivo.</p>
          <Campo rotulo="Motivo" para="forcar-motivo" obrigatorio>
            <textarea id="forcar-motivo" rows={3} value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={1000} />
          </Campo>
        </ModalFormulario>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- avulsos e importação

function Avulsos({ anexos, aoMudar }: { anexos: AnexoEtapa[]; aoMudar: () => void }) {
  const podeRegistrar = usePodeRegistrar();
  const [remover, setRemover] = useState<AnexoEtapa | null>(null);
  if (anexos.length === 0) return null;
  return (
    <section className="cartao lt-cartao-alerta" aria-labelledby="titulo-avulsos">
      <h2 id="titulo-avulsos">
        Arquivos avulsos do lote <span className="dica">({anexos.length}, não vão para o databook)</span>
      </h2>
      <p className="dica">Arquivos importados que não combinam com os prefixos do checklist ficam aqui como registro interno.</p>
      <ul className="lt-lista">
        {[...anexos].reverse().map((a) => (
          <li key={a.id}>
            <a href={enderecoApi(`/anexos/${a.id}/arquivo`)} target="_blank" rel="noopener" className="link-forte">
              {a.nome}
            </a>
            <span className="registro-meta">{dataHoraLocal(a.quando)}</span>
            {podeRegistrar && (
              <button type="button" className="botao botao-pequeno botao-perigo-contorno" onClick={() => setRemover(a)}>
                Remover
              </button>
            )}
          </li>
        ))}
      </ul>
      {remover && <ModalRemoverAnexo anexo={remover} aoFechar={() => setRemover(null)} aoRemover={() => { setRemover(null); aoMudar(); }} />}
    </section>
  );
}

function Importacao({ dados, aoMudar }: { dados: LoteDetalheCompleto; aoMudar: () => void }) {
  const avisos = useAvisos();
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [enviando, setEnviando] = useState(false);
  const concluido = dados.lote.concluido;
  const { indice, checklist } = dados.importacao;
  if (!indice) return null;

  async function importar() {
    setEnviando(true);
    try {
      const r = await enviarArquivos<{ importados: string[]; avulsos: string[]; ignorados: string[]; avancou: number }>(`/lotes/${dados.lote.id}/importar`, { arquivos });
      if (r.importados.length) avisos.sucesso(`${r.importados.length} documento(s) importado(s): ${r.importados.join(' · ')}`);
      if (r.avulsos.length) avisos.info(`${r.avulsos.length} arquivo(s) sem prefixo do checklist ficaram como avulsos do lote (não vão para o databook): ${r.avulsos.join(' · ')}`);
      if (r.ignorados.length) avisos.erro(`Não aceitos: ${r.ignorados.join(' ')}`);
      setArquivos([]);
      aoMudar();
    } catch (e) {
      avisos.erro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <details className={`cartao recolhivel ${concluido ? 'lt-cartao-alerta' : ''}`}>
      <summary>
        <strong>Importar / substituir documentos do lote</strong>{' '}
        <span className="dica">
          {concluido
            ? '— lote já concluído: adicione novos arquivos e gere o databook novamente'
            : '— envia todos os PDFs numerados de uma vez e aprova as etapas automaticamente'}
        </span>
      </summary>
      <p className="dica">
        Selecione os arquivos com prefixo numérico seguindo o checklist <strong>{indice}</strong> para este tipo <strong>{dados.lote.tipo}</strong>. Cada arquivo é anexado à
        etapa correspondente
        {!concluido && ' e marcado como APROVADO'}
        {!concluido && indice === 'PIN/BOX' && ', inclusive tamboreamento e usinagem em processo (etapas internas sem documento próprio)'}.{' '}
        {dados.lote.tipo === 'ARK' && 'As etapas de dureza, usinagem em processo, tamboreamento e tração não fazem parte do fluxo ARK e são puladas automaticamente. '}
        {concluido ? 'Depois de importar, gere o databook de novo (nova revisão).' : 'O lote avança automaticamente até onde todas as etapas estiverem concluídas.'}
      </p>
      <div className="tabela-rolagem">
        <table className="tabela tabela-estreita">
          <caption className="so-leitor">Prefixos do checklist de importação</caption>
          <thead>
            <tr>
              <th scope="col">Prefixo</th>
              <th scope="col">Etapa que aprova</th>
              <th scope="col">Título do documento</th>
            </tr>
          </thead>
          <tbody>
            {checklist.map((linha) => (
              <tr key={`${linha.prefixo}-${linha.etapa}-${linha.sub}`}>
                <td className="mono">
                  <strong>{linha.prefixo}</strong>
                </td>
                <td>{linha.curto}</td>
                <td className="sub-linha">{linha.titulo}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <EnvioArquivos arquivos={arquivos} aoMudar={setArquivos} aceita=".pdf,.jpg,.jpeg,.png" rotulo="Arquivos do lote" dica="Ex.: 1-Certificado MP.pdf, 3-Relatório de dureza.pdf" desabilitado={enviando} />
      <div className="acoes">
        <button type="button" className="botao botao-primario" disabled={arquivos.length === 0 || enviando} onClick={importar}>
          {enviando ? 'Importando e aprovando etapas…' : concluido ? 'Importar / substituir arquivos' : 'Importar e aprovar etapas'}
        </button>
      </div>
    </details>
  );
}

// ---------------------------------------------------------------- editar e cancelar o lote

interface FormLote {
  op: string;
  numero: string;
  tipo: TipoLote;
  qtd: string;
  coditem: string;
  motivo: string;
}

function EditarCancelar({ dados, aoMudar }: { dados: LoteDetalheCompleto; aoMudar: () => void }) {
  const avisos = useAvisos();
  const navegar = useNavigate();
  const { pode } = useSessao();
  const [modal, setModal] = useState<'editar' | 'cancelar' | null>(null);
  const [form, setForm] = useState<FormLote | null>(null);
  const [motivoCancelar, setMotivoCancelar] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const lote: LoteResumo = dados.lote;
  if (!(pode.qualidade || pode.pcp)) return null;
  const autorizado = !dados.tem_dados || pode.aprovador || pode.admin;

  function abrirEditar() {
    setForm({ op: lote.op, numero: lote.numero, tipo: lote.tipo, qtd: String(lote.qtd), coditem: lote.coditem ?? '', motivo: '' });
    setErro(null);
    setModal('editar');
  }

  async function salvar() {
    if (!form) return;
    setEnviando(true);
    setErro(null);
    try {
      const r = await api<{ mudou: boolean }>(`/lotes/${lote.id}`, {
        metodo: 'PATCH',
        corpo: { op: form.op.trim(), numero: form.numero.trim(), tipo: form.tipo, qtd: Number(form.qtd), coditem: form.coditem.trim(), motivo: form.motivo.trim() },
      });
      avisos.sucesso(r.mudou ? 'Dados do lote atualizados.' : 'Nada mudou.');
      setModal(null);
      aoMudar();
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  async function cancelar() {
    setEnviando(true);
    setErro(null);
    try {
      const r = await api<{ mensagem: string }>(`/lotes/${lote.id}/cancelar`, { metodo: 'POST', corpo: { motivo: motivoCancelar.trim() } });
      avisos.sucesso(r.mensagem);
      navegar('/');
    } catch (e) {
      setErro(mensagemDeErro(e));
      setEnviando(false);
    }
  }

  return (
    <section className="cartao" aria-labelledby="titulo-editar">
      <h2 id="titulo-editar">Editar ou cancelar o lote</h2>
      <p className="dica">
        {dados.tem_dados
          ? 'Este lote já tem registros ou anexos: editar e cancelar ficam com quem pode aprovar (ou o administrador), com o motivo escrito.'
          : 'Lote sem registros: quem tem Qualidade ou PCP pode editar ou cancelar.'}
      </p>
      <div className="acoes">
        <button type="button" className="botao" onClick={abrirEditar} disabled={!autorizado}>
          Editar dados do lote
        </button>
        <button
          type="button"
          className="botao botao-perigo-contorno"
          onClick={() => {
            setMotivoCancelar('');
            setErro(null);
            setModal('cancelar');
          }}
          disabled={!autorizado || dados.databook_enviado}
        >
          Cancelar lote
        </button>
        {dados.databook_enviado && <span className="dica">O databook desta OP/tipo já foi enviado ao cliente: o lote não pode ser cancelado.</span>}
      </div>

      {modal === 'editar' && form && (
        <ModalFormulario titulo={`Editar lote ${lote.numero}`} aoFechar={() => setModal(null)} aoEnviar={salvar} enviando={enviando} erro={erro} rotuloEnviar="Salvar alterações">
          <div className="linha-campos">
            <Campo rotulo="Nº da OP" para="ed-op" obrigatorio>
              <input id="ed-op" type="text" value={form.op} onChange={(e) => setForm({ ...form, op: e.target.value })} maxLength={20} />
            </Campo>
            <Campo rotulo="Nº do lote" para="ed-numero" obrigatorio>
              <input id="ed-numero" type="text" value={form.numero} onChange={(e) => setForm({ ...form, numero: e.target.value })} maxLength={40} />
            </Campo>
            <Campo rotulo="Formato" para="ed-tipo">
              <select id="ed-tipo" value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value as TipoLote })}>
                <option>PIN</option>
                <option>BOX</option>
                <option>ARK</option>
              </select>
            </Campo>
            <Campo rotulo="Quantidade" para="ed-qtd" obrigatorio>
              <input id="ed-qtd" type="number" min={1} value={form.qtd} onChange={(e) => setForm({ ...form, qtd: e.target.value })} />
            </Campo>
            <Campo rotulo="Código do item" para="ed-coditem">
              <input id="ed-coditem" type="text" value={form.coditem} onChange={(e) => setForm({ ...form, coditem: e.target.value })} maxLength={40} />
            </Campo>
          </div>
          {dados.tem_dados && (
            <Campo rotulo="Motivo da alteração" para="ed-motivo" obrigatorio dica="Fica na auditoria e na linha do tempo do lote.">
              <textarea id="ed-motivo" rows={2} value={form.motivo} onChange={(e) => setForm({ ...form, motivo: e.target.value })} maxLength={1000} />
            </Campo>
          )}
        </ModalFormulario>
      )}
      {modal === 'cancelar' && (
        <ModalFormulario titulo={`Cancelar lote ${lote.numero}`} aoFechar={() => setModal(null)} aoEnviar={cancelar} enviando={enviando} erro={erro} rotuloEnviar="Cancelar lote" perigo>
          <p>
            O lote sai do painel, mas continua guardado no sistema com os registros, anexos e a auditoria. O número <strong className="mono">{lote.numero}</strong> fica livre para um
            lote novo.
          </p>
          <Campo rotulo="Motivo" para="cancelar-motivo" obrigatorio={dados.tem_dados}>
            <textarea id="cancelar-motivo" rows={3} value={motivoCancelar} onChange={(e) => setMotivoCancelar(e.target.value)} maxLength={1000} />
          </Campo>
        </ModalFormulario>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- não conformidades e linha do tempo

function NaoConformidades({ ncs, etapas }: { ncs: NcDoLote[]; etapas: EtapaDoLoteCompleta[] }) {
  /** "Tração / Charpy · Charpy": a etapa e, quando houver, a subdivisão em que a NC foi aberta. */
  function ondeFoi(nc: NcDoLote): string {
    const etapa = etapas.find((e) => e.chave === nc.etapa);
    if (!etapa) return nc.sub ? `${nc.etapa} · ${nc.sub}` : nc.etapa;
    if (!nc.sub) return etapa.curto;
    return `${etapa.curto} · ${etapa.subs.find((s) => s.sub === nc.sub)?.nome ?? nc.sub}`;
  }

  function disposicao(nc: NcDoLote) {
    if (nc.disposicao) return DISPOSICOES[nc.disposicao] ?? nc.disposicao;
    return nc.status === 'encerrada' ? TRACO : <span className="automatico-vazio">a decidir</span>;
  }

  return (
    <section className="cartao" aria-labelledby="titulo-ncs">
      <h2 id="titulo-ncs">Não conformidades</h2>
      {ncs.length === 0 ? (
        <p className="dica">Nenhuma não conformidade registrada neste lote.</p>
      ) : (
        <div className="tabela-rolagem">
          <table className="tabela">
            <caption className="so-leitor">Não conformidades do lote</caption>
            <thead>
              <tr>
                <th scope="col">Número</th>
                <th scope="col">Etapa</th>
                <th scope="col">Situação</th>
                <th scope="col">Disposição</th>
              </tr>
            </thead>
            <tbody>
              {ncs.map((nc) => (
                <tr key={nc.id}>
                  <td className="mono">
                    <Link to={`/nao-conformidades/${nc.id}`} className="link-forte">
                      {nc.numero}
                    </Link>
                  </td>
                  <td>{ondeFoi(nc)}</td>
                  <td>
                    <SeloNc status={nc.status} />
                  </td>
                  <td>{disposicao(nc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LinhaDoTempo({ eventos }: { eventos: EventoLote[] }) {
  const [verTodos, setVerTodos] = useState(false);
  const visiveis = verTodos ? eventos : eventos.slice(0, LIMITE_EVENTOS);

  return (
    <section className="cartao" aria-labelledby="titulo-eventos">
      <h2 id="titulo-eventos">Linha do tempo</h2>
      {eventos.length === 0 ? (
        <p className="dica">Nenhum evento registrado neste lote.</p>
      ) : (
        <>
          <p className="dica">Do mais recente para o mais antigo.</p>
          <ol className="linha-tempo">
            {visiveis.map((evento, indice) => (
              // Os eventos não têm id; a lista só muda de tamanho (nunca de ordem), então a posição serve de chave
              <li key={indice}>
                <span className="linha-tempo-quando">{dataHoraLocal(evento.quando)}</span>
                <span className="linha-tempo-texto">{evento.texto}</span>
              </li>
            ))}
          </ol>
          {eventos.length > LIMITE_EVENTOS && (
            <button type="button" className="botao-link ver-todas" onClick={() => setVerTodos((v) => !v)}>
              {verTodos ? `Mostrar só os ${LIMITE_EVENTOS} mais recentes` : `Mostrar todos os ${inteiro(eventos.length)}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- tela

export function PaginaLote() {
  const { id = '' } = useParams();
  const idValido = /^\d+$/.test(id);
  const podeRegistrar = usePodeRegistrar();
  const carga = useCarga<LoteDetalheCompleto>(
    (sinal) => (idValido ? api(`/lotes/${id}`, { sinal }) : Promise.reject(new ErroApi(404, 'Lote não encontrado.'))),
    [id],
  );
  // Ao trocar de lote, os dados do anterior ficam na memória até o novo chegar: não mostra um lote no endereço de outro
  const dados = carga.dados && carga.dados.lote.id === Number(id) ? carga.dados : null;
  // A etapa opcional (ex.: dureza no ARK) não entra na numeração: o lote não depende dela
  const aplicaveis = dados ? dados.etapas.filter((e) => e.aplicavel && !e.opcional) : [];

  return (
    <>
      <Cabecalho titulo={dados ? `Lote ${dados.lote.numero}` : 'Lote'} apoio={dados ? `OP ${textoOuTraco(dados.lote.op)}` : undefined}>
        <Link to="/" className="botao">
          ← Voltar ao painel
        </Link>
        {dados && (
          <Link to={`/lotes/${id}/mapa`} className="botao">
            Mapa do lote
          </Link>
        )}
        <Link to="/dashboard" className="botao botao-fantasma">
          Dashboard
        </Link>
      </Cabecalho>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={idValido ? carga.recarregar : undefined} />}
      {!carga.erro && !dados && <Carregando />}

      {dados && (
        <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`} aria-busy={carga.carregando}>
          <DadosDoLote dados={dados} />
          <Vinculos dados={dados} />

          <section aria-labelledby="titulo-etapas">
            <h2 id="titulo-etapas">Etapas do processo</h2>
            <p className="dica">Clique numa etapa para registrar, anexar documentos ou aprovar.</p>
            <ol className="etapas">
              {dados.etapas.map((etapa) => (
                <ItemEtapa key={etapa.chave} etapa={etapa} loteId={dados.lote.id} passo={aplicaveis.indexOf(etapa) + 1} />
              ))}
            </ol>
            <ConcluirEtapaAtual dados={dados} aoMudar={carga.recarregar} />
          </section>

          {dados.laser_disponivel && (
            <p className="dica">
              <a href={enderecoApi(`/lotes/${dados.lote.id}/laser.csv`)} className="botao botao-pequeno">
                Baixar arquivo do laser (CSV)
              </a>{' '}
              Códigos de gravação de cada peça, para a máquina laser.
            </p>
          )}

          <Avulsos anexos={dados.avulsos} aoMudar={carga.recarregar} />
          {podeRegistrar && <Importacao dados={dados} aoMudar={carga.recarregar} />}
          <SecaoDatabookLote loteId={dados.lote.id} concluido={dados.lote.concluido} />
          <NaoConformidades ncs={dados.ncs} etapas={dados.etapas} />
          <EditarCancelar dados={dados} aoMudar={carga.recarregar} />
          <LinhaDoTempo eventos={dados.eventos} />
        </div>
      )}
    </>
  );
}
