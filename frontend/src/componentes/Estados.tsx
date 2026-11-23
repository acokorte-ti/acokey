import { useEffect, type ReactNode } from 'react';

/** Estados de tela: carregando, vazio e erro. */

export function Carregando({ texto = 'Carregando…' }: { texto?: string }) {
  return (
    <div className="estado" role="status">
      <span className="girador" aria-hidden="true" />
      <span>{texto}</span>
    </div>
  );
}

export function Vazio({ titulo, children }: { titulo: string; children?: ReactNode }) {
  return (
    <div className="estado estado-vazio">
      <strong>{titulo}</strong>
      {children && <span>{children}</span>}
    </div>
  );
}

export function ErroCarga({ mensagem, aoTentar }: { mensagem: string; aoTentar?: () => void }) {
  return (
    <div className="estado estado-erro" role="alert">
      <strong>Não foi possível carregar.</strong>
      <span>{mensagem}</span>
      {aoTentar && (
        <button type="button" className="botao" onClick={aoTentar}>
          Tentar de novo
        </button>
      )}
    </div>
  );
}

/** Faixa de aviso dentro da página (pendência, informação, erro de formulário). */
export function Faixa({
  tipo,
  children,
  papel,
}: {
  tipo: 'info' | 'alerta' | 'erro' | 'sucesso';
  children: ReactNode;
  papel?: 'alert' | 'status' | 'note';
}) {
  const icone = tipo === 'alerta' || tipo === 'erro' ? '!' : tipo === 'sucesso' ? '✓' : 'i';
  return (
    <div className={`faixa faixa-${tipo}`} role={papel}>
      <span className="faixa-icone" aria-hidden="true">
        {icone}
      </span>
      <div className="faixa-texto">{children}</div>
    </div>
  );
}

export function SeloAtivo({ ativo, feminino = false }: { ativo: boolean; feminino?: boolean }) {
  if (ativo) return <span className="selo selo-ok">{feminino ? 'Ativa' : 'Ativo'}</span>;
  return <span className="selo selo-inativo">{feminino ? 'Inativa' : 'Inativo'}</span>;
}

/** Cabeçalho padrão das páginas: título, texto de apoio e ações à direita. */
export function Cabecalho({ titulo, apoio, children }: { titulo: string; apoio?: ReactNode; children?: ReactNode }) {
  // O título da aba do navegador acompanha a tela
  useEffect(() => {
    document.title = `${titulo} · AçoKey Q`;
  }, [titulo]);

  return (
    <header className="cabecalho">
      <div>
        <h1>{titulo}</h1>
        {apoio && <p className="apoio">{apoio}</p>}
      </div>
      {children && <div className="cabecalho-acoes">{children}</div>}
    </header>
  );
}
