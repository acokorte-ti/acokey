import { useState, type ReactNode } from 'react';
import { Campo } from '../../componentes/Campo';
import { ModalFormulario } from '../../componentes/Modal';
import { mensagemDeErro } from '../../lib/api';
import { inteiro } from '../../lib/formato';
import { calcular, hojeIso, porcento, tomRefugo, tomRetrabalho, type Tom } from './calculos';
import type { Corrida, CorridaEntrada, Quantidades, SugestaoFornecedor } from './tipos';

/** O que se digita no formulário (números ficam como texto até gravar). */
export interface FormularioCorrida {
  nf_entrada: string;
  corrida: string;
  fornecedor: string;
  tipo_destino: string;
  data_recebimento: string;
  qt_fund: string;
  qt_real: string;
  qt_ok: string;
  qt_rej: string;
  qt_retrab: string;
  qt_cp_tt: string;
  observacoes: string;
}

type CampoQuantidade = keyof Quantidades;

/** Rótulo, complemento e explicação de cada quantidade (as dicas do sistema antigo). */
const QUANTIDADES: { chave: CampoQuantidade; rotulo: string; sub: string; ajuda: string }[] = [
  { chave: 'qt_fund', rotulo: 'QT-FUND.', sub: 'fundida', ajuda: 'Quantidade total fundida pelo fornecedor nesta corrida (antes da inspeção de recebimento).' },
  { chave: 'qt_real', rotulo: 'QT-REAL', sub: 'recebida', ajuda: 'Quantidade real de peças recebidas na AçoKorte. Base para os percentuais de refugo e retrabalho.' },
  { chave: 'qt_ok', rotulo: 'QT-OK', sub: 'aprovadas', ajuda: 'Peças aprovadas na inspeção de recebimento, disponíveis para produção.' },
  { chave: 'qt_rej', rotulo: 'QT-REJ.', sub: 'refugo', ajuda: 'Peças rejeitadas definitivamente (sucata). Contam como refugo.' },
  { chave: 'qt_retrab', rotulo: 'QT-RETRAB.', sub: 'retrabalhadas', ajuda: 'Peças com defeito recuperável que serão retrabalhadas antes de usar.' },
  { chave: 'qt_cp_tt', rotulo: 'QT-CP-T.T.', sub: 'corpos de prova', ajuda: 'Corpos de prova retirados para ensaios (tração/Charpy). São descontados do saldo disponível.' },
];

export function formularioVazio(): FormularioCorrida {
  return {
    nf_entrada: '',
    corrida: '',
    fornecedor: '',
    tipo_destino: '',
    data_recebimento: hojeIso(),
    qt_fund: '0',
    qt_real: '0',
    qt_ok: '0',
    qt_rej: '0',
    qt_retrab: '0',
    qt_cp_tt: '0',
    observacoes: '',
  };
}

export function formularioDe(c: Corrida): FormularioCorrida {
  return {
    nf_entrada: c.nf_entrada,
    corrida: c.corrida,
    fornecedor: c.fornecedor,
    tipo_destino: c.tipo_destino,
    data_recebimento: c.data_recebimento ?? '',
    qt_fund: String(c.qt_fund),
    qt_real: String(c.qt_real),
    qt_ok: String(c.qt_ok),
    qt_rej: String(c.qt_rej),
    qt_retrab: String(c.qt_retrab),
    qt_cp_tt: String(c.qt_cp_tt),
    observacoes: c.observacoes,
  };
}

function numero(texto: string): number {
  const valor = Number.parseInt(texto, 10);
  return Number.isFinite(valor) && valor > 0 ? valor : 0;
}

function quantidades(f: FormularioCorrida): Quantidades {
  return {
    qt_fund: numero(f.qt_fund),
    qt_real: numero(f.qt_real),
    qt_ok: numero(f.qt_ok),
    qt_rej: numero(f.qt_rej),
    qt_retrab: numero(f.qt_retrab),
    qt_cp_tt: numero(f.qt_cp_tt),
  };
}

export function paraEnvio(f: FormularioCorrida): CorridaEntrada {
  return {
    nf_entrada: f.nf_entrada.trim(),
    corrida: f.corrida.trim(),
    fornecedor: f.fornecedor.trim(),
    tipo_destino: f.tipo_destino,
    data_recebimento: f.data_recebimento || null,
    observacoes: f.observacoes.trim(),
    ...quantidades(f),
  };
}

function Indicador({ rotulo, valor, tom }: { rotulo: string; valor: string; tom: Tom }) {
  return (
    <div className="mp-indicador">
      <span className="mp-indicador-rotulo">{rotulo}</span>
      <strong className={tom ? `mp-tom-${tom}` : undefined}>{valor}</strong>
    </div>
  );
}

interface PropsModal {
  titulo: string;
  inicial: FormularioCorrida;
  /** Lançamento novo: NF obrigatória (como no formulário do sistema antigo). */
  novo: boolean;
  fornecedores: SugestaoFornecedor[];
  /** Quem fica registrado como responsável (o usuário logado). */
  responsavel?: string;
  rotuloEnviar: string;
  /** Aviso no topo do formulário (ex.: dados que vieram do Mega). */
  aviso?: ReactNode;
  aoFechar: () => void;
  /** Grava; se der erro, a mensagem aparece no formulário. */
  aoGravar: (corpo: CorridaEntrada) => Promise<void>;
}

/** Formulário da corrida (lançar e editar), com os percentuais calculados enquanto se digita. */
export function ModalCorrida({ titulo, inicial, novo, fornecedores, responsavel, rotuloEnviar, aviso, aoFechar, aoGravar }: PropsModal) {
  const [f, setF] = useState<FormularioCorrida>(inicial);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const mudar = (parcial: Partial<FormularioCorrida>) => setF((atual) => ({ ...atual, ...parcial }));
  const calculo = calcular(quantidades(f));

  async function enviar() {
    setErro(null);
    setEnviando(true);
    try {
      await aoGravar(paraEnvio(f));
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setEnviando(false);
    }
  }

  return (
    <ModalFormulario titulo={titulo} largura="larga" aoFechar={aoFechar} aoEnviar={() => void enviar()} enviando={enviando} erro={erro}
      rotuloEnviar={rotuloEnviar}>
      {aviso}
      <div className="form-grade">
        <Campo rotulo="NF de entrada" para="mp-nf" obrigatorio={novo}>
          <input id="mp-nf" type="text" required={novo} maxLength={40} value={f.nf_entrada} onChange={(e) => mudar({ nf_entrada: e.target.value })} />
        </Campo>
        <Campo rotulo="Corrida" para="mp-corrida" obrigatorio dica="Número da batelada de fundição do fornecedor.">
          <input
            id="mp-corrida"
            type="text"
            className="mono"
            required
            maxLength={60}
            placeholder="Ex.: M999"
            title="Permite rastrear cada peça até sua origem (certificado químico, laudo)."
            value={f.corrida}
            onChange={(e) => mudar({ corrida: e.target.value })}
          />
        </Campo>
        <Campo rotulo="Tipo destino" para="mp-tipo" obrigatorio>
          <select id="mp-tipo" required value={f.tipo_destino} onChange={(e) => mudar({ tipo_destino: e.target.value })}>
            <option value="">Selecione…</option>
            <option value="PIN">PIN</option>
            <option value="BOX">BOX</option>
            <option value="ARK">ARK</option>
          </select>
        </Campo>
        <Campo rotulo="Data de recebimento" para="mp-data">
          <input id="mp-data" type="date" value={f.data_recebimento} onChange={(e) => mudar({ data_recebimento: e.target.value })} />
        </Campo>
        <Campo rotulo="Fornecedor" para="mp-fornecedor" classe="col-2">
          <input
            id="mp-fornecedor"
            type="text"
            list="mp-lista-fornecedores"
            maxLength={160}
            placeholder="Escolha ou digite"
            value={f.fornecedor}
            onChange={(e) => mudar({ fornecedor: e.target.value })}
          />
          <datalist id="mp-lista-fornecedores">
            {fornecedores.map((s) => (
              <option key={s.valor} value={s.valor}>
                {s.rotulo}
              </option>
            ))}
          </datalist>
        </Campo>
        {responsavel !== undefined && (
          <Campo rotulo="Lançada por" para="mp-responsavel" classe="col-2" dica="Sempre o usuário que está logado.">
            <div id="mp-responsavel" className="automatico">
              {responsavel}
            </div>
          </Campo>
        )}
      </div>

      <h3 className="mp-subtitulo">Quantidades</h3>
      <div className="mp-grade-qtd">
        {QUANTIDADES.map((q) => (
          <Campo key={q.chave} rotulo={q.rotulo} para={`mp-${q.chave}`} dica={q.sub} obrigatorio={q.chave === 'qt_real'}>
            <input
              id={`mp-${q.chave}`}
              type="number"
              inputMode="numeric"
              className="num"
              min={0}
              step={1}
              required={q.chave === 'qt_real'}
              title={q.ajuda}
              value={f[q.chave]}
              onFocus={(e) => e.target.select()}
              onChange={(e) => mudar({ [q.chave]: e.target.value } as Partial<FormularioCorrida>)}
            />
          </Campo>
        ))}
      </div>
      <div className="mp-indicadores" aria-live="polite">
        <Indicador rotulo="Disponível (QT-OK − CP)" valor={inteiro(calculo.qt_disponivel)} tom="info" />
        <Indicador rotulo="% Refugo" valor={porcento(calculo.pct_refugo)} tom={tomRefugo(calculo.pct_refugo)} />
        <Indicador rotulo="% Retrabalho" valor={porcento(calculo.pct_retrab)} tom={tomRetrabalho(calculo.pct_retrab)} />
        <Indicador rotulo="% Aprovação" valor={porcento(calculo.pct_aprov)} tom="ok" />
        <Indicador rotulo="Rendimento" valor={porcento(calculo.rendimento)} tom="" />
      </div>

      <Campo rotulo="Observações" para="mp-obs">
        <textarea id="mp-obs" rows={2} maxLength={4000} value={f.observacoes} onChange={(e) => mudar({ observacoes: e.target.value })} />
      </Campo>
    </ModalFormulario>
  );
}
