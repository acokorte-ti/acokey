import type { SituacaoEtapa, StatusNc, StatusRegistro, TipoLote } from '../lib/tipos';

/** Selos do lote: tipo de chaveta, situação da etapa, status do registro e da não conformidade. */

interface Aparencia {
  rotulo: string;
  classe: string;
}

/** Etiqueta do tipo de chaveta, com a cor de cada um (PIN azul, BOX laranja, ARK verde). */
export function SeloTipo({ tipo }: { tipo: TipoLote }) {
  return (
    <span className={`etiqueta-tipo etiqueta-${tipo.toLowerCase()}`}>
      <span className="so-leitor">Tipo </span>
      {tipo}
    </span>
  );
}

const SITUACAO_ETAPA: Record<SituacaoEtapa, Aparencia> = {
  aprovada: { rotulo: 'Aprovada', classe: 'selo-ok' },
  reprovada: { rotulo: 'Reprovada', classe: 'selo-erro' },
  atual: { rotulo: 'Etapa atual', classe: 'selo-andamento' },
  futura: { rotulo: 'A fazer', classe: 'selo-espera' },
  opcional: { rotulo: 'Opcional', classe: 'selo-espera' },
  nao_aplicavel: { rotulo: 'Não se aplica', classe: 'selo-inativo' },
};

export function SeloSituacaoEtapa({ situacao }: { situacao: SituacaoEtapa }) {
  const aparencia = SITUACAO_ETAPA[situacao] ?? { rotulo: situacao, classe: '' };
  return <span className={`selo ${aparencia.classe}`}>{aparencia.rotulo}</span>;
}

const STATUS_REGISTRO: Record<StatusRegistro, Aparencia> = {
  aprovado: { rotulo: 'Aprovado', classe: 'selo-ok' },
  reprovado: { rotulo: 'Reprovado', classe: 'selo-erro' },
  pendente: { rotulo: 'Pendente', classe: 'selo-alerta' },
};

export function SeloRegistro({ status }: { status: StatusRegistro }) {
  const aparencia = STATUS_REGISTRO[status] ?? { rotulo: status, classe: '' };
  return <span className={`selo ${aparencia.classe}`}>{aparencia.rotulo}</span>;
}

const STATUS_NC: Record<StatusNc, Aparencia> = {
  aberta: { rotulo: 'Aberta', classe: 'selo-erro' },
  em_tratamento: { rotulo: 'Em tratamento', classe: 'selo-alerta' },
  encerrada: { rotulo: 'Encerrada', classe: 'selo-ok' },
};

export function SeloNc({ status }: { status: StatusNc }) {
  const aparencia = STATUS_NC[status] ?? { rotulo: status, classe: '' };
  return <span className={`selo ${aparencia.classe}`}>{aparencia.rotulo}</span>;
}

/** Marca curta de "tem não conformidade aberta", usada no cartão e na tabela de lotes. */
export function SeloNcAberta({ curto = false }: { curto?: boolean }) {
  return (
    <span className="selo selo-erro" title="Não conformidade aberta ou em tratamento">
      {curto ? (
        <>
          NC<span className="so-leitor"> (não conformidade aberta)</span>
        </>
      ) : (
        'NC aberta'
      )}
    </span>
  );
}
