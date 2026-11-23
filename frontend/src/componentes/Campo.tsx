import type { ReactNode } from 'react';

interface PropsCampo {
  rotulo: string;
  /** id do controle (input, select, textarea) que este rótulo descreve. */
  para: string;
  obrigatorio?: boolean;
  dica?: ReactNode;
  classe?: string;
  children: ReactNode;
}

/** Rótulo em cima, controle embaixo e, se houver, uma dica curta. */
export function Campo({ rotulo, para, obrigatorio = false, dica, classe, children }: PropsCampo) {
  return (
    <div className={`campo ${classe ?? ''}`}>
      <label htmlFor={para}>
        {rotulo}
        {obrigatorio && (
          <span className="obrigatorio" title="Obrigatório" aria-hidden="true">
            {' '}
            *
          </span>
        )}
      </label>
      {children}
      {dica && (
        <span className="dica" id={`${para}-dica`}>
          {dica}
        </span>
      )}
    </div>
  );
}

interface PropsMarcacao {
  id: string;
  marcado: boolean;
  aoMudar: (marcado: boolean) => void;
  children: ReactNode;
  desabilitado?: boolean;
}

/** Caixa de marcar com o texto clicável ao lado. */
export function Marcacao({ id, marcado, aoMudar, children, desabilitado = false }: PropsMarcacao) {
  return (
    <label className="marcacao" htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        checked={marcado}
        disabled={desabilitado}
        onChange={(evento) => aoMudar(evento.target.checked)}
      />
      <span>{children}</span>
    </label>
  );
}
