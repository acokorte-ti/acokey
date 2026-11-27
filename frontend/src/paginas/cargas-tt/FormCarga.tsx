import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Campo, Marcacao } from '../../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { Confirmacao } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { contemTermos, inteiro, pecas, TRACO } from '../../lib/formato';
import type { TipoLote } from '../../lib/tipos';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useCarga } from '../../lib/useCarga';
import { SeletorEquipamento } from '../relatorios/Comuns';
import { Instrucoes } from './Comuns';
import type { FormularioCarga, RespostaCarga } from './tipos';

type Filtro = 'TODOS' | TipoLote;
const FILTROS: Filtro[] = ['TODOS', 'PIN', 'BOX', 'ARK'];

/** Padrão do forno: o gravado (ou o dos parâmetros) se existir no cadastro; senão o primeiro da lista, como no antigo. */
function fornoInicial(lista: { codigo: string }[], padrao: string, editando: boolean): string {
  if (padrao && (editando || lista.some((e) => e.codigo === padrao))) return padrao;
  return lista[0]?.codigo ?? '';
}

export function FormCarga({ cargaId }: { cargaId: number | null }) {
  const navegar = useNavigate();
  const avisos = useAvisos();
  const editando = cargaId !== null;
  const form = useCarga<FormularioCarga>(
    (sinal) => api(`/cargas-tt/formulario${editando ? `?carga_id=${cargaId}` : ''}`, { sinal }),
    [cargaId],
  );
  const dados = form.dados;

  const [fornoTempera, setFornoTempera] = useState('');
  const [fornoRevenimento, setFornoRevenimento] = useState('');
  const [dataPlanejada, setDataPlanejada] = useState('');
  const [observacoes, setObservacoes] = useState('');
  const [selecionados, setSelecionados] = useState<number[]>([]);
  const [filtro, setFiltro] = useState<Filtro>('TODOS');
  const [busca, setBusca] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [confirmarRelatorio, setConfirmarRelatorio] = useState(false);

  useEffect(() => {
    if (!dados) return;
    setFornoTempera(fornoInicial(dados.fornos_tempera, dados.forno_tempera_padrao, editando));
    setFornoRevenimento(fornoInicial(dados.fornos_revenimento, dados.forno_revenimento_padrao, editando));
    setDataPlanejada(dados.carga ? (dados.carga.data_planejada ?? '') : dados.hoje);
    setObservacoes(dados.carga?.observacoes ?? '');
    setSelecionados(dados.lote_ids);
  }, [dados, editando]);

  const escolhidos = useMemo(
    () => (dados ? dados.disponiveis.filter((l) => selecionados.includes(l.id)) : []),
    [dados, selecionados],
  );

  if (form.erro) {
    return (
      <>
        <Cabecalho titulo={editando ? 'Editar carga' : 'Nova carga de tratamento térmico'} />
        <ErroCarga mensagem={form.erro} aoTentar={form.recarregar} />
      </>
    );
  }
  if (!dados) return <Carregando />;
  const carga = dados.carga;
  if (carga?.status === 'cancelada') {
    return (
      <>
        <Cabecalho titulo={`Carga ${carga.numero}`} />
        <Vazio titulo="Esta carga está cancelada e não pode mais ser alterada.">
          <Link to={`/cargas-tt/${carga.id}`}>Voltar para a carga</Link>
        </Vazio>
      </>
    );
  }

  // A busca só esconde da lista: lote marcado continua na carga mesmo fora da busca (a contagem avisa).
  const visiveis = dados.disponiveis.filter(
    (l) => (filtro === 'TODOS' || l.tipo === filtro) && contemTermos(`OP ${l.op} lote ${l.numero} ${l.corrida}`, busca),
  );
  const marcadosEscondidos = escolhidos.filter((l) => !visiveis.some((v) => v.id === l.id)).length;
  const tipos = new Set(escolhidos.map((l) => l.tipo));
  const misturaArk = tipos.has('ARK') && (tipos.has('PIN') || tipos.has('BOX'));
  const totalPecas = escolhidos.reduce((soma, l) => soma + (l.qtd || 0), 0);
  const temFornosTempera = dados.fornos_tempera.length > 0;
  const temFornosRevenimento = dados.fornos_revenimento.length > 0;

  function alternar(id: number, marcado: boolean) {
    setSelecionados((atual) => (marcado ? [...atual, id] : atual.filter((x) => x !== id)));
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    if (selecionados.length === 0) {
      setErro('Selecione ao menos um lote para a carga.');
      return;
    }
    if ((temFornosTempera && !fornoTempera) || (temFornosRevenimento && !fornoRevenimento)) {
      setErro('Escolha o forno de têmpera e o de revenimento.');
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const corpo = {
        forno_tempera_codigo: fornoTempera,
        forno_revenimento_codigo: fornoRevenimento,
        data_planejada: dataPlanejada || null,
        observacoes,
        lote_ids: selecionados,
      };
      const resposta = await api<RespostaCarga>(editando ? `/cargas-tt/${cargaId}` : '/cargas-tt', {
        metodo: editando ? 'PUT' : 'POST',
        corpo,
      });
      avisos.sucesso(resposta.mensagem);
      if (resposta.aviso) avisos.info(resposta.aviso);
      navegar(`/cargas-tt/${resposta.id}`);
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setEnviando(false);
    }
  }

  const titulo = carga ? `Editar carga ${carga.numero}` : 'Nova carga de tratamento térmico';
  const urlRelatorio = carga ? `/relatorios/tt?carga=${carga.id}` : '';

  return (
    <>
      <Cabecalho
        titulo={titulo}
        apoio={
          <>
            <Link to="/cargas-tt">Cargas de TT</Link> · Escolha os fornos, marque os lotes que vão entrar juntos (PIN e BOX podem ir na
            mesma carga; o ARK tem ciclo diferente, use carga separada) e consulte a ITT antes de começar.
          </>
        }
      />
      <form className="pilha ctt-form" onSubmit={enviar} onKeyDown={enterVaiParaProximo} noValidate>
        {carga?.status === 'concluida' && (
          <Faixa tipo="alerta">
            Esta carga está <strong>concluída</strong>. Editar aqui ajusta só a composição da carga: os anexos e registros já gerados nos
            lotes não mudam. Para levar o relatório aos lotes incluídos agora, gere o relatório de TT de novo a partir da carga.
          </Faixa>
        )}

        <section className="cartao" aria-labelledby="titulo-identificacao">
          <h2 id="titulo-identificacao">Identificação da carga</h2>
          <div className="linha-campos">
            <Campo
              rotulo="Número da carga"
              para="ctt-numero"
              dica={carga ? undefined : 'Gerado pelo sistema ao gravar (previsão). Duas cargas nunca recebem o mesmo número.'}
            >
              <div id="ctt-numero" className="automatico mono">
                {dados.numero_previsto}
              </div>
            </Campo>
            <Campo rotulo="Data planejada" para="ctt-data">
              <input id="ctt-data" type="date" value={dataPlanejada} onChange={(e) => setDataPlanejada(e.target.value)} />
            </Campo>
          </div>
        </section>

        <section className="cartao" aria-labelledby="titulo-fornos">
          <h2 id="titulo-fornos">
            Fornos <span className="sub-linha">(do cadastro de equipamentos)</span>
          </h2>
          <div className="linha-campos">
            <SeletorEquipamento
              id="ctt-forno-tempera"
              rotulo="Forno de têmpera"
              lista={dados.fornos_tempera}
              valor={fornoTempera}
              aoMudar={setFornoTempera}
              obrigatorio={dados.fornos_tempera.length > 0}
              vazio="Nenhum forno de têmpera no cadastro de equipamentos."
            />
            <SeletorEquipamento
              id="ctt-forno-revenimento"
              rotulo="Forno de revenimento"
              lista={dados.fornos_revenimento}
              valor={fornoRevenimento}
              aoMudar={setFornoRevenimento}
              obrigatorio={dados.fornos_revenimento.length > 0}
              vazio="Nenhum forno de revenimento no cadastro de equipamentos."
            />
          </div>
        </section>

        <section className="cartao" aria-labelledby="titulo-lotes-carga">
          <div className="cartao-topo">
            <h2 id="titulo-lotes-carga">Lotes nesta carga</h2>
            <div className="segmentos" role="group" aria-label="Filtrar por tipo">
              {FILTROS.map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`segmento ${filtro === f ? 'segmento-ativo' : ''}`}
                  aria-pressed={filtro === f}
                  onClick={() => setFiltro(f)}
                >
                  {f === 'TODOS' ? 'Todos' : f}
                </button>
              ))}
            </div>
          </div>
          <div className="campo ctt-busca">
            <label htmlFor="ctt-busca">Buscar lote ou OP</label>
            <input
              id="ctt-busca"
              type="search"
              placeholder="Nº da OP, do lote ou corrida"
              autoComplete="off"
              spellCheck={false}
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>
          <p className="dica">
            Marque todos os lotes que vão entrar juntos. Só aparecem lotes que estão na etapa de <strong>tratamento térmico</strong>
            {carga ? ' (e os que já estão nesta carga)' : ''}.
          </p>
          {dados.disponiveis.length === 0 ? (
            <Vazio titulo="Nenhum lote aguardando o tratamento térmico no momento." />
          ) : visiveis.length === 0 ? (
            <p className="dica">
              {busca.trim()
                ? `Nenhum lote${filtro === 'TODOS' ? '' : ` ${filtro}`} com essa busca.`
                : `Nenhum lote ${filtro} aguardando o tratamento térmico.`}
            </p>
          ) : (
            <ul className="ctt-opcoes">
              {visiveis.map((l) => (
                <li key={l.id} className={selecionados.includes(l.id) ? 'ctt-opcao-marcada' : ''}>
                  <Marcacao id={`ctt-lote-${l.id}`} marcado={selecionados.includes(l.id)} aoMudar={(m) => alternar(l.id, m)}>
                    <strong>OP {l.op}</strong> <SeloTipo tipo={l.tipo} /> · {pecas(l.qtd)} · Lote <span className="mono">{l.numero}</span>
                    <span className="ctt-opcao-sub">
                      {l.cliente || TRACO} · corrida {l.corrida || TRACO}
                      {l.em_cargas > 0 && (
                        <strong className="ctt-ja-em-carga">
                          {' '}
                          · já está em {l.em_cargas} {l.em_cargas === 1 ? 'outra carga' : 'outras cargas'}
                        </strong>
                      )}
                      {!l.aguardando_tt && <span> · já passou do tratamento térmico</span>}
                    </span>
                  </Marcacao>
                </li>
              ))}
            </ul>
          )}
          <p className="nota-discreta" aria-live="polite">
            {inteiro(escolhidos.length)} {escolhidos.length === 1 ? 'lote selecionado' : 'lotes selecionados'} · {pecas(totalPecas)}
            {marcadosEscondidos > 0 &&
              ` · ${inteiro(marcadosEscondidos)} ${marcadosEscondidos === 1 ? 'marcado não aparece' : 'marcados não aparecem'} com este filtro`}
          </p>
          {misturaArk && (
            <Faixa tipo="alerta">
              A carga mistura ARK com PIN/BOX. O ARK tem ciclo e material diferentes: o recomendado é carga separada. O sistema não
              impede.
            </Faixa>
          )}
        </section>

        <Instrucoes />

        <section className="cartao" aria-labelledby="titulo-obs-carga">
          <h2 id="titulo-obs-carga">Observações</h2>
          <Campo rotulo="Observações" para="ctt-obs">
            <textarea
              id="ctt-obs"
              rows={3}
              maxLength={4000}
              placeholder="Ex.: carga noturna, operador do turno, peças com prioridade…"
              value={observacoes}
              onChange={(e) => setObservacoes(e.target.value)}
            />
          </Campo>
        </section>

        <section className="cartao acoes-form">
          {erro && (
            <p className="erro-formulario" role="alert">
              {erro}
            </p>
          )}
          <div className="acoes">
            <button type="submit" className="botao botao-primario" disabled={enviando}>
              {enviando ? 'Gravando…' : carga ? 'Salvar alterações' : 'Criar carga'}
            </button>
            <Link to={carga ? `/cargas-tt/${carga.id}` : '/cargas-tt'} className="botao">
              Cancelar
            </Link>
            {carga && dados.lote_ids.length > 0 && (
              <button
                type="button"
                className="botao"
                onClick={() => (carga.status === 'concluida' ? setConfirmarRelatorio(true) : navegar(urlRelatorio))}
              >
                {carga.status === 'concluida' ? 'Gerar relatório novamente' : 'Gerar relatório de TT'}
              </button>
            )}
            <span className="dica">
              {carga
                ? 'O relatório de TT anexa o PDF em todos os lotes da carga e avança a etapa de cada um (salve antes as alterações).'
                : 'A carga começa como planejada. Você inicia e conclui ela depois, na tela da carga.'}
            </span>
          </div>
        </section>
      </form>

      {confirmarRelatorio && carga && (
        <Confirmacao
          titulo="Gerar o relatório de novo?"
          rotuloConfirmar="Continuar"
          aoConfirmar={() => navegar(urlRelatorio)}
          aoFechar={() => setConfirmarRelatorio(false)}
        >
          <p>
            A carga {carga.numero} já está concluída. Gerar novamente o relatório cria um novo anexo e repete a movimentação nos lotes da
            carga.
          </p>
        </Confirmacao>
      )}
    </>
  );
}
