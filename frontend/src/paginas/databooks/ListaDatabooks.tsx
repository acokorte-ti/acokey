import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Marcacao } from '../../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { Confirmacao } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { TabelaOrdenavel, type Coluna } from '../../componentes/Tabela';
import { api, consulta, enderecoApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataCurta, dataHoraLocal, haDias, TRACO } from '../../lib/formato';
import type { TipoLote } from '../../lib/tipos';
import { useCarga } from '../../lib/useCarga';
import { ModalEnvio } from './ModalEnvio';
import type { DatabookAEnviar, DatabookEnvio, PainelDatabooks } from './tipos';

type Aba = 'a-enviar' | 'enviados';
type FiltroTipo = '' | TipoLote;
const TIPOS: { valor: FiltroTipo; rotulo: string }[] = [
  { valor: '', rotulo: 'Todos' },
  { valor: 'PIN', rotulo: 'PIN' },
  { valor: 'BOX', rotulo: 'BOX' },
  { valor: 'ARK', rotulo: 'ARK' },
];
/** Databook gerado há esse tanto de dias sem envio aparece em destaque (mesmo prazo do alerta do painel). */
const DIAS_ALERTA = 3;

function linkLote(lote: string, loteId: number | null) {
  return loteId ? (
    <Link to={`/lotes/${loteId}`} className="mono link-forte">
      {lote}
    </Link>
  ) : (
    <span className="mono">{lote || TRACO}</span>
  );
}

/** "?aba=enviados&tipo=PIN" (vazio = aba "A enviar", todos os tipos). */
function busca(aba: Aba, tipo: FiltroTipo): string {
  return consulta({ aba: aba === 'enviados' ? 'enviados' : '', tipo });
}

function enderecoAEnviar(d: DatabookAEnviar): string {
  return enderecoApi('/databooks/arquivo', { op: d.op, tipo: d.tipo, arquivo: d.arquivo });
}

// ---------------------------------------------------------------- aba "A enviar"

function TabelaAEnviar({ itens, aoMarcar }: { itens: DatabookAEnviar[]; aoMarcar: (d: DatabookAEnviar) => void }) {
  const colunas: Coluna<DatabookAEnviar>[] = [
    { chave: 'op', titulo: 'OP', mono: true, valor: (d) => d.op },
    { chave: 'tipo', titulo: 'Tipo', valor: (d) => d.tipo, celula: (d) => <SeloTipo tipo={d.tipo} /> },
    { chave: 'rev', titulo: 'Revisão', numerica: true, valor: (d) => d.revisao, celula: (d) => <span className="db-rev">Rev {d.revisao}</span> },
    {
      chave: 'lote',
      titulo: 'Lote e arquivo',
      valor: (d) => d.lote,
      celula: (d) => (
        <>
          {linkLote(d.lote, d.lote_id)}
          <span className="db-arquivo">
            {d.arquivo} · {d.tamanho_mb.toLocaleString('pt-BR')} MB
          </span>
        </>
      ),
    },
    {
      chave: 'gerado',
      titulo: 'Gerado em',
      valor: (d) => d.modificado,
      celula: (d) => (
        <>
          {dataHoraLocal(d.modificado)}
          <span className={`sub-linha ${d.dias >= DIAS_ALERTA ? 'db-velho' : ''}`}> · {haDias(d.dias)}</span>
        </>
      ),
    },
    {
      chave: 'acoes',
      titulo: 'Ações',
      ordenavel: false,
      valor: () => '',
      celula: (d) => (
        <span className="db-acoes">
          <a className="botao-link" href={enderecoAEnviar(d)} target="_blank" rel="noopener">
            Abrir PDF<span className="so-leitor"> (abre em outra aba)</span>
          </a>
          {d.lote_id && (
            <Link className="botao-link" to={`/databooks/conferir/${d.lote_id}${consulta({ arquivo: d.arquivo })}`}>
              Conferir
            </Link>
          )}
          <button type="button" className="botao botao-pequeno" onClick={() => aoMarcar(d)}>
            Marcar como Enviado-DB
          </button>
        </span>
      ),
    },
  ];
  return (
    <TabelaOrdenavel
      legenda="Databooks gerados que ainda não foram enviados ao cliente"
      colunas={colunas}
      linhas={itens}
      chaveLinha={(d) => `${d.op}-${d.tipo}-${d.lote}-${d.revisao}`}
      ordemInicial={{ chave: 'op', direcao: 'asc' }}
    />
  );
}

// ---------------------------------------------------------------- aba "Enviados-DB"

function TabelaEnviados({ itens, aoDesfazer }: { itens: DatabookEnvio[]; aoDesfazer: (e: DatabookEnvio) => void }) {
  const colunas: Coluna<DatabookEnvio>[] = [
    { chave: 'op', titulo: 'OP', mono: true, valor: (e) => e.op },
    {
      chave: 'tipo',
      titulo: 'Tipo',
      valor: (e) => e.tipo,
      celula: (e) => (['PIN', 'BOX', 'ARK'].includes(e.tipo) ? <SeloTipo tipo={e.tipo as TipoLote} /> : e.tipo || TRACO),
    },
    { chave: 'rev', titulo: 'Revisão', numerica: true, valor: (e) => e.revisao, celula: (e) => <span className="db-rev">Rev {e.revisao}</span> },
    {
      chave: 'lote',
      titulo: 'Lote e arquivo',
      valor: (e) => e.lote,
      celula: (e) => (
        <>
          {linkLote(e.lote, e.lote_id)}
          <span className="db-arquivo">{e.arquivo}</span>
        </>
      ),
    },
    {
      chave: 'data',
      titulo: 'Enviado-DB',
      valor: (e) => e.data_envio,
      celula: (e) => (
        <>
          <span className="db-enviado">Enviado-DB em {dataCurta(e.data_envio)}</span>
          <span className="sub-linha">
            {' '}
            para <strong>{e.destinatario || TRACO}</strong>
            {e.nf_saida && <> · NF {e.nf_saida}</>}
          </span>
          {e.observacoes && <span className="sub-linha" style={{ display: 'block' }}>Obs.: {e.observacoes}</span>}
          {e.desfeito_em && (
            <span className="texto-erro" style={{ display: 'block', fontSize: 12.5 }}>
              Envio desfeito em {dataHoraLocal(e.desfeito_em)} por {e.desfeito_por || TRACO}: {e.desfeito_motivo}
            </span>
          )}
        </>
      ),
    },
    {
      chave: 'registro',
      titulo: 'Registrado por',
      valor: (e) => e.enviado_em,
      celula: (e) => (
        <>
          {e.enviado_por || TRACO}
          <span className="sub-linha" style={{ display: 'block' }}>
            {dataHoraLocal(e.enviado_em)}
          </span>
        </>
      ),
    },
    {
      chave: 'acoes',
      titulo: 'Ações',
      ordenavel: false,
      valor: () => '',
      celula: (e) => (
        <span className="db-acoes">
          {e.tem_arquivo ? (
            <a className="botao-link" href={enderecoApi(`/databooks/envios/${e.id}/arquivo`)} target="_blank" rel="noopener">
              Abrir PDF<span className="so-leitor"> (abre em outra aba)</span>
            </a>
          ) : (
            <span className="rotulo-discreto">PDF não encontrado</span>
          )}
          {!e.desfeito_em && (
            <button type="button" className="botao botao-pequeno botao-perigo-contorno" onClick={() => aoDesfazer(e)}>
              Desfazer envio
            </button>
          )}
        </span>
      ),
    },
  ];
  return (
    <TabelaOrdenavel
      legenda="Databooks enviados ao cliente"
      colunas={colunas}
      linhas={itens}
      chaveLinha={(e) => e.id}
      classeLinha={(e) => (e.desfeito_em ? 'db-linha-desfeita' : undefined)}
    />
  );
}

// ---------------------------------------------------------------- tela

/** /databooks: abas "A enviar" e "Enviados-DB" (aceita ?aba= ou ?tab=, e ?tipo=PIN|BOX|ARK, vindos do painel). */
export function ListaDatabooks() {
  const avisos = useAvisos();
  const [parametros, setParametros] = useSearchParams();
  const aba: Aba = (parametros.get('aba') ?? parametros.get('tab')) === 'enviados' ? 'enviados' : 'a-enviar';
  const tipoUrl = (parametros.get('tipo') ?? '').toUpperCase();
  const tipo: FiltroTipo = tipoUrl === 'PIN' || tipoUrl === 'BOX' || tipoUrl === 'ARK' ? tipoUrl : '';
  const [incluirDesfeitos, setIncluirDesfeitos] = useState(false);
  const carga = useCarga<PainelDatabooks>(
    (sinal) => api(`/databooks${consulta({ incluir_desfeitos: incluirDesfeitos || undefined })}`, { sinal }),
    [incluirDesfeitos],
  );
  const [envio, setEnvio] = useState<DatabookAEnviar | null>(null);
  const [desfazer, setDesfazer] = useState<DatabookEnvio | null>(null);
  const [motivo, setMotivo] = useState('');
  const [desfazendo, setDesfazendo] = useState(false);

  const dados = carga.dados;
  const aEnviar = useMemo(() => (dados?.a_enviar ?? []).filter((d) => !tipo || d.tipo === tipo), [dados, tipo]);
  const enviados = useMemo(() => (dados?.enviados ?? []).filter((e) => !tipo || e.tipo.toUpperCase() === tipo), [dados, tipo]);

  function irPara(novaAba: Aba, novoTipo: FiltroTipo = tipo) {
    setParametros(new URLSearchParams(busca(novaAba, novoTipo)), { replace: true });
  }

  async function confirmarDesfazer() {
    if (!desfazer) return;
    if (motivo.trim().length < 3) {
      avisos.erro('Escreva o motivo para desfazer o envio.');
      return;
    }
    setDesfazendo(true);
    try {
      await api(`/databooks/envios/${desfazer.id}/desfazer`, { metodo: 'POST', corpo: { motivo: motivo.trim() } });
      avisos.sucesso(`Envio do databook OP ${desfazer.op}/${desfazer.tipo} desfeito. Ele voltou para a aba A enviar.`);
      setDesfazer(null);
      carga.recarregar();
      irPara('a-enviar');
    } catch (e) {
      avisos.erro(mensagemDeErro(e));
    } finally {
      setDesfazendo(false);
    }
  }

  return (
    <>
      <Cabecalho titulo="Databooks" apoio="Controle de envio do databook ao cliente (Enviado-DB).">
        <Link to="/" className="botao">
          ← Painel
        </Link>
      </Cabecalho>

      <Faixa tipo="info">
        Aqui aparecem os databooks gerados nos lotes. Quando mandar um para o cliente, clique em <strong>Marcar como Enviado-DB</strong>:
        uma cópia do PDF vai para a pasta Enviados e o envio fica registrado. Isso não muda a geração do databook e não é a saída
        física do lote (essa é a Ordem de Faturamento).
      </Faixa>

      <nav className="abas" aria-label="Situação do databook" style={{ marginTop: 16 }}>
        <Link
          to={{ search: busca('a-enviar', tipo) }}
          replace
          className={`aba ${aba === 'a-enviar' ? 'aba-atual' : ''}`}
          aria-current={aba === 'a-enviar' ? 'page' : undefined}
        >
          A enviar<span className="db-contagem">{dados?.n_a_enviar ?? TRACO}</span>
        </Link>
        <Link
          to={{ search: busca('enviados', tipo) }}
          replace
          className={`aba ${aba === 'enviados' ? 'aba-atual' : ''}`}
          aria-current={aba === 'enviados' ? 'page' : undefined}
        >
          Enviados-DB<span className="db-contagem">{dados?.n_enviados ?? TRACO}</span>
        </Link>
      </nav>

      <section className="cartao cartao-aba" aria-label={aba === 'a-enviar' ? 'A enviar' : 'Enviados-DB'}>
        <div className="db-topo-lista">
          <div className="db-acoes">
            <span className="dica" id="db-rotulo-tipo">
              Tipo de chaveta:
            </span>
            <div className="segmentos" role="group" aria-labelledby="db-rotulo-tipo">
              {TIPOS.map((t) => (
                <button
                  key={t.valor || 'todos'}
                  type="button"
                  className={`segmento ${tipo === t.valor ? 'segmento-ativo' : ''}`}
                  aria-pressed={tipo === t.valor}
                  onClick={() => irPara(aba, t.valor)}
                >
                  {t.rotulo}
                </button>
              ))}
            </div>
          </div>
          {aba === 'enviados' && (
            <Marcacao id="db-incluir-desfeitos" marcado={incluirDesfeitos} aoMudar={setIncluirDesfeitos}>
              Mostrar também os envios desfeitos
            </Marcacao>
          )}
        </div>
        {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
        {!carga.erro && !dados && <Carregando />}
        {dados && aba === 'a-enviar' && (
          <div className={carga.carregando ? 'recarregando' : ''}>
            {aEnviar.length === 0 ? (
              <Vazio titulo={tipo ? `Nenhum databook ${tipo} pendente de envio no momento.` : 'Nenhum databook pendente de envio no momento.'} />
            ) : (
              <>
                <TabelaAEnviar itens={aEnviar} aoMarcar={setEnvio} />
                <p className="dica" style={{ marginTop: 8 }}>
                  Só a revisão mais recente de cada lote aparece aqui: as anteriores nunca vão para o cliente.
                </p>
              </>
            )}
          </div>
        )}
        {dados && aba === 'enviados' && (
          <div className={carga.carregando ? 'recarregando' : ''}>
            {enviados.length === 0 ? (
              <Vazio titulo={tipo ? `Nenhum databook ${tipo} enviado ainda.` : 'Nenhum databook enviado ainda.'} />
            ) : (
              <TabelaEnviados
                itens={enviados}
                aoDesfazer={(e) => {
                  setMotivo('');
                  setDesfazer(e);
                }}
              />
            )}
          </div>
        )}
      </section>

      {envio && dados && (
        <ModalEnvio
          item={envio}
          hoje={dados.hoje}
          aoFechar={() => setEnvio(null)}
          aoConcluir={() => {
            setEnvio(null);
            carga.recarregar();
            irPara('enviados');
          }}
        />
      )}

      {desfazer && (
        <Confirmacao
          titulo="Desfazer envio do databook"
          rotuloConfirmar="Desfazer envio"
          perigo
          enviando={desfazendo}
          aoFechar={() => setDesfazer(null)}
          aoConfirmar={() => void confirmarDesfazer()}
        >
          <p>
            Desfazer o envio do databook <strong>OP {desfazer.op}/{desfazer.tipo}</strong> (Rev {desfazer.revisao}, enviado em{' '}
            {dataCurta(desfazer.data_envio)} para {desfazer.destinatario || TRACO})?
          </p>
          <p className="dica">O databook volta para a aba A enviar. O registro deste envio fica guardado, marcado como desfeito.</p>
          <div className="campo">
            <label htmlFor="db-desfazer-motivo">
              Motivo<span className="obrigatorio"> *</span>
            </label>
            <textarea
              id="db-desfazer-motivo"
              rows={2}
              maxLength={500}
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              placeholder="Ex.: marcado por engano"
              required
            />
          </div>
        </Confirmacao>
      )}
    </>
  );
}
