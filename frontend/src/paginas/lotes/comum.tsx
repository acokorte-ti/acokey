/** Peças usadas pela página do lote e pela página da etapa. */
import { useState } from 'react';
import { Campo } from '../../componentes/Campo';
import { ModalFormulario } from '../../componentes/Modal';
import { api, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { useSessao } from '../../lib/sessao';
import type { AnexoEtapa } from '../../lib/tipos';

/** Registrar, anexar, aprovar por documento, avançar e importar: Qualidade, PCP ou Produção (o backend confere de novo). */
export function usePodeRegistrar(): boolean {
  const { pode } = useSessao();
  return pode.qualidade || pode.pcp || pode.producaoTT || pode.producaoUsinagem;
}

/** Remover anexo pede o motivo: nada é apagado, o anexo só sai da etapa e do databook. */
export function ModalRemoverAnexo({ anexo, aoFechar, aoRemover }: { anexo: AnexoEtapa; aoFechar: () => void; aoRemover: () => void }) {
  const avisos = useAvisos();
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function remover() {
    if (motivo.trim().length < 3) {
      setErro('Escreva o motivo da remoção.');
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      await api(`/anexos/${anexo.id}/remover`, { metodo: 'POST', corpo: { motivo: motivo.trim() } });
      avisos.sucesso(`Anexo "${anexo.nome}" removido.`);
      aoRemover();
    } catch (e) {
      setErro(mensagemDeErro(e));
      setEnviando(false);
    }
  }

  return (
    <ModalFormulario titulo="Remover anexo" aoFechar={aoFechar} aoEnviar={remover} enviando={enviando} erro={erro} rotuloEnviar="Remover" perigo>
      <p>
        Remover <strong>{anexo.nome}</strong>? Ele sai da etapa e do databook, mas o arquivo continua guardado no sistema, com o seu nome e o motivo.
      </p>
      <Campo rotulo="Motivo" para="remover-motivo" obrigatorio dica="Ex.: arquivo da OP errada, versão sem assinatura.">
        <input id="remover-motivo" type="text" value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={1000} />
      </Campo>
    </ModalFormulario>
  );
}
