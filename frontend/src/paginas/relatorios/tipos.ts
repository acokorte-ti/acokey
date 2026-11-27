/** Formatos da API dos relatórios gerados pelo sistema (backend/app/api_relatorios.py). */
import type { TipoLote } from '../../lib/tipos';

/** Equipamento do cadastro (forno ou durômetro), com a calibração. Datas "AAAA-MM-DD". */
export interface Equipamento {
  codigo: string;
  descricao: string;
  marca: string;
  rotulo: string;
  certificado: string;
  data_calibracao: string | null;
  validade_calibracao: string | null;
  vencida: boolean;
  ativo: boolean;
}

/** Quem pode constar como "Executado por" ou "Aprovado por". */
export interface Pessoa {
  id: number;
  nome: string;
  cargo: string;
  tem_assinatura: boolean;
}

export interface LoteBasico {
  id: number;
  numero: string;
  op: string;
  tipo: TipoLote;
  qtd: number;
  corrida: string;
  coditem: string;
}

/** Resposta de todos os "Salvar e gerar PDF". */
export interface RespostaRelatorio {
  mensagem: string;
  registro_id: number;
  anexo_id: number;
  status?: string;
  nc?: string | null;
  avancou?: boolean;
  lotes?: number;
}

// ---------------------------------------------------------------- dureza

export interface TelaDureza {
  lote: LoteBasico;
  info: {
    cliente: string;
    nome_peca: string;
    desenho: string;
    especificacao: string;
    esp_min: number;
    esp_max: number;
    padrao_aceitacao: string;
    material: string;
    po: string;
  };
  imagem_pontos: string;
  tem_imagem_pontos: boolean;
  /** Linhas que o RIP-35 traz prontas: 10% das peças do lote (base "lote"); a da OP ("op") só se o lote não tiver quantidade. */
  amostra: { qtd: number; base: 'op' | 'lote'; linhas: number; limite: number };
  /** Leitura automática da foto da folha (RIP-35 escrito à mão) ligada no servidor. */
  leitura_foto: boolean;
  durometros: Equipamento[];
  executores: Pessoa[];
  aprovadores: Pessoa[];
  usuario_id: number;
  carga: { id: number; numero: string } | null;
  carga_outros_lotes: (LoteBasico & { ja_feito: boolean })[];
  hoje: string;
}

/** Uma linha lida da foto da folha. O que não deu para ler volta vazio e marcado (nao_lidos / peca_nao_lida). */
export interface LinhaLidaFoto {
  peca: string;
  peca_nao_lida: boolean;
  valores: string[];
  nao_lidos: boolean[];
}

/** Foto já gravada no servidor; vai junto ao salvar o RIP-35 e vira anexo interno da etapa. */
export interface FotoLida {
  arquivo: string;
  nome: string;
}

export interface RespostaLeituraFoto {
  linhas: LinhaLidaFoto[];
  nao_lidos: number;
  aviso: string;
  foto: FotoLida;
}

// ---------------------------------------------------------------- tratamento térmico

/** Uma linha da lista de lotes do relatório de TT (cliente e item de cada OP). */
export interface LinhaTT {
  op: string;
  lote: string;
  tipo: TipoLote;
  qtd: number;
  cliente: string;
  item: string;
}

export type LoteTT = LoteBasico & LinhaTT;

export interface TelaTT {
  lote: LoteBasico;
  principal: LinhaTT;
  carga: { id: number; numero: string; status: string } | null;
  /** O lote está numa carga em aberto: a tela sugere gerar pela carga. */
  carga_do_lote: { id: number; numero: string; status: string } | null;
  lotes_carga: LoteTT[];
  outros_lotes: (LoteTT & { aguardando_tt: boolean })[];
  info: { material: string; fornecedor: string; esp_dureza: string; esp_min: number; esp_max: number; po: string };
  fornos_tempera: Equipamento[];
  fornos_revenimento: Equipamento[];
  forno_tempera_padrao: string;
  forno_revenimento_padrao: string;
  tecnicos: Pessoa[];
  aprovadores: Pessoa[];
  usuario_id: number;
  hoje: string;
}

// ---------------------------------------------------------------- visual

export interface TelaVisual {
  lote: LoteBasico;
  info: {
    cliente: string;
    nome_peca: string;
    desenho: string;
    padrao_aceitacao: string;
    po: string;
    obs1: string;
    obs2: string;
    obs3: string;
  };
  /** Formato do código gravado a laser (parâmetro laser_formato), ex.: "{ano}T{tri}-C{corrida}-L{lote}-{seq:03d}". */
  laser: { formato: string; corrida: string; lote: string };
  ano: number;
  tri: number;
  lote_completo: string;
  resultados: string[];
  pode_usar_como_esta: boolean;
  executores: Pessoa[];
  aprovadores: Pessoa[];
  usuario_id: number;
  hoje: string;
}
