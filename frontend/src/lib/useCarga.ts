import { useCallback, useEffect, useRef, useState } from 'react';
import { foiCancelada, mensagemDeErro } from './api';

export interface Carga<T> {
  /** Último resultado bom. Durante uma recarga continua sendo o anterior (a tela não pisca). */
  dados: T | null;
  erro: string | null;
  carregando: boolean;
  recarregar: () => void;
  /** Troca os dados sem ir ao servidor (ex.: depois de salvar, com a resposta do próprio PUT). */
  definir: (dados: T) => void;
}

interface Estado<T> {
  dados: T | null;
  erro: string | null;
  carregando: boolean;
}

/**
 * Busca dados quando a tela abre e sempre que as dependências mudam.
 * Cancela a busca anterior se uma nova começar (o resultado velho nunca sobrescreve o novo).
 */
export function useCarga<T>(buscar: (sinal: AbortSignal) => Promise<T>, dependencias: readonly unknown[]): Carga<T> {
  const [estado, setEstado] = useState<Estado<T>>({ dados: null, erro: null, carregando: true });
  const [versao, setVersao] = useState(0);
  const funcao = useRef(buscar);
  funcao.current = buscar;

  useEffect(() => {
    const controle = new AbortController();
    setEstado((atual) => ({ dados: atual.dados, erro: null, carregando: true }));
    funcao.current(controle.signal).then(
      (dados) => {
        if (!controle.signal.aborted) setEstado({ dados, erro: null, carregando: false });
      },
      (erro: unknown) => {
        if (controle.signal.aborted || foiCancelada(erro)) return;
        setEstado({ dados: null, erro: mensagemDeErro(erro), carregando: false });
      },
    );
    return () => controle.abort();
    // As dependências vêm de quem chama (mesmo contrato do useEffect).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencias, versao]);

  const recarregar = useCallback(() => setVersao((v) => v + 1), []);
  const definir = useCallback((dados: T) => setEstado({ dados, erro: null, carregando: false }), []);

  return { ...estado, recarregar, definir };
}

/** Devolve o valor só depois que ele parou de mudar por `espera` ms (busca enquanto digita). */
export function useAtrasado<T>(valor: T, espera = 350): T {
  const [atrasado, setAtrasado] = useState(valor);
  useEffect(() => {
    const id = window.setTimeout(() => setAtrasado(valor), espera);
    return () => window.clearTimeout(id);
  }, [valor, espera]);
  return atrasado;
}
