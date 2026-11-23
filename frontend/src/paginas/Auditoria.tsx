import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Vazio } from '../componentes/Estados';
import { Paginacao } from '../componentes/Tabela';
import { api, consulta } from '../lib/api';
import { dataHoraSistema, inteiro } from '../lib/formato';
import type { ListaAuditoria, ListaLotes, RegistroAuditoria } from '../lib/tipos';
import { useAtrasado, useCarga } from '../lib/useCarga';

const TAMANHO = 50;

/**
 * Nome de cada ação na tela. A chave é o código em minúsculas (a comparação ignora maiúsculas);
 * código que não estiver aqui aparece na tela como veio do servidor.
 */
const ACOES: Record<string, string> = {
  login: 'Entrou',
  login_falha: 'Tentativa de login recusada',
  login_bloqueado: 'Tentativa com o acesso bloqueado',
  tentativa_bloqueada: 'Tentativa bloqueada',
  trocar_senha: 'Trocou a própria senha',
  redefinir_senha: 'Redefiniu a senha de alguém',
  criar: 'Criou',
  alterar: 'Alterou',
  editar: 'Editou',
  excluir: 'Excluiu',
  apagar: 'Apagou',
  aprovar: 'Aprovou',
  reprovar: 'Reprovou',
  avancar: 'Avançou de etapa',
  abrir: 'Abriu',
  decidir: 'Decidiu',
  encerrar: 'Encerrou',
  status: 'Mudou a situação',
  importar: 'Importou',
  enviar: 'Enviou',
  desfazer: 'Desfez',
  gerar_pdf: 'Gerou PDF',
  gerar_docx: 'Gerou documento Word',
};

const ENTIDADES: Record<string, string> = {
  usuario: 'Usuário',
  sessao: 'Sessão',
  lote: 'Lote',
  registro: 'Registro de etapa',
  anexo: 'Anexo',
  nc: 'Não conformidade',
};

/** Ações que significam acesso recusado: aparecem em vermelho. */
const ACOES_RECUSADAS = new Set(['login_falha', 'login_bloqueado', 'tentativa_bloqueada']);
/** Ações em que cada campo dos detalhes pode vir como [antes, depois]. */
const ACOES_DE_MUDANCA = new Set(['alterar', 'editar']);

/** Códigos oferecidos nos filtros antes de aparecerem em algum registro (os mesmos do login e do cadastro de usuários). */
const ACOES_DO_FILTRO = ['LOGIN', 'LOGIN_FALHA', 'LOGIN_BLOQUEADO', 'TROCAR_SENHA', 'REDEFINIR_SENHA', 'CRIAR', 'ALTERAR'];
const ENTIDADES_DO_FILTRO = ['usuario'];

function nomeDaAcao(codigo: string): string {
  return ACOES[codigo.toLowerCase()] ?? codigo;
}

function nomeDaEntidade(codigo: string): string {
  return ENTIDADES[codigo.toLowerCase()] ?? codigo;
}

/** Junta à lista os códigos que ainda não estavam nela; devolve a MESMA lista se não houver novidade. */
function acrescentar(lista: string[], codigos: (string | null)[]): string[] {
  const novos = [...new Set(codigos)].filter((c): c is string => c !== null && c !== '' && !lista.includes(c));
  return novos.length > 0 ? [...lista, ...novos] : lista;
}

/**
 * Opções de um filtro: os códigos esperados mais os que já apareceram nos registros.
 * O que apareceu num registro vale como a grafia certa (o servidor compara o texto exato).
 */
function opcoesDoFiltro(esperados: string[], vistos: string[], nome: (codigo: string) => string) {
  const porChave = new Map<string, string>();
  for (const codigo of [...esperados, ...vistos]) porChave.set(codigo.toLowerCase(), codigo);
  return [...porChave.values()]
    .map((codigo) => ({ codigo, rotulo: nome(codigo) }))
    .sort((a, b) => a.rotulo.localeCompare(b.rotulo, 'pt-BR'));
}

/** "pode_aprovar" -> "Pode aprovar" já ajuda; os mais comuns ganham nome próprio. */
const CAMPOS: Record<string, string> = {
  login: 'Usuário (login)',
  nome: 'Nome',
  cargo: 'Cargo',
  ativo: 'Ativo',
  admin: 'Administrador',
  modulos: 'Módulos',
  pode_aprovar: 'Pode aprovar',
  trocar_senha: 'Senha provisória',
  motivo: 'Motivo',
  antes: 'Antes',
  depois: 'Depois',
  numero: 'Número',
  op: 'OP',
  qtd: 'Quantidade',
  coditem: 'Item (CODITEM)',
};

function nomeDoCampo(chave: string): string {
  const conhecido = CAMPOS[chave];
  if (conhecido) return conhecido;
  const texto = chave.replace(/_/g, ' ');
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

function Valor({ valor }: { valor: unknown }): ReactNode {
  if (valor === null || valor === undefined || valor === '') return <span className="automatico-vazio">vazio</span>;
  if (typeof valor === 'boolean') return valor ? 'sim' : 'não';
  if (typeof valor === 'string' || typeof valor === 'number') return String(valor);
  // Listas e objetos: JSON indentado, legível
  return <pre className="json">{JSON.stringify(valor, null, 2)}</pre>;
}

/** Detalhes gravados em JSON. Nas alterações cada campo pode vir como [antes, depois]. */
function Detalhes({ registro }: { registro: RegistroAuditoria }) {
  const detalhes = registro.detalhes;
  if (!detalhes || Object.keys(detalhes).length === 0) return <span className="automatico-vazio">sem detalhes</span>;
  const ehAlteracao = ACOES_DE_MUDANCA.has(registro.acao.toLowerCase());
  return (
    <dl className="detalhes">
      {Object.entries(detalhes).map(([chave, valor]) => {
        const mudanca = ehAlteracao && Array.isArray(valor) && valor.length === 2;
        return (
          <div key={chave}>
            <dt>{nomeDoCampo(chave)}</dt>
            <dd>
              {mudanca ? (
                <span className="mudanca">
                  <span className="mudanca-antes">
                    <span className="so-leitor">antes: </span>
                    <Valor valor={(valor as unknown[])[0]} />
                  </span>
                  <span aria-hidden="true">→</span>
                  <span className="mudanca-depois">
                    <span className="so-leitor">depois: </span>
                    <Valor valor={(valor as unknown[])[1]} />
                  </span>
                </span>
              ) : (
                <Valor valor={valor} />
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export function Auditoria() {
  const [de, setDe] = useState('');
  const [ate, setAte] = useState('');
  const [login, setLogin] = useState('');
  const [acao, setAcao] = useState('');
  const [entidade, setEntidade] = useState('');
  const [loteId, setLoteId] = useState('');
  const [pagina, setPagina] = useState(1);
  const [abertos, setAbertos] = useState<Set<number>>(new Set());
  /** Códigos de ação e de entidade que já apareceram em algum registro desde que a tela abriu. */
  const [vistos, setVistos] = useState<{ acoes: string[]; entidades: string[] }>({ acoes: [], entidades: [] });
  const loginParado = useAtrasado(login);

  const lista = useCarga<ListaAuditoria>(
    (sinal) =>
      api(
        `/auditoria${consulta({ de, ate, login: loginParado.trim(), acao, entidade, lote_id: loteId, pagina, tamanho: TAMANHO })}`,
        { sinal },
      ),
    [de, ate, loginParado, acao, entidade, loteId, pagina],
  );
  // Os lotes servem para mostrar o número (em vez do id interno) e para o filtro por lote.
  // Se esta busca falhar, a auditoria continua funcionando: só fica sem o filtro e sem o número.
  const lotes = useCarga<ListaLotes>((sinal) => api('/lotes', { sinal }), []);

  const dados = lista.dados;

  useEffect(() => {
    if (!dados) return;
    setVistos((atual) => {
      const acoes = acrescentar(
        atual.acoes,
        dados.itens.map((r) => r.acao),
      );
      const entidades = acrescentar(
        atual.entidades,
        dados.itens.map((r) => r.entidade),
      );
      return acoes === atual.acoes && entidades === atual.entidades ? atual : { acoes, entidades };
    });
  }, [dados]);

  const opcoesAcao = useMemo(() => opcoesDoFiltro(ACOES_DO_FILTRO, vistos.acoes, nomeDaAcao), [vistos.acoes]);
  const opcoesEntidade = useMemo(() => opcoesDoFiltro(ENTIDADES_DO_FILTRO, vistos.entidades, nomeDaEntidade), [vistos.entidades]);

  const lotesOrdenados = useMemo(
    () => [...(lotes.dados?.itens ?? [])].sort((a, b) => b.numero.localeCompare(a.numero, 'pt-BR', { numeric: true })),
    [lotes.dados],
  );
  const numeroDoLote = useMemo(() => new Map(lotesOrdenados.map((l) => [l.id, l.numero])), [lotesOrdenados]);

  function filtrar(acaoFiltro: () => void) {
    acaoFiltro();
    setPagina(1);
  }

  function alternar(id: number) {
    setAbertos((atual) => {
      const novo = new Set(atual);
      if (novo.has(id)) novo.delete(id);
      else novo.add(id);
      return novo;
    });
  }

  function celulaDoLote(registro: RegistroAuditoria): ReactNode {
    if (!registro.lote_id) return '—';
    const numero = numeroDoLote.get(registro.lote_id);
    // Lote que não está mais na lista (ou lista que não carregou): mostra o id interno, sem link
    if (!numero) return <span title="Número interno do lote">#{registro.lote_id}</span>;
    return <Link to={`/lotes/${registro.lote_id}`}>{numero}</Link>;
  }

  const temFiltro = de !== '' || ate !== '' || login !== '' || acao !== '' || entidade !== '' || loteId !== '';

  return (
    <>
      <Cabecalho titulo="Auditoria" apoio="Registro de quem fez o quê, e quando." />

      <div className="filtros" role="search" aria-label="Filtros da auditoria">
        <div className="campo">
          <label htmlFor="aud-de">De</label>
          <input id="aud-de" type="date" max="9999-12-31" value={de} onChange={(e) => filtrar(() => setDe(e.target.value))} />
        </div>
        <div className="campo">
          <label htmlFor="aud-ate">Até</label>
          <input id="aud-ate" type="date" max="9999-12-31" value={ate} onChange={(e) => filtrar(() => setAte(e.target.value))} />
        </div>
        <div className="campo">
          <label htmlFor="aud-login">Usuário (login)</label>
          <input
            id="aud-login"
            type="search"
            className="mono"
            autoCapitalize="off"
            spellCheck={false}
            value={login}
            onChange={(e) => filtrar(() => setLogin(e.target.value))}
          />
        </div>
        <div className="campo">
          <label htmlFor="aud-acao">Ação</label>
          <select id="aud-acao" value={acao} onChange={(e) => filtrar(() => setAcao(e.target.value))}>
            <option value="">Todas</option>
            {opcoesAcao.map((opcao) => (
              <option key={opcao.codigo} value={opcao.codigo}>
                {opcao.rotulo}
              </option>
            ))}
          </select>
        </div>
        <div className="campo">
          <label htmlFor="aud-entidade">Sobre</label>
          <select id="aud-entidade" value={entidade} onChange={(e) => filtrar(() => setEntidade(e.target.value))}>
            <option value="">Tudo</option>
            {opcoesEntidade.map((opcao) => (
              <option key={opcao.codigo} value={opcao.codigo}>
                {opcao.rotulo}
              </option>
            ))}
          </select>
        </div>
        {lotesOrdenados.length > 0 && (
          <div className="campo">
            <label htmlFor="aud-lote">Lote</label>
            <select id="aud-lote" className="mono" value={loteId} onChange={(e) => filtrar(() => setLoteId(e.target.value))}>
              <option value="">Todos</option>
              {lotesOrdenados.map((lote) => (
                <option key={lote.id} value={lote.id}>
                  {lote.numero}
                </option>
              ))}
            </select>
          </div>
        )}
        {temFiltro && (
          <button
            type="button"
            className="botao-link"
            onClick={() =>
              filtrar(() => {
                setDe('');
                setAte('');
                setLogin('');
                setAcao('');
                setEntidade('');
                setLoteId('');
              })
            }
          >
            Limpar filtros
          </button>
        )}
      </div>

      {lista.erro && <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />}
      {!dados && lista.carregando && <Carregando />}
      {dados && dados.itens.length === 0 && (
        <Vazio titulo={temFiltro ? 'Nenhum registro com esses filtros.' : 'Nenhum registro ainda.'} />
      )}
      {dados && dados.itens.length > 0 && (
        <div className={`cartao ${lista.carregando ? 'recarregando' : ''}`} aria-busy={lista.carregando}>
          <p className="contagem">
            {inteiro(dados.total)} {dados.total === 1 ? 'registro' : 'registros'}
          </p>
          <div className="tabela-rolagem">
            <table className="tabela">
              <caption className="so-leitor">Registros de auditoria, do mais recente para o mais antigo</caption>
              <thead>
                <tr>
                  <th scope="col">Quando</th>
                  <th scope="col">Usuário</th>
                  <th scope="col">Ação</th>
                  <th scope="col">Sobre</th>
                  <th scope="col">Id</th>
                  <th scope="col">Lote</th>
                  <th scope="col">IP</th>
                  <th scope="col">Detalhes</th>
                </tr>
              </thead>
              <tbody>
                {dados.itens.map((r) => {
                  const aberto = abertos.has(r.id);
                  const temDetalhes = r.detalhes !== null && Object.keys(r.detalhes).length > 0;
                  return (
                    <Fragment key={r.id}>
                      <tr>
                        <td className="mono">{dataHoraSistema(r.quando)}</td>
                        <td className="mono">{r.login ?? '—'}</td>
                        <td>
                          {ACOES_RECUSADAS.has(r.acao.toLowerCase()) ? (
                            <span className="selo selo-erro">{nomeDaAcao(r.acao)}</span>
                          ) : (
                            nomeDaAcao(r.acao)
                          )}
                        </td>
                        <td>{r.entidade ? nomeDaEntidade(r.entidade) : '—'}</td>
                        <td className="mono">{r.entidade_id ?? '—'}</td>
                        <td className="mono">{celulaDoLote(r)}</td>
                        <td className="mono">{r.ip ?? '—'}</td>
                        <td>
                          {temDetalhes ? (
                            <button
                              type="button"
                              className="botao botao-pequeno"
                              aria-expanded={aberto}
                              aria-controls={`aud-detalhes-${r.id}`}
                              onClick={() => alternar(r.id)}
                            >
                              {aberto ? 'Ocultar' : 'Ver'}
                            </button>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                      {aberto && temDetalhes && (
                        <tr id={`aud-detalhes-${r.id}`} className="linha-detalhes">
                          <td colSpan={8}>
                            <Detalhes registro={r} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Paginacao pagina={pagina} tamanho={TAMANHO} total={dados.total} aoMudar={setPagina} />
        </div>
      )}
    </>
  );
}
