/**
 * Página de uma etapa do lote (legado: /lote/<id>/etapa/<key>): registros, documentos anexados, aprovação com base no
 * documento, fotos só de registro interno, envios a prestador ligados à etapa e o formulário detalhado.
 */
import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { EnvioArquivos } from '../../componentes/EnvioArquivos';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { SeloNc, SeloRegistro, SeloSituacaoEtapa, SeloTipo } from '../../componentes/Selos';
import { api, enderecoApi, enviarArquivos, ErroApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataCurta, dataHoraLocal } from '../../lib/formato';
import { useSessao } from '../../lib/sessao';
import type { AnexoEtapa, SituacaoEtapa } from '../../lib/tipos';
import { useCarga } from '../../lib/useCarga';
import { FormularioDetalhado } from './Formularios';
import { ModalRemoverAnexo, usePodeRegistrar } from './comum';
import type { PaginaEtapaDados, RegistroDaEtapa } from './tipos';

const VIA: Record<string, string> = {
  formulario: 'formulário detalhado',
  documento_anexado: 'aprovado pelo documento anexado',
  sem_documento: 'concluída sem documento próprio',
  importacao: 'importação de documentos',
  sistema: 'relatório gerado pelo sistema',
};

/** Atalhos para os relatórios gerados pelo próprio sistema (no antigo, botões amarelos dentro da etapa). */
function RelatorioDoSistema({ dados }: { dados: PaginaEtapaDados }) {
  const { pode } = useSessao();
  const id = dados.lote.id;
  let atalho: { para: string; titulo: string; texto: string } | null = null;
  if (dados.etapa.chave === 'dureza' && pode.qualidade && dados.lote.tipo !== 'ARK') {
    atalho = { para: `/relatorios/dureza?lote=${id}`, titulo: 'Gerar RIP-35 direto no sistema', texto: 'Formulário com cálculo automático do status pela especificação, já com a imagem dos pontos de medição do tipo da peça.' };
  } else if (dados.etapa.chave === 'trat_termico' && pode.tt) {
    atalho = { para: `/relatorios/tt?lote=${id}`, titulo: 'Gerar relatório de TT direto no sistema', texto: 'Permite incluir mais de uma OP no mesmo tratamento (quando o forno trata lotes juntos), com os gráficos do forno.' };
  } else if (dados.etapa.chave === 'visual' && pode.qualidade) {
    atalho = { para: `/relatorios/visual?lote=${id}`, titulo: 'Gerar relatório visual direto no sistema', texto: 'Observações padrão já preenchidas, fotos (geral/peça/laser) e prévia dos códigos de rastreabilidade a laser.' };
  }
  if (!atalho) return null;
  return (
    <div className="lt-atalho">
      <div>
        <strong>{atalho.titulo}</strong>
        <p className="dica">{atalho.texto}</p>
      </div>
      <Link to={atalho.para} className="botao">
        Gerar relatório pelo sistema
      </Link>
    </div>
  );
}

function Envios({ dados }: { dados: PaginaEtapaDados }) {
  if (dados.envios.length === 0) return null;
  return (
    <section className="cartao" aria-labelledby="titulo-envios">
      <h2 id="titulo-envios">Envios a prestador externo nesta etapa</h2>
      <ul className="lt-lista">
        {dados.envios.map((e) => (
          <li key={e.id}>
            <span className={`selo ${e.status === 'enviado' ? 'selo-alerta' : 'selo-ok'}`}>{e.status === 'enviado' ? 'Enviado' : 'Retornado'}</span>
            <Link to={`/envios/${e.id}`} className="link-forte mono">
              {e.numero}
            </Link>
            <span>
              <strong>{e.prestador}</strong> ({e.tipo_servico})
            </span>
            <span className="registro-meta">
              enviado em {dataCurta(e.data_envio)}
              {e.responsavel && ` por ${e.responsavel}`}
              {e.data_retorno && ` · retornado em ${dataCurta(e.data_retorno)}`}
            </span>
            {e.status === 'enviado' && e.laudo_lancado && <span className="selo selo-ok">laudo já lançado</span>}
          </li>
        ))}
      </ul>
      <p className="dica">
        Quando o laudo do prestador for lançado nesta etapa, lembre de marcar o envio como <strong>retornado</strong> em <Link to="/envios">Envios a prestador</Link>.
      </p>
    </section>
  );
}

function Registros({ dados }: { dados: PaginaEtapaDados }) {
  const varios = dados.etapa.subs.length > 1;
  const lista = varios ? dados.registros.filter((r) => r.sub === dados.sub) : dados.registros;
  return (
    <section className="cartao" aria-labelledby="titulo-registros">
      <h2 id="titulo-registros">Registros desta etapa{varios && ` · ${dados.etapa.subs.find((s) => s.sub === dados.sub)?.nome ?? ''}`}</h2>
      {lista.length === 0 ? (
        <p className="dica">Nenhum registro ainda.</p>
      ) : (
        <ul className="lt-lista">
          {lista.map((r) => (
            <ItemRegistro key={r.id} registro={r} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ItemRegistro({ registro: r }: { registro: RegistroDaEtapa }) {
  return (
    <li className={r.anulado ? 'lt-anulado' : undefined}>
      <SeloRegistro status={r.status} />
      {r.anulado && <span className="selo selo-inativo" title={r.anulado_motivo}>Anulado</span>}
      <span>{dataHoraLocal(r.quando)}</span>
      <span>{r.responsavel || '—'}</span>
      {VIA[r.via] && <span className="registro-meta">{VIA[r.via]}</span>}
      {r.nc && (
        <Link to={`/nao-conformidades/${r.nc.id}`} className="lt-nc">
          NC {r.nc.numero} <SeloNc status={r.nc.status} />
        </Link>
      )}
      {r.tem_relatorio && (
        <a href={enderecoApi(`/registros/${r.id}/pdf`)} target="_blank" rel="noopener" className="link-forte">
          Abrir relatório PDF<span className="so-leitor"> (abre em outra aba)</span>
        </a>
      )}
      {r.anulado && r.anulado_motivo && <span className="registro-meta">Motivo da anulação: {r.anulado_motivo}</span>}
    </li>
  );
}

function ListaAnexos({
  anexos,
  dados,
  podeRegistrar,
  aoRemover,
}: {
  anexos: AnexoEtapa[];
  dados: PaginaEtapaDados;
  podeRegistrar: boolean;
  aoRemover: (anexo: AnexoEtapa) => void;
}) {
  const { pode } = useSessao();
  const nomeSub = (sub: string) => dados.etapa.subs.find((s) => s.sub === sub)?.nome ?? '';
  return (
    <ul className="lt-lista">
      {anexos.map((a) => (
        <li key={a.id}>
          <a href={enderecoApi(`/anexos/${a.id}/arquivo`)} target="_blank" rel="noopener" className="link-forte">
            {a.nome}
            <span className="so-leitor"> (abre em outra aba)</span>
          </a>
          {a.sub && dados.etapa.subs.length > 1 && <span className="registro-meta">{nomeSub(a.sub)}</span>}
          <span className="registro-meta">{dataHoraLocal(a.quando)}</span>
          {dados.etapa.chave === 'dim_final' && pode.qualidade && a.nome.toLowerCase().endsWith('.pdf') && (
            <Link to={`/verificar-dimensional?anexo=${a.id}`} className="botao botao-pequeno" title="Checar cotas fora da tolerância (RIP-33A)">
              Verificar cotas
            </Link>
          )}
          {podeRegistrar && (
            <button type="button" className="botao botao-pequeno botao-perigo-contorno" onClick={() => aoRemover(a)}>
              Remover
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Anexar documentos, aprovar com base neles, importar o certificado da corrida ou marcar a etapa como concluída. */
function Documentos({ dados, aoMudar }: { dados: PaginaEtapaDados; aoMudar: () => void }) {
  const avisos = useAvisos();
  const podeRegistrar = usePodeRegistrar();
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [enviando, setEnviando] = useState(false);
  const [remover, setRemover] = useState<AnexoEtapa | null>(null);
  const [corrida, setCorrida] = useState(dados.lote.corrida ?? '');
  const [prestador, setPrestador] = useState('');
  const [obs, setObs] = useState('');
  const { etapa, lote } = dados;
  const temDocumento = dados.anexos.length > 0;
  const internaSemDocumento = !temDocumento && !etapa.exige_anexo && (etapa.formulario === 'simples' || etapa.formulario === 'dim');
  const opcoesPrestador = etapa.chave === 'receb_mp' ? dados.fornecedores_mp.map((f) => ({ codigo: f.codigo, texto: `${f.codigo} — ${f.razao_social}${f.materiais ? ` (${f.materiais})` : ''}` })) : dados.prestadores.map((p) => ({ codigo: p.codigo, texto: `${p.codigo} — ${p.razao_social}` }));
  const etapaComPrestador = ['lab_ext', 'fosfato', 'lp', 'trat_termico', 'receb_mp'].includes(etapa.chave);

  async function anexar() {
    if (arquivos.length === 0) return;
    setEnviando(true);
    try {
      const r = await enviarArquivos<{ salvos: AnexoEtapa[]; ignorados: string[] }>(`/lotes/${lote.id}/etapas/${etapa.chave}/anexos`, { arquivos, sub: dados.sub });
      avisos.sucesso(`${r.salvos.length} arquivo(s) anexado(s).`);
      if (r.ignorados.length) avisos.erro(`Não anexado(s): ${r.ignorados.join(' ')}`);
      setArquivos([]);
      aoMudar();
    } catch (e) {
      avisos.erro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  async function aprovar() {
    setEnviando(true);
    try {
      const r = await api<{ aprovados: string[]; mensagem: string; avancou: number }>(`/lotes/${lote.id}/etapas/${etapa.chave}/aprovar-por-anexo`, {
        metodo: 'POST',
        corpo: { corrida: etapa.chave === 'receb_mp' ? corrida : '', prestador, obs },
      });
      avisos.sucesso(r.avancou > 0 ? `${r.mensagem} O lote avançou ${r.avancou} etapa(s).` : r.mensagem);
      setObs('');
      aoMudar();
    } catch (e) {
      avisos.erro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  async function importarCertificado() {
    setEnviando(true);
    try {
      const r = await api<{ mensagem: string }>(`/lotes/${lote.id}/importar-certificado-mp`, { metodo: 'POST' });
      avisos.sucesso(r.mensagem);
      aoMudar();
    } catch (e) {
      avisos.erro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="cartao" aria-labelledby="titulo-documentos">
      <h2 id="titulo-documentos">Arquivos anexados à etapa (entram no databook)</h2>
      {temDocumento ? (
        <ListaAnexos anexos={dados.anexos} dados={dados} podeRegistrar={podeRegistrar} aoRemover={setRemover} />
      ) : (
        <p className="dica">Nenhum anexo nesta etapa{etapa.exige_anexo && ' (é obrigatório anexar para aprovar)'}.</p>
      )}

      {podeRegistrar && etapa.chave === 'receb_mp' && dados.certificados_corrida > 0 && !temDocumento && (
        <Faixa tipo="info">
          <strong>
            A corrida {lote.corrida} já tem {dados.certificados_corrida} certificado(s) anexado(s) em Matéria-prima.
          </strong>{' '}
          Use o atalho para copiar o certificado direto para esta etapa, sem precisar enviar de novo.
          <div className="lt-faixa-acao">
            <button type="button" className="botao" onClick={importarCertificado} disabled={enviando}>
              Importar certificado da corrida
            </button>
          </div>
        </Faixa>
      )}

      {podeRegistrar && (
        <div className="lt-envio">
          <EnvioArquivos arquivos={arquivos} aoMudar={setArquivos} aceita=".pdf,.jpg,.jpeg,.png" dica="PDF, JPG ou PNG, até 25 MB cada. Dá para escolher vários de uma vez." rotulo="Anexar documentos" desabilitado={enviando} />
          {arquivos.length > 0 && (
            <button type="button" className="botao" onClick={anexar} disabled={enviando}>
              {enviando ? 'Enviando…' : `Anexar ${arquivos.length} arquivo(s)`}
            </button>
          )}
        </div>
      )}

      {podeRegistrar && (temDocumento || internaSemDocumento) && (
        <div className={`lt-aprovar ${temDocumento ? '' : 'lt-aprovar-neutro'}`}>
          {temDocumento ? (
            <p>
              <strong>Aprovar etapa:</strong> como já tem documento anexado, você pode aprovar esta etapa sem preencher o formulário detalhado.
              {!etapa.liberada && ' O lote avança automaticamente até esta etapa.'}
              {etapa.subs.length > 1 && ' Aprova todos os ensaios da etapa que ainda não estão aprovados.'}
            </p>
          ) : (
            <p>
              <strong>Operação interna sem documento próprio:</strong> você pode marcar esta etapa como concluída diretamente.
            </p>
          )}
          <div className="form-grade">
            {etapa.chave === 'receb_mp' && (
              <Campo rotulo="Corrida nº (opcional)" para="ap-corrida">
                <input id="ap-corrida" type="text" value={corrida} onChange={(e) => setCorrida(e.target.value)} list="lt-corridas-ap" autoComplete="off" />
                <datalist id="lt-corridas-ap">
                  {dados.corridas_mp.map((c) => (
                    <option key={`${c.corrida}-${c.nf_entrada}`} value={c.corrida}>
                      {[c.tipo_destino, c.nf_entrada && `NF ${c.nf_entrada}`, c.fornecedor].filter(Boolean).join(' · ')}
                    </option>
                  ))}
                </datalist>
              </Campo>
            )}
            {temDocumento && etapaComPrestador && opcoesPrestador.length > 0 && (
              <Campo rotulo={`${dados.rotulo_prestador} (do cadastro)`} para="ap-prestador" classe="col-2">
                <select id="ap-prestador" value={prestador} onChange={(e) => setPrestador(e.target.value)}>
                  <option value="">— não informar —</option>
                  {opcoesPrestador.map((p) => (
                    <option key={p.codigo} value={p.codigo}>
                      {p.texto}
                    </option>
                  ))}
                </select>
              </Campo>
            )}
            <Campo rotulo="Observação (opcional)" para="ap-obs" classe={etapa.chave === 'receb_mp' || (temDocumento && etapaComPrestador && opcoesPrestador.length > 0) ? 'col-1' : 'col-4'}>
              <input id="ap-obs" type="text" value={obs} onChange={(e) => setObs(e.target.value)} />
            </Campo>
          </div>
          {temDocumento && etapaComPrestador && opcoesPrestador.length === 0 && etapa.chave !== 'receb_mp' && (
            <p className="dica">Nenhum prestador cadastrado para este tipo de serviço. Cadastre em Cadastros › Prestadores se quiser identificar a empresa aqui.</p>
          )}
          <div className="acoes">
            <button type="button" className={`botao ${temDocumento ? 'botao-primario' : ''}`} onClick={aprovar} disabled={enviando}>
              {temDocumento ? 'Aprovar etapa com base no documento anexado' : 'Marcar etapa como concluída'}
            </button>
            <span className="dica">Registrado em nome de {dados.padroes.usuario}.</span>
          </div>
        </div>
      )}
      {remover && <ModalRemoverAnexo anexo={remover} aoFechar={() => setRemover(null)} aoRemover={() => { setRemover(null); aoMudar(); }} />}
    </section>
  );
}

/** Fotos só para registro interno (evidência da inspeção visual do ARK): não entram no databook. */
function FotosRegistro({ dados, aoMudar }: { dados: PaginaEtapaDados; aoMudar: () => void }) {
  const avisos = useAvisos();
  const podeRegistrar = usePodeRegistrar();
  const [fotos, setFotos] = useState<File[]>([]);
  const [enviando, setEnviando] = useState(false);
  const [remover, setRemover] = useState<AnexoEtapa | null>(null);

  async function enviar() {
    setEnviando(true);
    try {
      const r = await enviarArquivos<{ salvos: AnexoEtapa[]; ignorados: string[] }>(`/lotes/${dados.lote.id}/etapas/${dados.etapa.chave}/fotos-registro`, { fotos });
      avisos.sucesso(`${r.salvos.length} foto(s) adicionada(s) para registro interno (não aparecem no databook).`);
      if (r.ignorados.length) avisos.erro(`Não adicionada(s): ${r.ignorados.join(' ')}`);
      setFotos([]);
      aoMudar();
    } catch (e) {
      avisos.erro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="cartao lt-cartao-alerta" aria-labelledby="titulo-fotos">
      <h2 id="titulo-fotos">Fotos do visual (apenas para registro interno)</h2>
      <p className="dica">
        Estas fotos ficam salvas aqui como histórico/evidência da inspeção visual. <strong>Não</strong> entram no databook enviado ao cliente.
      </p>
      {dados.fotos_registro.length === 0 ? (
        <p className="dica">Nenhuma foto adicionada ainda.</p>
      ) : (
        <ul className="lt-fotos">
          {dados.fotos_registro.map((f) => (
            <li key={f.id}>
              <a href={enderecoApi(`/anexos/${f.id}/arquivo`)} target="_blank" rel="noopener">
                <img src={enderecoApi(`/anexos/${f.id}/arquivo`)} alt={f.nome} loading="lazy" />
              </a>
              <span className="lt-foto-nome" title={f.nome}>
                {f.nome}
              </span>
              <span className="registro-meta">{dataHoraLocal(f.quando)}</span>
              {podeRegistrar && (
                <button type="button" className="botao botao-pequeno botao-perigo-contorno" onClick={() => setRemover(f)}>
                  Remover
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {podeRegistrar && (
        <div className="lt-envio">
          <EnvioArquivos arquivos={fotos} aoMudar={setFotos} aceita=".jpg,.jpeg,.png" rotulo="Adicionar fotos" dica="JPG ou PNG. Duplo clique, arraste ou cole com Ctrl+V." desabilitado={enviando} />
          {fotos.length > 0 && (
            <button type="button" className="botao" onClick={enviar} disabled={enviando}>
              {enviando ? 'Enviando…' : 'Adicionar fotos para registro (não vão para o databook)'}
            </button>
          )}
        </div>
      )}
      {remover && <ModalRemoverAnexo anexo={remover} aoFechar={() => setRemover(null)} aoRemover={() => { setRemover(null); aoMudar(); }} />}
    </section>
  );
}

/** "Concluir etapa e liberar a próxima" direto da etapa (o mesmo botão da página do lote). */
function ConcluirEtapa({ dados, aoMudar }: { dados: PaginaEtapaDados; aoMudar: () => void }) {
  const avisos = useAvisos();
  const [enviando, setEnviando] = useState(false);
  async function concluir() {
    setEnviando(true);
    try {
      const r = await api<{ mensagem: string }>(`/lotes/${dados.lote.id}/avancar`, { metodo: 'POST', corpo: {} });
      avisos.sucesso(r.mensagem);
      aoMudar();
    } catch (e) {
      avisos.erro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }
  return (
    <Faixa tipo="sucesso">
      Todos os registros desta etapa estão aprovados.
      <div className="lt-faixa-acao">
        <button type="button" className="botao botao-primario" onClick={concluir} disabled={enviando}>
          Concluir etapa e liberar a próxima
        </button>
      </div>
    </Faixa>
  );
}

export function PaginaEtapa() {
  const { id = '', chave = '' } = useParams();
  const [busca] = useSearchParams();
  const sub = busca.get('sub') ?? '';
  const podeRegistrar = usePodeRegistrar();
  const idValido = /^\d+$/.test(id);
  const carga = useCarga<PaginaEtapaDados>(
    (sinal) =>
      idValido
        ? api(`/lotes/${id}/etapas/${encodeURIComponent(chave)}${sub ? `?sub=${encodeURIComponent(sub)}` : ''}`, { sinal })
        : Promise.reject(new ErroApi(404, 'Lote não encontrado.')),
    [id, chave, sub],
  );
  const dados = carga.dados && carga.dados.lote.id === Number(id) && carga.dados.etapa.chave === chave ? carga.dados : null;
  const versao = dados ? `${dados.etapa.chave}-${dados.sub}-${dados.registros.length}` : '';

  return (
    <>
      <Cabecalho
        titulo={dados ? dados.etapa.nome : 'Etapa'}
        apoio={
          dados ? (
            <>
              {dados.etapa.setor} · OP {dados.lote.op} · Lote <span className="mono">{dados.lote.numero}</span> <SeloTipo tipo={dados.lote.tipo} />
            </>
          ) : undefined
        }
      >
        <Link to={`/lotes/${id}`} className="botao">
          ← Voltar ao lote
        </Link>
        <Link to="/" className="botao botao-fantasma">
          Painel
        </Link>
      </Cabecalho>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={idValido ? carga.recarregar : undefined} />}
      {!carga.erro && !dados && <Carregando />}

      {dados && (
        <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`} aria-busy={carga.carregando}>
          <div className="lt-topo-etapa">
            <SeloSituacaoEtapa situacao={dados.etapa.situacao as SituacaoEtapa} />
            {dados.etapa.relatorio && <span className="registro-meta">Relatório: {dados.etapa.relatorio}</span>}
          </div>

          {!dados.etapa.aplicavel ? (
            <Faixa tipo="alerta">Esta etapa não faz parte do fluxo de lotes {dados.lote.tipo}: ela é pulada automaticamente.</Faixa>
          ) : (
            <>
              {dados.etapa.subs.length > 1 && (
                <nav className="abas" aria-label="Ensaios da etapa">
                  {dados.etapa.subs.map((s) => (
                    <Link
                      key={s.sub}
                      to={{ search: `?sub=${s.sub}` }}
                      replace
                      className={`aba ${s.sub === dados.sub ? 'aba-atual' : ''}`}
                      aria-current={s.sub === dados.sub ? 'page' : undefined}
                    >
                      {s.nome} {s.status && <SeloRegistro status={s.status} />}
                    </Link>
                  ))}
                </nav>
              )}
              {!podeRegistrar && <Faixa tipo="info">Seu usuário só consulta: registrar, anexar e aprovar ficam com Qualidade, PCP e Produção.</Faixa>}
              <RelatorioDoSistema dados={dados} />
              {dados.pode_avancar && podeRegistrar && <ConcluirEtapa dados={dados} aoMudar={carga.recarregar} />}
              <Envios dados={dados} />
              <Registros dados={dados} />
              <Documentos key={`doc-${versao}-${dados.anexos.length}`} dados={dados} aoMudar={carga.recarregar} />
              {dados.etapa.chave === 'visual' && dados.lote.tipo === 'ARK' && <FotosRegistro dados={dados} aoMudar={carga.recarregar} />}

              {podeRegistrar &&
                (dados.etapa.liberada ? (
                  dados.anexos.length > 0 ? (
                    <details className="cartao lt-detalhado">
                      <summary>
                        <strong>Preencher formulário detalhado</strong>{' '}
                        <span className="dica">(opcional: como já tem documento anexado, dá para aprovar pelo botão verde acima)</span>
                      </summary>
                      <FormularioDetalhado key={versao} dados={dados} aoGravar={carga.recarregar} />
                    </details>
                  ) : (
                    <section className="cartao" aria-labelledby="titulo-novo">
                      <h2 id="titulo-novo">Novo registro{dados.etapa.subs.length > 1 && ` · ${dados.etapa.subs.find((s) => s.sub === dados.sub)?.nome ?? ''}`}</h2>
                      <FormularioDetalhado key={versao} dados={dados} aoGravar={carga.recarregar} />
                    </section>
                  )
                ) : (
                  <Faixa tipo="info">
                    Esta etapa ainda não é a etapa atual do lote. Você pode anexar documentos e usar o atalho “Aprovar etapa” acima: o lote avança
                    automaticamente até aqui.
                  </Faixa>
                ))}
            </>
          )}
        </div>
      )}
    </>
  );
}
