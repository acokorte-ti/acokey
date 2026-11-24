import { useState } from 'react';
import { Campo } from '../../componentes/Campo';
import { ModalFormulario } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import type { DatabookAEnviar, DatabookEnvio } from './tipos';

interface Props {
  item: DatabookAEnviar;
  /** "AAAA-MM-DD": data de envio sugerida (hoje). */
  hoje: string;
  aoFechar: () => void;
  aoConcluir: (envio: DatabookEnvio) => void;
}

/** "Marcar como Enviado-DB": data, destinatário, NF e observações. O PDF é copiado para a pasta Enviados. */
export function ModalEnvio({ item, hoje, aoFechar, aoConcluir }: Props) {
  const avisos = useAvisos();
  const [dataEnvio, setDataEnvio] = useState(hoje);
  const [destinatario, setDestinatario] = useState('');
  const [nf, setNf] = useState('');
  const [observacoes, setObservacoes] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function enviar() {
    if (!dataEnvio) {
      setErro('Informe a data de envio.');
      return;
    }
    if (!destinatario.trim()) {
      setErro('Informe o destinatário (campo obrigatório).');
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const envio = await api<DatabookEnvio>('/databooks/envios', {
        metodo: 'POST',
        corpo: {
          op: item.op,
          tipo: item.tipo,
          arquivo: item.arquivo,
          data_envio: dataEnvio,
          destinatario: destinatario.trim(),
          nf_saida: nf.trim(),
          observacoes: observacoes.trim(),
        },
      });
      avisos.sucesso(`Databook OP ${item.op}/${item.tipo} marcado como Enviado-DB e copiado para a pasta Enviados.`);
      aoConcluir(envio);
    } catch (e) {
      setErro(mensagemDeErro(e));
      setEnviando(false);
    }
  }

  return (
    <ModalFormulario
      titulo="Marcar como Enviado-DB"
      aoFechar={aoFechar}
      aoEnviar={() => void enviar()}
      enviando={enviando}
      rotuloEnviar="Confirmar envio"
      erro={erro}
    >
      <p>
        OP <strong className="mono">{item.op}</strong> <SeloTipo tipo={item.tipo} /> <span className="db-rev">Rev {item.revisao}</span>{' '}
        · Lote <strong className="mono">{item.lote}</strong>
        <span className="db-arquivo">{item.arquivo}</span>
      </p>
      <p className="dica">
        Registra que o databook foi mandado ao cliente. Não é a saída física do lote (essa é a Ordem de Faturamento).
      </p>
      <div className="linha-campos">
        <Campo rotulo="Data de envio" para="db-envio-data" obrigatorio>
          <input id="db-envio-data" type="date" value={dataEnvio} onChange={(e) => setDataEnvio(e.target.value)} required />
        </Campo>
        <Campo rotulo="NF de saída" para="db-envio-nf" dica="Opcional">
          <input id="db-envio-nf" type="text" maxLength={40} value={nf} onChange={(e) => setNf(e.target.value)} />
        </Campo>
      </div>
      <Campo rotulo="Destinatário" para="db-envio-destinatario" obrigatorio dica="Quem recebeu: pessoa e setor do cliente.">
        <input
          id="db-envio-destinatario"
          type="text"
          maxLength={300}
          value={destinatario}
          onChange={(e) => setDestinatario(e.target.value)}
          placeholder="Ex.: Fulano (Qualidade do cliente)"
          data-foco-inicial
          required
        />
      </Campo>
      <Campo rotulo="Observações" para="db-envio-obs" dica="Opcional. Ex.: enviado por e-mail.">
        <textarea id="db-envio-obs" rows={2} maxLength={2000} value={observacoes} onChange={(e) => setObservacoes(e.target.value)} />
      </Campo>
    </ModalFormulario>
  );
}
