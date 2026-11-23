import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';

type TipoAviso = 'sucesso' | 'erro' | 'info';

interface Aviso {
  id: number;
  tipo: TipoAviso;
  texto: string;
}

interface ValorAvisos {
  sucesso: (texto: string) => void;
  erro: (texto: string) => void;
  info: (texto: string) => void;
}

const ContextoAvisos = createContext<ValorAvisos | null>(null);

const DURACAO_MS: Record<TipoAviso, number> = { sucesso: 4500, info: 6000, erro: 9000 };
const ICONE: Record<TipoAviso, string> = { sucesso: '✓', erro: '!', info: 'i' };
const NOME: Record<TipoAviso, string> = { sucesso: 'Sucesso', erro: 'Erro', info: 'Aviso' };

/** Avisos rápidos ("toasts") no canto da tela, lidos também por leitores de tela. */
export function ProvedorAvisos({ children }: { children: ReactNode }) {
  const [avisos, setAvisos] = useState<Aviso[]>([]);
  const proximoId = useRef(1);

  const fechar = useCallback((id: number) => {
    setAvisos((lista) => lista.filter((a) => a.id !== id));
  }, []);

  const abrir = useCallback(
    (tipo: TipoAviso, texto: string) => {
      const id = proximoId.current++;
      // No máximo 4 na tela; o mais antigo sai
      setAvisos((lista) => [...lista.slice(-3), { id, tipo, texto }]);
      window.setTimeout(() => fechar(id), DURACAO_MS[tipo]);
    },
    [fechar],
  );

  const valor = useMemo<ValorAvisos>(
    () => ({
      sucesso: (texto) => abrir('sucesso', texto),
      erro: (texto) => abrir('erro', texto),
      info: (texto) => abrir('info', texto),
    }),
    [abrir],
  );

  return (
    <ContextoAvisos.Provider value={valor}>
      {children}
      <div className="avisos" role="region" aria-label="Avisos">
        {avisos.map((aviso) => (
          <div
            key={aviso.id}
            className={`aviso aviso-${aviso.tipo}`}
            role={aviso.tipo === 'erro' ? 'alert' : 'status'}
          >
            <span className="aviso-icone" aria-hidden="true">
              {ICONE[aviso.tipo]}
            </span>
            <span className="aviso-texto">
              <span className="so-leitor">{NOME[aviso.tipo]}: </span>
              {aviso.texto}
            </span>
            <button type="button" className="aviso-fechar" onClick={() => fechar(aviso.id)} aria-label="Fechar aviso">
              ×
            </button>
          </div>
        ))}
      </div>
    </ContextoAvisos.Provider>
  );
}

export function useAvisos(): ValorAvisos {
  const valor = useContext(ContextoAvisos);
  if (!valor) throw new Error('useAvisos precisa estar dentro de <ProvedorAvisos>.');
  return valor;
}
