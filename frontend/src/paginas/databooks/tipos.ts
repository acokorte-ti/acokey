/** Formatos da API de databooks (backend/app/api_databooks.py). Datas sem fuso: hora local da fábrica. */
import type { TipoLote } from '../../lib/tipos';

/** Databook gerado que ainda não foi enviado ao cliente (aba "A enviar"): a revisão mais recente de cada lote. */
export interface DatabookAEnviar {
  op: string;
  tipo: TipoLote;
  lote: string;
  revisao: number;
  arquivo: string;
  tamanho_mb: number;
  /** Quando o PDF foi gerado: "AAAA-MM-DDTHH:MM:SS". */
  modificado: string;
  /** Dias desde a geração. */
  dias: number;
  /** Lote do sistema com esse número (null se não houver). */
  lote_id: number | null;
}

/** Registro de envio do databook ao cliente (Enviado-DB). Não é a saída física do lote. */
export interface DatabookEnvio {
  id: number;
  op: string;
  tipo: string;
  lote: string;
  revisao: number;
  arquivo: string;
  /** "AAAA-MM-DD" */
  data_envio: string | null;
  destinatario: string;
  nf_saida: string;
  observacoes: string;
  enviado_em: string | null;
  enviado_por: string;
  /** Envio desfeito: a linha fica, marcada (nada é apagado). */
  desfeito_em: string | null;
  desfeito_por: string;
  desfeito_motivo: string;
  lote_id: number | null;
  /** O PDF enviado está guardado no servidor. */
  tem_arquivo: boolean;
}

/** GET /databooks */
export interface PainelDatabooks {
  a_enviar: DatabookAEnviar[];
  enviados: DatabookEnvio[];
  /** Totais das abas, sem o filtro de tipo. */
  n_a_enviar: number;
  n_enviados: number;
  /** "AAAA-MM-DD" (data de hoje na fábrica, padrão da data de envio). */
  hoje: string;
}

export interface RevisaoDatabook {
  arquivo: string;
  revisao: number | null;
  gerado_em: string;
  tamanho_kb: number;
}

/** Usuário que pode assinar como "Aprovado por". */
export interface Aprovador {
  id: number;
  nome: string;
  cargo: string;
  tem_assinatura: boolean;
}

/** O que vai na capa: vem do cadastro da OP e dos parâmetros; só o produto pode ser ajustado na tela. */
export interface CapaDatabook {
  empresa: string;
  cliente: string;
  projeto: string;
  pedido: string;
  produto: string;
  produto_sugestoes: string[];
  lote: string;
  qtd: number;
  numero_documento: string;
  op_cadastrada: boolean;
  proxima_revisao: number;
  elaborado_por: string;
  elaborado_cargo: string;
  elaborado_tem_assinatura: boolean;
}

/** GET /databooks/lote/{id} */
export interface DatabookDoLote {
  lote: { id: number; numero: string; op: string; tipo: TipoLote; qtd: number };
  concluido: boolean;
  /** Revisão mais recente (a que vale). */
  databook: RevisaoDatabook | null;
  /** Todas as revisões, da mais nova para a mais antiga. */
  revisoes: RevisaoDatabook[];
  /** Alertas da montagem (checklist, arquivo que não abriu). Vazio = nenhum. */
  alertas: string[];
  envios: DatabookEnvio[];
  pendente_envio: DatabookAEnviar | null;
  aprovadores: Aprovador[];
  capa: CapaDatabook;
  /** "AAAA-MM-DD": hoje na fábrica (data de envio sugerida). */
  hoje: string;
}

/** POST /databooks/lote/{id}/gerar */
export interface ResultadoGeracao {
  arquivo: string;
  revisao: number;
  paginas: number;
  tamanho_kb: number;
  alertas: string[];
  mensagem: string;
}

export interface Inconsistencia {
  pagina: number;
  ops_erradas: string[];
  lotes_errados: string[];
  ops_todas: string[];
  lotes_todos: string[];
  contexto: string;
}

/** GET /databooks/lote/{id}/conferencia */
export interface ConferenciaDatabook {
  lote: { id: number; numero: string; op: string; tipo: TipoLote };
  arquivo: string;
  revisao: number | null;
  gerado_em: string;
  resultado: {
    ok: boolean;
    erro: string | null;
    total_paginas?: number;
    paginas_com_referencia?: number;
    paginas_ok?: number;
    inconsistencias: Inconsistencia[];
    op_esperada?: string;
    lote_esperado?: string;
  };
}
