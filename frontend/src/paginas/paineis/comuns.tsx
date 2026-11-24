/** Peças comuns do dashboard, do Gantt e dos KPIs: cartões de número com tendência e filtros. */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { inteiro, normalizar } from '../../lib/formato';
import type { TipoLote } from '../../lib/tipos';
import type { Tendencias, Totais, Variacao } from './tipos';

export const TIPOS: TipoLote[] = ['PIN', 'BOX', 'ARK'];
/** Lista de databooks já enviados ao cliente (módulo Databooks), opcionalmente de um tipo. */
export function linkEnviados(tipo?: TipoLote): string {
  return tipo ? `/databooks?tab=enviados&tipo=${tipo}` : '/databooks?tab=enviados';
}

const SINAL: Record<Variacao['sentido'], string> = { subiu: '▲', caiu: '▼', igual: '=', novo: '▲' };

/** "▲ +20% vs mês anterior": verde quando sobe, vermelho quando cai (aqui, subir é bom). */
export function Tendencia({ v, referencia = 'vs mês anterior' }: { v: Variacao | null; referencia?: string }) {
  if (!v) return null;
  const titulo = `Este mês: ${inteiro(v.atual)} · mês anterior: ${inteiro(v.anterior)}`;
  return (
    <span className={`pn-tendencia pn-tendencia-${v.sentido}`} title={titulo}>
      <span aria-hidden="true">{SINAL[v.sentido]}</span> {v.rotulo}
      {v.sentido !== 'novo' && <span className="pn-tendencia-ref"> {referencia}</span>}
      <span className="so-leitor">. {titulo}</span>
    </span>
  );
}

export function CartaoNumero({
  rotulo,
  valor,
  apoio,
  tendencia,
  referenciaTendencia,
  link,
  classe,
}: {
  rotulo: string;
  valor: ReactNode;
  apoio?: ReactNode;
  tendencia?: Variacao | null;
  /** Texto depois da variação; padrão "vs mês anterior". */
  referenciaTendencia?: string;
  /** O cartão vira link (ex.: Enviados-DB abre a lista de databooks enviados). */
  link?: string;
  classe?: string;
}) {
  const corpo = (
    <>
      <span className="cartao-rotulo">{rotulo}</span>
      <span className="cartao-valor">{valor}</span>
      {tendencia !== undefined && <Tendencia v={tendencia} referencia={referenciaTendencia} />}
      {apoio && <span className="cartao-apoio">{apoio}</span>}
    </>
  );
  const classes = `cartao-numero pn-numero ${classe ?? ''}`;
  if (link) {
    return (
      <Link to={link} className={`${classes} pn-numero-link`}>
        {corpo}
      </Link>
    );
  }
  return <div className={classes}>{corpo}</div>;
}

/** "120 peças" */
export function pecasTexto(n: number): string {
  return `${inteiro(n)} ${n === 1 ? 'peça' : 'peças'}`;
}

/** Os cartões do topo do dashboard e do Gantt (totais da fábrica, com a tendência mês a mês). */
export function CartoesTotais({ totais, tendencias, primeiro }: { totais: Totais; tendencias: Tendencias; primeiro: ReactNode }) {
  return (
    <div className="pn-cartoes">
      {primeiro}
      <CartaoNumero rotulo="Em andamento" valor={inteiro(totais.andamento)} apoio={pecasTexto(totais.pecas_andamento)} classe="pn-numero-andamento" />
      <CartaoNumero
        rotulo="Concluídos"
        valor={inteiro(totais.concluidos)}
        tendencia={tendencias.concluidos}
        apoio={`${pecasTexto(totais.pecas_concluidos)}${totais.enviados ? ' · sem enviar' : ''}`}
        classe="pn-numero-concluido"
      />
      <CartaoNumero
        rotulo="Enviados-DB"
        valor={inteiro(totais.enviados)}
        tendencia={tendencias.enviados}
        apoio={<>{pecasTexto(totais.pecas_enviados)} · ver a lista</>}
        link={linkEnviados()}
        classe="pn-numero-enviado"
      />
      {TIPOS.map((tipo) => {
        const t = tipo.toLowerCase() as 'pin' | 'box' | 'ark';
        const enviados = totais[`${t}_enviados`];
        return (
          <CartaoNumero
            key={tipo}
            rotulo={`${tipo} · lotes`}
            valor={inteiro(totais[t])}
            tendencia={tendencias[t]}
            apoio={`${pecasTexto(totais[`pecas_${t}`])}${enviados ? ` · ${inteiro(totais[`${t}_ativos`])} ativos / ${inteiro(enviados)} enviados` : ''}`}
            classe={`pn-numero-${t}`}
          />
        );
      })}
    </div>
  );
}

interface PropsSegmentos<T extends string> {
  idRotulo: string;
  opcoes: { valor: T; rotulo: string }[];
  valor: T;
  aoMudar: (valor: T) => void;
}

/** Controle segmentado: uma opção marcada por vez. */
export function Segmentos<T extends string>({ idRotulo, opcoes, valor, aoMudar }: PropsSegmentos<T>) {
  return (
    <div className="segmentos" role="group" aria-labelledby={idRotulo}>
      {opcoes.map((opcao) => (
        <button
          key={opcao.valor}
          type="button"
          className={`segmento ${valor === opcao.valor ? 'segmento-ativo' : ''}`}
          aria-pressed={valor === opcao.valor}
          onClick={() => aoMudar(opcao.valor)}
        >
          {opcao.rotulo}
        </button>
      ))}
    </div>
  );
}

export type FiltroTipo = '' | TipoLote;
export const OPCOES_TIPO: { valor: FiltroTipo; rotulo: string }[] = [{ valor: '', rotulo: 'Todos' }, ...TIPOS.map((t) => ({ valor: t, rotulo: t }))];

/** Listas de sugestões (OPs e CODITEMs do cadastro) para os campos de filtro. */
export function SugestoesCadastro({ idOps, idItens, ops }: { idOps: string; idItens: string; ops: { op: string; tipo: string; coditem: string; descricao: string }[] }) {
  const itens = [...new Set(ops.map((o) => o.coditem).filter(Boolean))];
  return (
    <>
      <datalist id={idOps}>
        {ops.map((o) => (
          <option key={o.op} value={o.op}>
            {[o.tipo, o.coditem, o.descricao].filter(Boolean).join(' - ')}
          </option>
        ))}
      </datalist>
      <datalist id={idItens}>
        {itens.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>
    </>
  );
}

/** Texto contém o trecho digitado (sem diferença de maiúsculas nem de acentos). */
export function inclui(texto: string, trecho: string): boolean {
  const t = normalizar(trecho);
  return t === '' || normalizar(texto).includes(t);
}
