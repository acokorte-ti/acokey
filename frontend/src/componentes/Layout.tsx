import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useSessao, useUsuario, type Permissoes } from '../lib/sessao';

/*
 * Moldura no padrão visual da AçoKorte (o mesmo do sistema de Manutenção e do EstoqueACK, layout "Bancada"):
 * topo branco com o logo e o usuário, menu lateral claro agrupado, item ativo branco com barra vermelha.
 */

/** Ícones de traço 24×24 (cor = cor do texto). */
const ICONES = {
  // Quadro com três colunas (o painel é um kanban)
  painel: <path d="M4 4h4v14H4zM10 4h4v9h-4zM16 4h4v16h-4z" />,
  usuarios: (
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5a6.5 6.5 0 0 1 3.5 5.5" />
    </>
  ),
  auditoria: (
    <>
      <path d="M12 3 4 6v6c0 4.4 3.4 7.8 8 9 4.6-1.2 8-4.6 8-9V6z" />
      <path d="M8.5 12l2.5 2.5 4.5-5" />
    </>
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  fechar: <path d="M6 6l12 12M18 6 6 18" />,
  sair: (
    <>
      <path d="M14 4h5a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-5" />
      <path d="M10 16l-4-4 4-4M6 12h10" />
    </>
  ),
  conta: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
} as const;

type NomeIcone = keyof typeof ICONES;

export function Icone({ nome }: { nome: NomeIcone }) {
  return (
    <svg className="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {ICONES[nome]}
    </svg>
  );
}

interface ItemMenu {
  para: string;
  rotulo: string;
  icone: NomeIcone;
  visivel: (pode: Permissoes) => boolean;
  /** Só marca como atual no endereço exato (a raiz "/" casaria com tudo). */
  exato?: boolean;
}

interface GrupoMenu {
  titulo: string;
  itens: ItemMenu[];
}

const GRUPOS: GrupoMenu[] = [
  {
    titulo: 'Lotes',
    itens: [{ para: '/', rotulo: 'Painel', icone: 'painel', visivel: () => true, exato: true }],
  },
  {
    titulo: 'Administração',
    itens: [
      { para: '/auditoria', rotulo: 'Auditoria', icone: 'auditoria', visivel: (p) => p.auditoria },
      { para: '/usuarios', rotulo: 'Usuários', icone: 'usuarios', visivel: (p) => p.admin },
    ],
  },
];

function iniciais(nome: string): string {
  const partes = nome.trim().split(/\s+/).filter(Boolean);
  return ((partes[0]?.[0] ?? '') + (partes.length > 1 ? (partes[partes.length - 1]?.[0] ?? '') : '')).toUpperCase() || '?';
}

/** Moldura das telas: topo, menu lateral (vira gaveta em tela estreita) e a área de conteúdo. */
export function Layout({ children }: { children: ReactNode }) {
  const { pode, sair } = useSessao();
  const usuario = useUsuario();
  const [menuAberto, setMenuAberto] = useState(false);
  const botaoFechar = useRef<HTMLButtonElement>(null);
  const local = useLocation();

  // Em tela estreita o menu cobre o conteúdo: fecha ao navegar e com Esc
  useEffect(() => setMenuAberto(false), [local.pathname]);
  useEffect(() => {
    if (!menuAberto) return;
    botaoFechar.current?.focus();
    function tecla(evento: KeyboardEvent) {
      if (evento.key === 'Escape') setMenuAberto(false);
    }
    document.addEventListener('keydown', tecla);
    return () => document.removeEventListener('keydown', tecla);
  }, [menuAberto]);

  const grupos = GRUPOS.map((g) => ({ ...g, itens: g.itens.filter((i) => i.visivel(pode)) })).filter((g) => g.itens.length > 0);
  // Abaixo do nome vai o cargo; sem cargo cadastrado, o que a pessoa é no sistema
  const papel = usuario.cargo.trim() || (usuario.admin ? 'Administrador' : 'Usuário');

  return (
    <div className="moldura">
      <a href="#conteudo" className="pular">
        Pular para o conteúdo
      </a>

      <header className="topo">
        <button
          type="button"
          className="icone-botao abrir-menu"
          aria-expanded={menuAberto}
          aria-controls="lateral"
          aria-label="Abrir menu"
          onClick={() => setMenuAberto(true)}
        >
          <Icone nome="menu" />
        </button>
        <Link to="/" className="topo-marca" aria-label="AçoKey Q, ir para o início">
          <img src="/logo-acokorte.png" alt="AçoKorte" width={138} height={28} />
          <span className="topo-sistema">AçoKey Q</span>
        </Link>
        <span className="topo-espaco" />
        <Link to="/conta" className="topo-usuario" title="Minha conta: trocar a senha">
          <span className="avatar" aria-hidden="true">
            {iniciais(usuario.nome)}
          </span>
          <span className="topo-usuario-texto">
            <strong>{usuario.nome}</strong>
            <small>{papel}</small>
          </span>
        </Link>
        <button type="button" className="botao botao-fantasma botao-pequeno topo-sair" onClick={() => void sair()}>
          <Icone nome="sair" />
          Sair
        </button>
      </header>

      <aside id="lateral" className={`lateral ${menuAberto ? 'lateral-aberta' : ''}`} aria-label="Menu">
        <div className="lateral-topo">
          <strong>Menu</strong>
          <button ref={botaoFechar} type="button" className="icone-botao" aria-label="Fechar menu" onClick={() => setMenuAberto(false)}>
            <Icone nome="fechar" />
          </button>
        </div>
        <nav aria-label="Principal">
          {grupos.map((g) => (
            <div key={g.titulo} className="grupo-menu">
              <p className="grupo-titulo">{g.titulo}</p>
              <ul>
                {g.itens.map((item) => (
                  <li key={item.para}>
                    <NavLink to={item.para} end={item.exato} className="item-menu" title={item.rotulo}>
                      <Icone nome={item.icone} />
                      <span className="rotulo-menu">{item.rotulo}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="lateral-rodape">
          <Link to="/conta" className="item-menu">
            <Icone nome="conta" />
            <span className="rotulo-menu">Minha conta</span>
          </Link>
          <button type="button" className="item-menu" onClick={() => void sair()}>
            <Icone nome="sair" />
            <span className="rotulo-menu">Sair</span>
          </button>
        </div>
      </aside>
      {menuAberto && <div className="lateral-fundo" onClick={() => setMenuAberto(false)} aria-hidden="true" />}

      <main id="conteudo" className="conteudo" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
