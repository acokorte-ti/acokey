import { useState, type ReactNode } from 'react';
import { Campo } from '../../componentes/Campo';
import { ModalFormulario } from '../../componentes/Modal';
import { mensagemDeErro } from '../../lib/api';

interface Props {
  titulo: string;
  children?: ReactNode;
  rotulo?: string;
  rotuloConfirmar: string;
  perigo?: boolean;
  aoFechar: () => void;
  /** Grava; se der erro, a mensagem aparece na janela. */
  aoConfirmar: (motivo: string) => Promise<void>;
}

/** Confirmação de ação que exige motivo escrito (cancelar, reabrir, remover): fica na auditoria. */
export function ModalMotivo({ titulo, children, rotulo = 'Motivo', rotuloConfirmar, perigo = false, aoFechar, aoConfirmar }: Props) {
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function confirmar() {
    if (motivo.trim().length < 3) {
      setErro('Escreva o motivo (pelo menos 3 letras).');
      return;
    }
    setErro(null);
    setEnviando(true);
    try {
      await aoConfirmar(motivo.trim());
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setEnviando(false);
    }
  }

  return (
    <ModalFormulario titulo={titulo} aoFechar={aoFechar} aoEnviar={() => void confirmar()} enviando={enviando} erro={erro}
      rotuloEnviar={rotuloConfirmar} perigo={perigo}>
      {children}
      <Campo rotulo={rotulo} para="motivo-texto" obrigatorio dica="Fica registrado na auditoria, com o seu usuário.">
        <textarea id="motivo-texto" rows={3} required minLength={3} maxLength={2000} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
      </Campo>
    </ModalFormulario>
  );
}
