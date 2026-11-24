import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { Confirmacao, ModalFormulario } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, enderecoApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataCurta, dataHoraLocal, pecas, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import { Instrucoes, SeloCarga } from './Comuns';
import type { CargaDetalhe, StatusCarga } from './tipos';

type Acao = 'iniciar' | 'concluir' | 'cancelar' | 'relatorio' | null;

export function DetalheCarga({ cargaId }: { cargaId: number }) {
  const navegar = useNavigate();
  const avisos = useAvisos();
  const carga = useCarga<CargaDetalhe>((sinal) => api(`/cargas-tt/${cargaId}`, { sinal }), [cargaId]);
  const [acao, setAcao] = useState<Acao>(null);
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  if (carga.erro) {
    return (
      <>
        <Cabecalho titulo="Carga de tratamento térmico" />
        <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />
      </>
    );
  }
  const c = carga.dados;
  if (!c) return <Carregando />;

  function fechar() {
    setAcao(null);
    setErro(null);
    setMotivo('');
  }

  async function mudarStatus(status: Exclude<StatusCarga, 'planejada'>) {
    if (enviando) return;
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await api<{ mensagem: string }>(`/cargas-tt/${cargaId}/status`, {
        metodo: 'POST',
        corpo: { status, motivo: status === 'cancelada' ? motivo : '' },
      });
      avisos.sucesso(resposta.mensagem);
      fechar();
      carga.recarregar();
    } catch (falha) {
      const mensagem = mensagemDeErro(falha);
      if (acao) setErro(mensagem);
      else avisos.erro(mensagem);
    } finally {
      setEnviando(false);
    }
  }

  const urlRelatorio = `/relatorios/tt?carga=${c.id}`;
  const podeGerar = c.lotes.length > 0 && c.status !== 'cancelada';

  return (
    <>
      <Cabecalho
        titulo={`Carga ${c.numero}`}
        apoio={
          <>
            <Link to="/cargas-tt">Cargas de TT</Link>
            {c.data_planejada && <> · planejada para {dataCurta(c.data_planejada)}</>} · criada em {dataHoraLocal(c.criado_em)} por{' '}
            {c.criado_por || TRACO}
          </>
        }
      >
        <SeloCarga status={c.status} />
      </Cabecalho>

      <div className={`pilha ${carga.carregando ? 'recarregando' : ''}`}>
        {c.status === 'cancelada' && (
          <Faixa tipo="alerta">
            Cancelada em {dataHoraLocal(c.cancelado_em)} por {c.cancelado_por || TRACO}. Motivo: {c.cancelado_motivo || TRACO}
          </Faixa>
        )}

        <section className="cartao" aria-labelledby="titulo-acoes">
          <h2 id="titulo-acoes">Ações</h2>
          <div className="acoes">
            {c.status === 'planejada' && (
              <button type="button" className="botao botao-primario" onClick={() => void mudarStatus('em_andamento')} disabled={enviando}>
                ▶ Iniciar execução
              </button>
            )}
            {podeGerar && (
              <button
                type="button"
                className={`botao ${c.status === 'planejada' ? '' : 'botao-primario'}`}
                onClick={() => (c.status === 'concluida' ? setAcao('relatorio') : navegar(urlRelatorio))}
              >
                {c.status === 'concluida' ? 'Gerar relatório novamente' : 'Gerar relatório de TT'}
              </button>
            )}
            {c.status === 'em_andamento' && (
              <button type="button" className="botao" onClick={() => setAcao('concluir')}>
                ✓ Concluir (sem relatório)
              </button>
            )}
            {c.status !== 'cancelada' && (
              <Link to={`/cargas-tt/${c.id}/editar`} className="botao">
                Editar carga
              </Link>
            )}
            {(c.status === 'planejada' || c.status === 'em_andamento') && (
              <button type="button" className="botao botao-perigo-contorno" onClick={() => setAcao('cancelar')}>
                Cancelar carga
              </button>
            )}
            <Link to="/cargas-tt" className="botao botao-fantasma">
              ← Voltar
            </Link>
          </div>
          {podeGerar && (
            <p className="dica">O relatório de TT anexa o PDF em todos os lotes da carga, avança a etapa de cada um e conclui a carga.</p>
          )}
          {c.data_inicio && (
            <p className="dica">
              Início: {dataHoraLocal(c.data_inicio)}
              {c.data_fim && <> · Fim: {dataHoraLocal(c.data_fim)}</>}
            </p>
          )}
          {c.relatorio && (
            <p>
              Relatório de TT:{' '}
              <a href={enderecoApi(`/anexos/${c.relatorio.anexo_id}/arquivo`)} target="_blank" rel="noopener">
                {c.relatorio.nome}
                <span className="so-leitor"> (abre em outra aba)</span>
              </a>
            </p>
          )}
        </section>

        <section className="cartao" aria-labelledby="titulo-fornos-det">
          <h2 id="titulo-fornos-det">Fornos</h2>
          <dl className="ficha ficha-linha">
            <div>
              <dt>Têmpera</dt>
              <dd>
                {c.forno_tempera_desc}
                {c.forno_tempera_codigo && <span className="sub-linha"> ({c.forno_tempera_codigo})</span>}
              </dd>
            </div>
            <div>
              <dt>Revenimento</dt>
              <dd>
                {c.forno_revenimento_desc}
                {c.forno_revenimento_codigo && <span className="sub-linha"> ({c.forno_revenimento_codigo})</span>}
              </dd>
            </div>
          </dl>
        </section>

        <section className="cartao" aria-labelledby="titulo-lotes-det">
          <h2 id="titulo-lotes-det">
            Lotes nesta carga ({c.lotes.length}) <span className="sub-linha">· {pecas(c.total_pecas)}</span>
          </h2>
          {c.lotes.length === 0 ? (
            <Vazio titulo="Nenhum lote nesta carga." />
          ) : (
            <ul className="ctt-grade-lotes">
              {c.lotes.map((l) => (
                <li key={l.id} className="ctt-lote">
                  <div>
                    <Link to={`/lotes/${l.id}`} className="link-forte">
                      OP {l.op}
                    </Link>{' '}
                    <SeloTipo tipo={l.tipo} />
                  </div>
                  <div className="sub-linha">
                    Lote <span className="mono">{l.numero}</span> · {pecas(l.qtd)} · {l.cliente || TRACO}
                  </div>
                  <div className="sub-linha">Corrida {l.corrida || TRACO}</div>
                  <div>
                    {l.cancelado ? (
                      <span className="selo selo-inativo">Lote cancelado</span>
                    ) : l.tt_aprovado ? (
                      <span className="selo selo-ok">TT aprovado</span>
                    ) : (
                      <span className="selo selo-espera">Etapa: {l.etapa_atual}</span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <Instrucoes />

        {c.observacoes && (
          <section className="cartao" aria-labelledby="titulo-obs-det">
            <h2 id="titulo-obs-det">Observações</h2>
            <p className="ctt-observacoes">{c.observacoes}</p>
          </section>
        )}
      </div>

      {acao === 'concluir' && (
        <Confirmacao
          titulo="Concluir sem relatório?"
          rotuloConfirmar="Concluir"
          aoConfirmar={() => void mudarStatus('concluida')}
          aoFechar={fechar}
          enviando={enviando}
        >
          <p>A carga {c.numero} será marcada como concluída sem gerar o relatório de TT pelo sistema.</p>
          {erro && (
            <p className="erro-formulario" role="alert">
              {erro}
            </p>
          )}
        </Confirmacao>
      )}

      {acao === 'relatorio' && (
        <Confirmacao
          titulo="Gerar o relatório de novo?"
          rotuloConfirmar="Continuar"
          aoConfirmar={() => navegar(urlRelatorio)}
          aoFechar={fechar}
        >
          <p>
            Esta carga já está concluída. Gerar novamente o relatório cria um novo anexo e repete a movimentação nos lotes da carga.
          </p>
        </Confirmacao>
      )}

      {acao === 'cancelar' && (
        <ModalFormulario
          titulo={`Cancelar a carga ${c.numero}`}
          aoFechar={fechar}
          aoEnviar={() => {
            if (motivo.trim().length < 3) setErro('Escreva o motivo do cancelamento.');
            else void mudarStatus('cancelada');
          }}
          enviando={enviando}
          rotuloEnviar="Cancelar carga"
          erro={erro}
          perigo
        >
          <p>A carga sai da lista em aberto. Nada é apagado: ela fica na aba Canceladas e na linha do tempo de cada lote.</p>
          <Campo rotulo="Motivo" para="ctt-motivo" obrigatorio>
            <textarea id="ctt-motivo" rows={3} maxLength={2000} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </Campo>
        </ModalFormulario>
      )}
    </>
  );
}
