import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useSessao, useUsuario, type Permissoes } from '../lib/sessao';
import { BuscaGlobal } from './BuscaGlobal';

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
  inicio: <path d="M3 11.5 12 4l9 7.5M5.5 10v10h13V10M10 20v-6h4v6" />,
  dashboard: (
    <>
      <path d="M4 18a8 8 0 1 1 16 0" />
      <path d="M12 18l4-6" />
    </>
  ),
  gantt: <path d="M4 5h9M7 10h11M5 15h7M10 20h10" />,
  forno: <path d="M12 3c1 3 4 4.5 4 8.5a4 4 0 0 1-8 0c0-2 1-3 1.5-4 .5 1.5 1.5 2 2 2 .5-2-.5-4.5.5-6.5zM5 21h14" />,
  envio: (
    <>
      <path d="M3 7l9-4 9 4v10l-9 4-9-4z" />
      <path d="M3 7l9 4 9-4M12 11v10" />
    </>
  ),
  fatura: (
    <>
      <path d="M6 3h9l3 3v15H6z" />
      <path d="M9 10h6M9 14h6M9 18h3" />
    </>
  ),
  kpis: <path d="M4 20V4M4 20h16M7 15l4-4 3 3 5-6" />,
  materia: (
    <>
      <path d="M4 8l8-4 8 4-8 4z" />
      <path d="M4 8v8l8 4 8-4V8" />
    </>
  ),
  nc: (
    <>
      <path d="M12 3 2 20h20z" />
      <path d="M12 10v4M12 17h.01" />
    </>
  ),
  indicadores: (
    <>
      <path d="M12 3a9 9 0 1 0 9 9h-9z" />
      <path d="M15 3.5A9 9 0 0 1 20.5 9H15z" />
    </>
  ),
  regua: <path d="M3 17 17 3l4 4L7 21zM7 13l2 2M10 10l2 2M13 7l2 2" />,
  equipamento: <path d="M14.5 5.5a4 4 0 0 0-5 5L4 16l4 4 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-3-1-1-3z" />,
  livro: (
    <>
      <path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" />
      <path d="M5 17a3 3 0 0 1 3-3h11" />
    </>
  ),
  especificacao: <path d="M5 4v16M12 4v16M19 4v16M3 8h4M10 15h4M17 10h4" />,
  lista: <path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />,
  fabrica: <path d="M3 21V10l5 3V10l5 3V10l5 3V4h3v17z" />,
  laboratorio: <path d="M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3M7.5 15h9" />,
  engrenagem: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" />
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

// Mesmos grupos e regras de quem vê o quê do menu do sistema antigo (legado/templates_html.py, TEMPLATES["base"])
const todos = () => true;
const GRUPOS: GrupoMenu[] = [
  {
    titulo: 'Produção',
    itens: [
      { para: '/inicio', rotulo: 'Início', icone: 'inicio', visivel: todos },
      { para: '/', rotulo: 'Painel de lotes', icone: 'painel', visivel: todos, exato: true },
      { para: '/dashboard', rotulo: 'Dashboard', icone: 'dashboard', visivel: todos },
      { para: '/gantt', rotulo: 'Gantt', icone: 'gantt', visivel: todos },
      { para: '/cargas-tt', rotulo: 'Cargas de TT', icone: 'forno', visivel: (p) => p.tt },
      { para: '/envios', rotulo: 'Envios a prestador', icone: 'envio', visivel: (p) => p.expedicao },
      { para: '/faturamento', rotulo: 'OF - Faturamento', icone: 'fatura', visivel: (p) => p.expedicao },
      { para: '/kpis', rotulo: 'KPIs', icone: 'kpis', visivel: (p) => p.kpis },
    ],
  },
  {
    titulo: 'Qualidade',
    itens: [
      { para: '/materia-prima', rotulo: 'Matéria-prima', icone: 'materia', visivel: (p) => p.qualidade },
      { para: '/nao-conformidades', rotulo: 'Não conformidades', icone: 'nc', visivel: (p) => p.qualidade },
      { para: '/indicadores', rotulo: 'Indicadores', icone: 'indicadores', visivel: (p) => p.qualidade },
      { para: '/verificar-dimensional', rotulo: 'Verificar dimensional', icone: 'regua', visivel: (p) => p.qualidade },
      { para: '/equipamentos', rotulo: 'Equipamentos', icone: 'equipamento', visivel: (p) => p.equipamentos },
      { para: '/databooks', rotulo: 'Databooks', icone: 'livro', visivel: (p) => p.qualidade },
      { para: '/auditoria', rotulo: 'Auditoria', icone: 'auditoria', visivel: (p) => p.auditoria },
    ],
  },
  {
    titulo: 'Cadastros',
    itens: [
      { para: '/especificacoes', rotulo: 'Especificações', icone: 'especificacao', visivel: (p) => p.cadastros || p.qualidade },
      { para: '/ordens-producao', rotulo: 'Ordens de produção', icone: 'lista', visivel: (p) => p.cadastros },
      { para: '/fornecedores-mp', rotulo: 'Fornecedores MP', icone: 'fabrica', visivel: (p) => p.cadastros },
      { para: '/prestadores', rotulo: 'Prestadores', icone: 'laboratorio', visivel: (p) => p.cadastros },
    ],
  },
  {
    titulo: 'Administração',
    itens: [
      { para: '/parametros', rotulo: 'Parâmetros', icone: 'engrenagem', visivel: (p) => p.admin },
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
        <BuscaGlobal />
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
