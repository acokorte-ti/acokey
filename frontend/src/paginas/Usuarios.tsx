import { useMemo, useState } from 'react';
import { Campo, Marcacao } from '../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, SeloAtivo, Vazio } from '../componentes/Estados';
import { ListaRegras } from '../componentes/FormSenha';
import { Modal, ModalFormulario } from '../componentes/Modal';
import { TabelaOrdenavel, type Coluna } from '../componentes/Tabela';
import { api, mensagemDeErro } from '../lib/api';
import { useAvisos } from '../lib/avisos';
import { dataHoraSistema, MODULOS, resumoDoAcesso, TRACO } from '../lib/formato';
import { useSessao, useUsuario } from '../lib/sessao';
import type { Modulo, Usuario, UsuarioAlteracao, UsuarioNovo } from '../lib/tipos';
import { useCarga } from '../lib/useCarga';
import { MiniaturaAssinatura, ModalAssinatura } from './cadastros/AssinaturaUsuario';

/** Senha provisória fácil de ditar: letras e números sem os que se confundem (0/O, 1/l/I). */
function gerarSenha(): string {
  const letras = 'abcdefghjkmnpqrstuvwxyz';
  const numeros = '23456789';
  const sorteio = new Uint32Array(12);
  crypto.getRandomValues(sorteio);
  // Posições 3, 7 e 11 são números; as outras, letras: sempre mistura os dois
  return Array.from(sorteio, (valor, i) => {
    const conjunto = i % 4 === 3 ? numeros : letras;
    return conjunto[valor % conjunto.length];
  }).join('');
}

/** O que o administrador define sobre o acesso de cada pessoa. */
interface Acesso {
  cargo: string;
  admin: boolean;
  modulos: Modulo[];
  pode_aprovar: boolean;
}

type EdicaoNovo = { tipo: 'novo'; login: string; nome: string; senha: string } & Acesso;
type EdicaoAlterar = { tipo: 'alterar'; usuario: Usuario; nome: string; ativo: boolean } & Acesso;
type EdicaoSenha = { tipo: 'senha'; usuario: Usuario; senha: string };
type Edicao = EdicaoNovo | EdicaoAlterar | EdicaoSenha;

function mesmosModulos(a: readonly Modulo[], b: readonly Modulo[]): boolean {
  return a.length === b.length && a.every((modulo) => b.includes(modulo));
}

/** Só o que foi mexido no formulário vai para o servidor (e para a auditoria). */
function mudancas(edicao: EdicaoAlterar): UsuarioAlteracao {
  const antes = edicao.usuario;
  const nome = edicao.nome.trim();
  const cargo = edicao.cargo.trim();
  const corpo: UsuarioAlteracao = {};
  if (nome !== antes.nome) corpo.nome = nome;
  if (cargo !== antes.cargo) corpo.cargo = cargo;
  if (edicao.ativo !== antes.ativo) corpo.ativo = edicao.ativo;
  if (edicao.admin !== antes.admin) corpo.admin = edicao.admin;
  if (!mesmosModulos(edicao.modulos, antes.modulos)) corpo.modulos = edicao.modulos;
  if (edicao.pode_aprovar !== antes.pode_aprovar) corpo.pode_aprovar = edicao.pode_aprovar;
  return corpo;
}

interface PropsCamposAcesso {
  valor: Acesso;
  aoMudar: (mudanca: Partial<Acesso>) => void;
  cargoObrigatorio?: boolean;
}

/** Cargo, administrador, módulos e "pode aprovar": iguais em "Novo usuário" e em "Editar". */
function CamposAcesso({ valor, aoMudar, cargoObrigatorio = false }: PropsCamposAcesso) {
  function alternarModulo(modulo: Modulo, marcado: boolean) {
    const escolhidos = new Set(valor.modulos);
    if (marcado) escolhidos.add(modulo);
    else escolhidos.delete(modulo);
    // Sempre na ordem padrão dos módulos, não na ordem dos cliques
    aoMudar({ modulos: MODULOS.map((m) => m.chave).filter((chave) => escolhidos.has(chave)) });
  }

  return (
    <>
      <Campo rotulo="Cargo" para="usuario-cargo" obrigatorio={cargoObrigatorio} dica="Ex.: Inspetor da Qualidade">
        <input
          id="usuario-cargo"
          type="text"
          required={cargoObrigatorio}
          maxLength={80}
          value={valor.cargo}
          onChange={(e) => aoMudar({ cargo: e.target.value })}
        />
      </Campo>
      <Marcacao id="usuario-admin" marcado={valor.admin} aoMudar={(admin) => aoMudar({ admin })}>
        Administrador <span className="sub-linha">(cadastra usuários e vê a auditoria)</span>
      </Marcacao>
      <fieldset className="grupo-marcacoes">
        <legend>Módulos que acessa</legend>
        {MODULOS.map((modulo) => (
          <Marcacao
            key={modulo.chave}
            id={`usuario-modulo-${modulo.chave}`}
            marcado={valor.modulos.includes(modulo.chave)}
            aoMudar={(marcado) => alternarModulo(modulo.chave, marcado)}
          >
            {modulo.rotulo}
          </Marcacao>
        ))}
        <span className="dica">TT = tratamento térmico.</span>
      </fieldset>
      <Marcacao id="usuario-aprova" marcado={valor.pode_aprovar} aoMudar={(pode_aprovar) => aoMudar({ pode_aprovar })}>
        Pode aprovar <span className="sub-linha">(assina relatórios como “Aprovado por” e decide desvios)</span>
      </Marcacao>
    </>
  );
}

function CampoSenhaProvisoria({ senha, aoMudar }: { senha: string; aoMudar: (senha: string) => void }) {
  return (
    <>
      <Campo
        rotulo="Senha provisória"
        para="usuario-senha"
        obrigatorio
        dica="Passe esta senha para a pessoa: no primeiro acesso o sistema obriga a trocar por uma senha só dela."
      >
        <div className="campo-com-botao">
          <input
            id="usuario-senha"
            type="text"
            className="mono"
            autoComplete="off"
            spellCheck={false}
            required
            maxLength={200}
            value={senha}
            onChange={(e) => aoMudar(e.target.value)}
          />
          <button type="button" className="botao" onClick={() => aoMudar(gerarSenha())}>
            Gerar
          </button>
        </div>
      </Campo>
      <ListaRegras senha={senha} />
    </>
  );
}

export function Usuarios() {
  const eu = useUsuario();
  const { atualizarUsuario } = useSessao();
  const avisos = useAvisos();
  const lista = useCarga<Usuario[]>((sinal) => api('/usuarios', { sinal }), []);
  const [edicao, setEdicao] = useState<Edicao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  /** Depois de criar ou redefinir: a senha provisória fica na tela até o administrador anotar. */
  const [entrega, setEntrega] = useState<{ login: string; nome: string; senha: string } | null>(null);
  const [copiada, setCopiada] = useState(false);
  /** Assinatura digital: de quem está sendo trocada, e um número que muda a cada troca (a imagem não fica velha). */
  const [assinando, setAssinando] = useState<Usuario | null>(null);
  const [versaoAssinatura, setVersaoAssinatura] = useState(() => Date.now());

  async function copiarSenha(senha: string) {
    try {
      await navigator.clipboard.writeText(senha);
      setCopiada(true);
    } catch {
      avisos.info('Não foi possível copiar sozinho: selecione a senha e copie.');
    }
  }

  function abrir(nova: Edicao) {
    setErro(null);
    setEdicao(nova);
  }

  const colunas = useMemo<Coluna<Usuario>[]>(
    () => [
      {
        chave: 'nome',
        titulo: 'Nome',
        valor: (u) => u.nome,
        celula: (u) => (
          <>
            {u.nome}
            {u.id === eu.id && <span className="sub-linha"> (você)</span>}
          </>
        ),
      },
      { chave: 'login', titulo: 'Usuário', mono: true, valor: (u) => u.login },
      { chave: 'cargo', titulo: 'Cargo', valor: (u) => u.cargo, celula: (u) => u.cargo.trim() || TRACO },
      {
        chave: 'acesso',
        titulo: 'Acesso',
        dica: 'Administrador e módulos liberados',
        valor: (u) => resumoDoAcesso(u),
      },
      {
        chave: 'aprova',
        titulo: 'Pode aprovar',
        dica: 'Assina relatórios como “Aprovado por” e decide desvios',
        valor: (u) => u.pode_aprovar,
      },
      {
        chave: 'assinatura',
        titulo: 'Assinatura',
        dica: 'Tem a imagem da assinatura digital cadastrada',
        valor: (u) => u.tem_assinatura,
        celula: (u) => (u.tem_assinatura ? <MiniaturaAssinatura usuario={u} versao={versaoAssinatura} /> : TRACO),
      },
      {
        chave: 'situacao',
        titulo: 'Situação',
        valor: (u) => u.ativo,
        celula: (u) => (
          <>
            <SeloAtivo ativo={u.ativo} />
            {u.bloqueado && (
              <span className="selo selo-erro selo-colado" title="Muitas tentativas de senha errada.">
                Bloqueado
              </span>
            )}
            {u.trocar_senha && u.ativo && <span className="selo selo-alerta selo-colado">Senha provisória</span>}
          </>
        ),
      },
      {
        chave: 'ultimo',
        titulo: 'Último acesso',
        mono: true,
        valor: (u) => u.ultimo_login_em,
        celula: (u) => (u.ultimo_login_em ? dataHoraSistema(u.ultimo_login_em) : 'nunca entrou'),
      },
      {
        chave: '_acoes',
        titulo: 'Ações',
        ordenavel: false,
        valor: () => null,
        celula: (u) => (
          <span className="acoes-linha">
            <button
              type="button"
              className="botao botao-pequeno"
              onClick={() =>
                abrir({
                  tipo: 'alterar',
                  usuario: u,
                  nome: u.nome,
                  ativo: u.ativo,
                  cargo: u.cargo,
                  admin: u.admin,
                  modulos: u.modulos,
                  pode_aprovar: u.pode_aprovar,
                })
              }
            >
              Editar
            </button>
            <button type="button" className="botao botao-pequeno" onClick={() => abrir({ tipo: 'senha', usuario: u, senha: '' })}>
              Redefinir senha
            </button>
            <button type="button" className="botao botao-pequeno" onClick={() => setAssinando(u)}>
              Assinatura
            </button>
          </span>
        ),
      },
    ],
    [eu.id, versaoAssinatura],
  );

  async function salvar() {
    if (!edicao) return;
    setErro(null);
    setEnviando(true);
    try {
      if (edicao.tipo === 'novo') {
        const corpo: UsuarioNovo = {
          login: edicao.login.trim(),
          nome: edicao.nome.trim(),
          cargo: edicao.cargo.trim(),
          senha: edicao.senha,
          admin: edicao.admin,
          modulos: edicao.modulos,
          pode_aprovar: edicao.pode_aprovar,
        };
        const criado = await api<Usuario>('/usuarios', { metodo: 'POST', corpo });
        avisos.sucesso(`Usuário ${criado.login} criado.`);
        setCopiada(false);
        setEntrega({ login: criado.login, nome: criado.nome, senha: edicao.senha });
      } else if (edicao.tipo === 'alterar') {
        const corpo = mudancas(edicao);
        if (Object.keys(corpo).length === 0) {
          avisos.info('Nada foi alterado.');
          setEdicao(null);
          return;
        }
        const alterado = await api<Usuario>(`/usuarios/${edicao.usuario.id}`, { metodo: 'PATCH', corpo });
        avisos.sucesso('Usuário alterado.');
        // Mexeu no próprio cadastro: o topo e o menu acompanham na hora
        if (alterado.id === eu.id) atualizarUsuario(alterado);
      } else {
        await api<Usuario>(`/usuarios/${edicao.usuario.id}/senha`, { metodo: 'POST', corpo: { senha: edicao.senha } });
        avisos.sucesso(`Senha de ${edicao.usuario.login} redefinida.`);
        setCopiada(false);
        setEntrega({ login: edicao.usuario.login, nome: edicao.usuario.nome, senha: edicao.senha });
      }
      setEdicao(null);
      lista.recarregar();
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <Cabecalho titulo="Usuários" apoio="Quem pode entrar no sistema e o que cada um pode fazer.">
        <button
          type="button"
          className="botao botao-primario"
          onClick={() =>
            abrir({
              tipo: 'novo',
              login: '',
              nome: '',
              senha: gerarSenha(),
              cargo: '',
              admin: false,
              modulos: [],
              pode_aprovar: false,
            })
          }
        >
          Novo usuário
        </button>
      </Cabecalho>

      {lista.erro && <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />}
      {!lista.dados && lista.carregando && <Carregando />}
      {lista.dados && lista.dados.length === 0 && <Vazio titulo="Nenhum usuário cadastrado." />}
      {lista.dados && lista.dados.length > 0 && (
        <div className={`cartao ${lista.carregando ? 'recarregando' : ''}`}>
          <TabelaOrdenavel
            legenda="Usuários do sistema"
            colunas={colunas}
            linhas={lista.dados}
            chaveLinha={(u) => u.id}
            classeLinha={(u) => (u.ativo ? undefined : 'linha-inativa')}
          />
        </div>
      )}

      {edicao?.tipo === 'novo' && (
        <ModalFormulario
          titulo="Novo usuário"
          aoFechar={() => setEdicao(null)}
          aoEnviar={() => void salvar()}
          enviando={enviando}
          erro={erro}
          rotuloEnviar="Criar usuário"
        >
          <Campo rotulo="Nome completo" para="usuario-nome" obrigatorio>
            <input
              id="usuario-nome"
              type="text"
              required
              minLength={2}
              maxLength={120}
              autoFocus
              value={edicao.nome}
              onChange={(e) => setEdicao({ ...edicao, nome: e.target.value })}
            />
          </Campo>
          <Campo rotulo="Usuário (login)" para="usuario-login" obrigatorio dica="Letras, números, ponto, hífen ou sublinhado. Ex.: joao.silva">
            <input
              id="usuario-login"
              type="text"
              className="mono"
              required
              minLength={3}
              maxLength={60}
              pattern="[a-zA-Z0-9._\-]+"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              value={edicao.login}
              onChange={(e) => setEdicao({ ...edicao, login: e.target.value })}
            />
          </Campo>
          <CamposAcesso valor={edicao} aoMudar={(mudanca) => setEdicao({ ...edicao, ...mudanca })} cargoObrigatorio />
          <CampoSenhaProvisoria senha={edicao.senha} aoMudar={(senha) => setEdicao({ ...edicao, senha })} />
        </ModalFormulario>
      )}

      {edicao?.tipo === 'alterar' && (
        <ModalFormulario
          titulo={`Editar ${edicao.usuario.login}`}
          aoFechar={() => setEdicao(null)}
          aoEnviar={() => void salvar()}
          enviando={enviando}
          erro={erro}
        >
          <Campo rotulo="Nome completo" para="usuario-nome" obrigatorio>
            <input
              id="usuario-nome"
              type="text"
              required
              minLength={2}
              maxLength={120}
              autoFocus
              value={edicao.nome}
              onChange={(e) => setEdicao({ ...edicao, nome: e.target.value })}
            />
          </Campo>
          <CamposAcesso valor={edicao} aoMudar={(mudanca) => setEdicao({ ...edicao, ...mudanca })} />
          <Marcacao id="usuario-ativo" marcado={edicao.ativo} aoMudar={(ativo) => setEdicao({ ...edicao, ativo })}>
            Ativo <span className="sub-linha">(pode entrar no sistema)</span>
          </Marcacao>
        </ModalFormulario>
      )}

      {edicao?.tipo === 'senha' && (
        <ModalFormulario
          titulo={`Redefinir a senha de ${edicao.usuario.login}`}
          aoFechar={() => setEdicao(null)}
          aoEnviar={() => void salvar()}
          enviando={enviando}
          erro={erro}
          rotuloEnviar="Redefinir senha"
        >
          <p>{edicao.usuario.nome} vai precisar desta senha provisória para entrar e escolher uma senha nova.</p>
          <CampoSenhaProvisoria senha={edicao.senha} aoMudar={(senha) => setEdicao({ ...edicao, senha })} />
        </ModalFormulario>
      )}

      {entrega && (
        <Modal titulo="Entregue a senha provisória" aoFechar={() => setEntrega(null)}>
          <div className="modal-corpo">
            <p>
              Passe estes dados para <strong>{entrega.nome}</strong>. No primeiro acesso o sistema obriga a trocar por uma
              senha só dela. Depois de fechar esta janela a senha não aparece mais.
            </p>
            <dl className="ficha">
              <div>
                <dt>Usuário</dt>
                <dd className="mono">{entrega.login}</dd>
              </div>
              <div>
                <dt>Senha provisória</dt>
                <dd className="mono senha-entrega">{entrega.senha}</dd>
              </div>
            </dl>
          </div>
          <div className="modal-rodape">
            <button type="button" className="botao" data-foco-inicial onClick={() => void copiarSenha(entrega.senha)}>
              {copiada ? 'Copiada ✓' : 'Copiar senha'}
            </button>
            <button type="button" className="botao botao-primario" onClick={() => setEntrega(null)}>
              Já anotei
            </button>
          </div>
        </Modal>
      )}

      {assinando && (
        <ModalAssinatura
          usuario={assinando}
          versao={versaoAssinatura}
          aoFechar={() => setAssinando(null)}
          aoMudar={(alterado) => {
            setAssinando(null);
            setVersaoAssinatura(Date.now());
            if (alterado.id === eu.id) atualizarUsuario(alterado);
            lista.recarregar();
          }}
        />
      )}
    </>
  );
}
