import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, definirCsrf, registrarTratadores } from './api';
import type { Modulo, RespostaSessao, Usuario } from './tipos';

/** O que o usuário pode abrir (o backend recusa de qualquer forma; aqui é só para esconder). */
export interface Permissoes {
  /** Tela de usuários: só o administrador. */
  admin: boolean;
  /** Tela de auditoria: administrador ou quem tem o módulo Qualidade. */
  auditoria: boolean;
}

/** O usuário tem este módulo liberado? (o administrador não ganha os módulos automaticamente) */
export function temModulo(usuario: Usuario | null, modulo: Modulo): boolean {
  return usuario !== null && usuario.modulos.includes(modulo);
}

export function permissoesDe(usuario: Usuario | null): Permissoes {
  const admin = usuario?.admin === true;
  return {
    admin,
    auditoria: admin || temModulo(usuario, 'qualidade'),
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
