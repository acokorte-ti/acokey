import { useEffect, useId, useRef, type FormEvent, type ReactNode } from 'react';

interface PropsModal {
  titulo: string;
  aoFechar: () => void;
  children: ReactNode;
  largura?: 'normal' | 'larga' | 'muito-larga';
}

/**
 * Janela modal sobre o <dialog> nativo: o navegador prende o foco dentro dela,
 * fecha com Esc e devolve o foco ao botão que abriu.
 */
export function Modal({ titulo, aoFechar, children, largura = 'normal' }: PropsModal) {
  const ref = useRef<HTMLDialogElement>(null);
  const idTitulo = useId();

  useEffect(() => {
    const dialogo = ref.current;
    if (dialogo && !dialogo.open) {
      dialogo.showModal();
      // Sozinho, o navegador poria o foco no "×" (o primeiro botão): quem abre um formulário quer
      // digitar direto no primeiro campo, ou no botão marcado com data-foco-inicial.
      const alvo =
        dialogo.querySelector<HTMLElement>('[data-foco-inicial]') ??
        dialogo.querySelector<HTMLElement>(
          '.modal-corpo input:not(:disabled), .modal-corpo select:not(:disabled), .modal-corpo textarea:not(:disabled)',
        );
      alvo?.focus();
    }
    return () => {
      if (dialogo?.open) dialogo.close();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className={`modal ${largura === 'normal' ? '' : `modal-${largura}`}`}
      aria-labelledby={idTitulo}
      onCancel={(evento) => {
        evento.preventDefault(); // quem fecha é o React (tira o componente da tela)
        aoFechar();
      }}
    >
      <div className="modal-topo">
        <h2 id={idTitulo}>{titulo}</h2>
        <button type="button" className="botao-icone" onClick={aoFechar} aria-label="Fechar">
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}

interface PropsModalFormulario extends PropsModal {
  aoEnviar: () => void;
  enviando: boolean;
  rotuloEnviar?: string;
  /** Mensagem de erro do servidor, mostrada acima dos botões. */
  erro?: string | null;
  perigo?: boolean;
}

/** Modal com formulário: corpo rolável, erro e botões Cancelar / Salvar no rodapé. */
export function ModalFormulario({
  aoEnviar,
  enviando,
  rotuloEnviar = 'Salvar',
  erro,
  perigo = false,
  children,
  ...modal
}: PropsModalFormulario) {
  function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (!enviando) aoEnviar();
  }

  return (
    <Modal {...modal}>
      <form onSubmit={enviar} className="modal-form">
        <div className="modal-corpo">{children}</div>
        {erro && (
          <p className="erro-formulario" role="alert">
            {erro}
          </p>
        )}
        <div className="modal-rodape">
          <button type="button" className="botao" onClick={modal.aoFechar} disabled={enviando}>
            Cancelar
          </button>
          <button type="submit" className={`botao ${perigo ? 'botao-perigo' : 'botao-primario'}`} disabled={enviando}>
            {enviando ? 'Gravando…' : rotuloEnviar}
          </button>
        </div>
      </form>
    </Modal>
  );
}

interface PropsConfirmacao {
  titulo: string;
  children: ReactNode;
  rotuloConfirmar: string;
  aoConfirmar: () => void;
  aoFechar: () => void;
  enviando?: boolean;
  perigo?: boolean;
}

/** Pergunta de confirmação para ações que mexem em dados. */
export function Confirmacao({
  titulo,
  children,
  rotuloConfirmar,
  aoConfirmar,
  aoFechar,
  enviando = false,
  perigo = false,
}: PropsConfirmacao) {
  return (
    <ModalFormulario
      titulo={titulo}
      aoFechar={aoFechar}
      aoEnviar={aoConfirmar}
      enviando={enviando}
      rotuloEnviar={rotuloConfirmar}
      perigo={perigo}
    >
      {children}
    </ModalFormulario>
  );
}
