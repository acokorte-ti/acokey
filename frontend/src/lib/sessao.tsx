import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, definirCsrf, registrarTratadores } from './api';
import type { Modulo, RespostaSessao, Usuario } from './tipos';

/**
 * O que o usuário pode abrir (o backend recusa de qualquer forma; aqui é só para esconder).
 * As combinações seguem o menu do sistema antigo (legado/templates_html.py, TEMPLATES["base"]).
 * O administrador enxerga todos os módulos (igual ao backend), mas NÃO ganha "pode aprovar".
 */
export interface Permissoes {
  /** Usuários e parâmetros do sistema. */
  admin: boolean;
  /** Pode assinar relatórios como "Aprovado por" e decidir desvios (uso como está, anulação). */
  aprovador: boolean;
  qualidade: boolean;
  pcp: boolean;
  producaoTT: boolean;
  producaoUsinagem: boolean;
  cadastros: boolean;
  /** Auditoria: Qualidade. */
  auditoria: boolean;
  /** Cargas de TT e relatório de tratamento térmico: Produção TT ou Qualidade. */
  tt: boolean;
  /** Envios a prestador e Ordem de Faturamento: Qualidade, Produção TT ou Produção Usinagem. */
  expedicao: boolean;
  /** KPIs: Qualidade ou Produção TT. */
  kpis: boolean;
  /** Equipamentos: Qualidade ou Cadastros. */
  equipamentos: boolean;
}

/** O usuário tem este módulo liberado? O administrador tem todos. */
export function temModulo(usuario: Usuario | null, modulo: Modulo): boolean {
  return usuario !== null && (usuario.admin || usuario.modulos.includes(modulo));
}

export function permissoesDe(usuario: Usuario | null): Permissoes {
  const m = (modulo: Modulo) => temModulo(usuario, modulo);
  const qualidade = m('qualidade');
  const producaoTT = m('producao_tt');
  const producaoUsinagem = m('producao_usinagem');
  const cadastros = m('cadastros');
  return {
    admin: usuario?.admin === true,
    aprovador: usuario?.pode_aprovar === true,
    qualidade,
    pcp: m('pcp'),
    producaoTT,
    producaoUsinagem,
    cadastros,
    auditoria: qualidade,
    tt: qualidade || producaoTT,
    expedicao: qualidade || producaoTT || producaoUsinagem,
    kpis: qualidade || producaoTT,
    equipamentos: qualidade || cadastros,
  };
}

interface ValorSessao {
  /** true só enquanto a primeira consulta a /auth/eu não voltou. */
  carregando: boolean;
  usuario: Usuario | null;
  pode: Permissoes;
  entrar: (login: string, senha: string) => Promise<void>;
  sair: () => Promise<void>;
  /** Depois de trocar a senha o backend devolve o usuário atualizado. */
  atualizarUsuario: (usuario: Usuario) => void;
}

const ContextoSessao = createContext<ValorSessao | null>(null);

export function ProvedorSessao({ children }: { children: ReactNode }) {
  const [carregando, setCarregando] = useState(true);
  const [usuario, setUsuario] = useState<Usuario | null>(null);

  useEffect(() => {
    registrarTratadores({
      aoPerderSessao: () => {
        definirCsrf(null);
        setUsuario(null);
      },
      aoExigirTrocaSenha: () => {
        setUsuario((atual) => (atual ? { ...atual, trocar_senha: true } : atual));
      },
    });

    const controle = new AbortController();
    api<RespostaSessao>('/auth/eu', { sinal: controle.signal })
      .then((resposta) => {
        definirCsrf(resposta.csrf);
        setUsuario(resposta.usuario);
      })
      .catch(() => {
        // sem sessão (401) ou servidor fora do ar: mostra o login
      })
      .finally(() => {
        if (!controle.signal.aborted) setCarregando(false);
      });
    return () => controle.abort();
  }, []);

  const entrar = useCallback(async (login: string, senha: string) => {
    const resposta = await api<RespostaSessao>('/auth/login', {
      metodo: 'POST',
      corpo: { login, senha },
      semTratarSessao: true,
    });
    definirCsrf(resposta.csrf);
    setUsuario(resposta.usuario);
  }, []);

  const sair = useCallback(async () => {
    try {
      await api<{ ok: boolean }>('/auth/logout', { metodo: 'POST', semTratarSessao: true });
    } catch {
      // mesmo que o servidor não responda, a tela volta para o login
    }
    definirCsrf(null);
    setUsuario(null);
  }, []);

  const valor = useMemo<ValorSessao>(
    () => ({
      carregando,
      usuario,
      pode: permissoesDe(usuario),
      entrar,
      sair,
      atualizarUsuario: setUsuario,
    }),
    [carregando, usuario, entrar, sair],
  );

  return <ContextoSessao.Provider value={valor}>{children}</ContextoSessao.Provider>;
}

export function useSessao(): ValorSessao {
  const valor = useContext(ContextoSessao);
  if (!valor) throw new Error('useSessao precisa estar dentro de <ProvedorSessao>.');
  return valor;
}

/** Usuário logado; só pode ser usado nas telas que ficam atrás do login. */
export function useUsuario(): Usuario {
  const { usuario } = useSessao();
  if (!usuario) throw new Error('Tela usada sem usuário logado.');
  return usuario;
}
