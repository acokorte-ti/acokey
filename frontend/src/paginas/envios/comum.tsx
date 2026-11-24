/* Peças comuns às telas de envio a prestador (e reaproveitadas pela ordem de faturamento). */
import { useState, type ReactNode } from 'react';
import { Campo } from '../../componentes/Campo';
import { ModalFormulario } from '../../componentes/Modal';
import { mensagemDeErro } from '../../lib/api';
import type { EspecificacaoTipo, Natureza, StatusEnvio } from './tipos';

const STATUS: Record<StatusEnvio, { rotulo: string; classe: string }> = {
  enviado: { rotulo: 'Enviado', classe: 'selo-alerta' },
  retornado: { rotulo: 'Retornado', classe: 'selo-ok' },
  cancelado: { rotulo: 'Cancelado', classe: 'selo-inativo' },
};

export function SeloStatusEnvio({ status }: { status: StatusEnvio }) {
  const aparencia = STATUS[status] ?? { rotulo: status, classe: '' };
  return <span className={`selo ${aparencia.classe}`}>{aparencia.rotulo}</span>;
}

/** "Há 12 dias" em vermelho quando passou do limite sem retorno. */
export function SeloDias({ dias, alerta }: { dias: number; alerta: boolean }) {
  if (!dias) return null;
  return (
    <span className={`env-dias ${alerta ? 'env-dias-alerta' : ''}`} title={alerta ? 'Enviado há muitos dias sem retorno' : undefined}>
      {dias} {dias === 1 ? 'dia' : 'dias'}
    </span>
  );
}

/** Aviso colorido do que sai da fábrica: azul (só CPs), verde (laboratório vem à fábrica), laranja (peças saem). */
export function NotaNatureza({ natureza }: { natureza: Natureza }) {
  return (
    <p className={`env-natureza env-natureza-${natureza.classe}`} role="note">
      <strong>Natureza do envio:</strong> {natureza.texto}
    </p>
  );
}

function ColunaEspecificacao({ titulo, classe, norma, linhas }: { titulo: string; classe: string; norma: string; linhas: [string, string][] }) {
  if (!linhas.length) return null;
  return (
    <div className={`env-spec-coluna ${classe}`}>
      <div className="env-spec-titulo">{titulo}</div>
      <div className="env-spec-norma">
        Norma de execução: <strong>{norma}</strong>
      </div>
      <dl>
        {linhas.map(([rotulo, valor]) => (
          <div key={rotulo} className="env-spec-linha">
            <dt>{rotulo}:</dt>
            <dd>{valor}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Especificação aplicável, por tipo de peça, com Tração (azul) e Charpy (vermelho) lado a lado. */
export function QuadroEspecificacao({
  especificacao,
  normaCodigo,
  clienteCurto,
  titulo = 'Especificação aplicável',
  apoio,
}: {
  especificacao: EspecificacaoTipo[];
  normaCodigo: string;
  clienteCurto?: string;
  titulo?: string;
  apoio?: ReactNode;
}) {
  const referencia = [normaCodigo, clienteCurto].filter(Boolean).join(' · ');
  return (
    <section className="env-spec" aria-label={titulo}>
      <h3>
        {titulo}
        {referencia && <span className="env-spec-ref"> (Norma: {referencia})</span>}
      </h3>
      {apoio && <p className="dica">{apoio}</p>}
      {especificacao.map((sp) => (
        <div key={sp.tipo} className="env-spec-tipo">
          <div className="env-spec-cab">
            <strong>Tipo {sp.tipo}</strong> · <span>Material: {sp.material}</span>
          </div>
          {sp.vazio || (!sp.tracao.length && !sp.charpy.length) ? (
            <p className="env-spec-vazio">Nenhuma especificação cadastrada para este tipo.</p>
          ) : (
            <div className="env-spec-colunas">
              <ColunaEspecificacao titulo="TRAÇÃO" classe="env-spec-tracao" norma="ASTM A370" linhas={sp.tracao} />
              <ColunaEspecificacao titulo="IMPACTO CHARPY" classe="env-spec-charpy" norma="ASTM E23" linhas={sp.charpy} />
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

// ---------------------------------------------------------------- números digitados

/** Inteiro digitado; vazio ou inválido vale 0. */
export function inteiroDe(texto: string | number | null | undefined): number {
  const valor = Number.parseInt(String(texto ?? '').trim(), 10);
  return Number.isFinite(valor) && valor > 0 ? valor : 0;
}

/** Número com vírgula ou ponto ("12,5"); vazio ou inválido vale 0. */
export function decimalDe(texto: string | number | null | undefined): number {
  const valor = Number.parseFloat(String(texto ?? '').trim().replace(',', '.'));
  return Number.isFinite(valor) && valor > 0 ? valor : 0;
}

/** 12.5 -> "12,50" */
export function pesoBr(valor: number): string {
  return valor.toFixed(2).replace('.', ',');
}

/** Valor guardado (número) para mostrar no campo de texto: 0 vira vazio, 12.5 vira "12,5". */
export function textoDoPeso(valor: number | null | undefined): string {
  return valor ? String(valor).replace('.', ',') : '';
}

// ---------------------------------------------------------------- confirmação com motivo

interface PropsModalMotivo {
  titulo: string;
  children?: ReactNode;
  rotulo?: string;
  rotuloConfirmar: string;
  perigo?: boolean;
  aoFechar: () => void;
  /** Grava; se der erro, a mensagem aparece na janela. */
  aoConfirmar: (motivo: string) => Promise<void>;
}

/** Ação que exige motivo escrito (cancelar, remover foto): fica na auditoria, com o usuário. */
export function ModalMotivo({ titulo, children, rotulo = 'Motivo', rotuloConfirmar, perigo = false, aoFechar, aoConfirmar }: PropsModalMotivo) {
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function confirmar() {
    if (motivo.trim().length < 5) {
      setErro('Escreva o motivo (pelo menos 5 letras).');
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
    <ModalFormulario
      titulo={titulo}
      aoFechar={aoFechar}
      aoEnviar={() => void confirmar()}
      enviando={enviando}
      erro={erro}
      rotuloEnviar={rotuloConfirmar}
      perigo={perigo}
    >
      {children}
      <Campo rotulo={rotulo} para="env-motivo" obrigatorio dica="Fica registrado na auditoria, com o seu usuário.">
        <textarea id="env-motivo" rows={3} maxLength={2000} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
      </Campo>
    </ModalFormulario>
  );
}
