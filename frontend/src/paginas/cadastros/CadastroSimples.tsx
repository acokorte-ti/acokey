import { useMemo, useState, type ReactNode } from 'react';
import { Marcacao } from '../../componentes/Campo';
import { Carregando, ErroCarga, SeloAtivo, Vazio } from '../../componentes/Estados';
import { Confirmacao, ModalFormulario } from '../../componentes/Modal';
import { TabelaOrdenavel, type Coluna, type Ordenacao } from '../../componentes/Tabela';
import { api, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { contemTermos, inteiro } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';

interface FiltroExtra<T> {
  rotulo: string;
  opcoes: { valor: string; rotulo: string }[];
  passa: (item: T, valor: string) => boolean;
}

interface ItemCadastro {
  id: number;
  codigo: string;
  ativo: boolean;
}

export interface PropsCadastro<T extends ItemCadastro, F> {
  /** Rota da API: GET lista, POST cria, PUT /{id} altera, POST /{id}/inativar e /{id}/reativar. */
  rota: string;
  /** Nome do item no singular, em minúsculas ("equipamento", "prestador"). */
  nome: string;
  /** Quem só consulta não vê os botões de gravar. */
  podeEditar: boolean;
  colunas: Coluna<T>[];
  textoBusca: (item: T) => string;
  novo: () => F;
  editar: (item: T) => F;
  /** Corpo enviado à API. */
  envio: (formulario: F) => unknown;
  campos: (formulario: F, mudar: (parcial: Partial<F>) => void, item: T | null, todos: T[]) => ReactNode;
  filtro?: FiltroExtra<T>;
  ordemInicial?: Ordenacao;
  classeLinha?: (item: T) => string | undefined;
  /** Texto da confirmação de inativar (o que deixa de acontecer). */
  efeitoInativar: string;
}

interface Edicao<T, F> {
  item: T | null; // null = cadastro novo
  formulario: F;
}

/**
 * Cadastro simples: busca, tabela ordenável e formulário em janela.
 * Não existe exclusão (no sistema antigo a linha era apagada da planilha): o que sai de uso é inativado e pode voltar.
 */
export function CadastroSimples<T extends ItemCadastro, F>({
  rota,
  nome,
  podeEditar,
  colunas,
  textoBusca,
  novo,
  editar,
  envio,
  campos,
  filtro,
  ordemInicial,
  classeLinha,
  efeitoInativar,
}: PropsCadastro<T, F>) {
  const avisos = useAvisos();
  const lista = useCarga<T[]>((sinal) => api<T[]>(rota, { sinal }), [rota]);
  const [busca, setBusca] = useState('');
  const [valorFiltro, setValorFiltro] = useState('');
  const [mostrarInativos, setMostrarInativos] = useState(false);
  const [edicao, setEdicao] = useState<Edicao<T, F> | null>(null);
  const [situacao, setSituacao] = useState<T | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const todos = useMemo(() => lista.dados ?? [], [lista.dados]);
  const filtradas = useMemo(
    () =>
      todos.filter(
        (item) =>
          (mostrarInativos || item.ativo) &&
          (!filtro || !valorFiltro || filtro.passa(item, valorFiltro)) &&
          contemTermos(textoBusca(item), busca),
      ),
    // `filtro` e `textoBusca` são funções fixas de cada cadastro
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [todos, busca, valorFiltro, mostrarInativos],
  );

  const colunasComAcao = useMemo<Coluna<T>[]>(() => {
    const comSituacao: Coluna<T>[] = [
      ...colunas,
      { chave: '_situacao', titulo: 'Situação', valor: (item) => item.ativo, celula: (item) => <SeloAtivo ativo={item.ativo} /> },
    ];
    if (!podeEditar) return comSituacao;
    return [
      ...comSituacao,
      {
        chave: '_acoes',
        titulo: 'Ações',
        ordenavel: false,
        valor: () => null,
        celula: (item) => (
          <span className="acoes-linha">
            <button
              type="button"
              className="botao botao-pequeno"
              onClick={() => {
                setErro(null);
                setEdicao({ item, formulario: editar(item) });
              }}
            >
              Editar
            </button>
            <button
              type="button"
              className={`botao botao-pequeno ${item.ativo ? 'botao-perigo-contorno' : ''}`}
              onClick={() => {
                setErro(null);
                setSituacao(item);
              }}
            >
              {item.ativo ? 'Inativar' : 'Reativar'}
            </button>
          </span>
        ),
      },
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colunas, podeEditar]);

  async function salvar() {
    if (!edicao) return;
    setErro(null);
    setEnviando(true);
    try {
      const corpo = envio(edicao.formulario);
      if (edicao.item) await api<T>(`${rota}/${edicao.item.id}`, { metodo: 'PUT', corpo });
      else await api<T>(rota, { metodo: 'POST', corpo });
      avisos.sucesso(`Cadastro de ${nome} gravado.`);
      setEdicao(null);
      lista.recarregar();
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  async function trocarSituacao() {
    if (!situacao) return;
    setEnviando(true);
    try {
      await api<T>(`${rota}/${situacao.id}/${situacao.ativo ? 'inativar' : 'reativar'}`, { metodo: 'POST' });
      avisos.sucesso(`${situacao.codigo} ${situacao.ativo ? 'inativado' : 'reativado'}.`);
      setSituacao(null);
      lista.recarregar();
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  const idBusca = `busca${rota.replace(/\W/g, '-')}`;
  const inativos = todos.filter((item) => !item.ativo).length;

  return (
    <section className="cartao" aria-label={`Cadastro de ${nome}`}>
      <div className="filtros">
        <div className="campo campo-busca">
          <label htmlFor={idBusca}>Buscar</label>
          <input id={idBusca} type="search" placeholder="Código ou nome…" value={busca} onChange={(e) => setBusca(e.target.value)} />
        </div>
        {filtro && (
          <div className="campo cad-filtro-largo">
            <label htmlFor={`${idBusca}-filtro`}>{filtro.rotulo}</label>
            <select id={`${idBusca}-filtro`} value={valorFiltro} onChange={(e) => setValorFiltro(e.target.value)}>
              <option value="">Todos</option>
              {filtro.opcoes.map((o) => (
                <option key={o.valor} value={o.valor}>
                  {o.rotulo}
                </option>
              ))}
            </select>
          </div>
        )}
        <Marcacao id={`${idBusca}-inativos`} marcado={mostrarInativos} aoMudar={setMostrarInativos}>
          Mostrar inativos{inativos > 0 ? ` (${inteiro(inativos)})` : ''}
        </Marcacao>
        {podeEditar && (
          <button
            type="button"
            className="botao botao-primario filtros-fim"
            onClick={() => {
              setErro(null);
              setEdicao({ item: null, formulario: novo() });
            }}
          >
            Novo {nome}
          </button>
        )}
      </div>

      {lista.erro && <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />}
      {!lista.dados && lista.carregando && <Carregando />}
      {lista.dados && filtradas.length === 0 && (
        <Vazio titulo={todos.length === 0 ? `Nenhum ${nome} cadastrado ainda.` : 'Nenhum cadastro com esses filtros.'}>
          {todos.length > 0 ? 'Confira a busca ou marque “Mostrar inativos”.' : undefined}
        </Vazio>
      )}
      {lista.dados && filtradas.length > 0 && (
        <div className={lista.carregando ? 'recarregando' : undefined}>
          <TabelaOrdenavel
            legenda={`Cadastro de ${nome}`}
            colunas={colunasComAcao}
            linhas={filtradas}
            chaveLinha={(item) => item.id}
            ordemInicial={ordemInicial}
            classeLinha={(item) => [item.ativo ? '' : 'linha-inativa', classeLinha?.(item) ?? ''].filter(Boolean).join(' ') || undefined}
          />
          <p className="contagem">
            {inteiro(filtradas.length)} de {inteiro(todos.length)}
          </p>
        </div>
      )}

      {edicao && (
        <ModalFormulario
          titulo={edicao.item ? `Editar ${nome} ${edicao.item.codigo}` : `Novo ${nome}`}
          largura="larga"
          aoFechar={() => setEdicao(null)}
          aoEnviar={() => void salvar()}
          enviando={enviando}
          erro={erro}
        >
          {campos(
            edicao.formulario,
            (parcial) => setEdicao((atual) => (atual ? { ...atual, formulario: { ...atual.formulario, ...parcial } } : atual)),
            edicao.item,
            todos,
          )}
        </ModalFormulario>
      )}

      {situacao && (
        <Confirmacao
          titulo={situacao.ativo ? `Inativar ${situacao.codigo}?` : `Reativar ${situacao.codigo}?`}
          rotuloConfirmar={situacao.ativo ? 'Inativar' : 'Reativar'}
          perigo={situacao.ativo}
          enviando={enviando}
          aoFechar={() => setSituacao(null)}
          aoConfirmar={() => void trocarSituacao()}
        >
          {situacao.ativo ? (
            <p>
              {efeitoInativar} O cadastro continua guardado (com o histórico) e pode ser reativado quando quiser.
            </p>
          ) : (
            <p>O cadastro volta a aparecer para escolher nas telas.</p>
          )}
          {erro && (
            <p className="erro-formulario" role="alert">
              {erro}
            </p>
          )}
        </Confirmacao>
      )}
    </section>
  );
}
