/**
 * Busca de lote no topo de todas as telas (legado: overlay "busca-ov" e abrirBusca() de TEMPLATES["base"]).
 *
 * - Abre pelo botão "Buscar lote", com Ctrl+K (Cmd+K no Mac) ou com "/" fora de um campo de texto.
 * - Procura por OP, número do lote, CODITEM ou descrição do produto (GET /api/buscar). OPs do cadastro que
 *   ainda não têm lote também aparecem.
 * - Sem nada digitado, mostra os últimos lotes abertos neste computador.
 * - ↑ ↓ escolhem, Enter abre, Esc fecha.
 */
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api, consulta, foiCancelada, mensagemDeErro } from '../lib/api';
import { inteiro } from '../lib/formato';
import type { TipoLote } from '../lib/tipos';
import type { ItemBusca, RespostaBusca } from '../paginas/paineis/tipos';
import './BuscaGlobal.css';
import { SeloNcAberta, SeloTipo } from './Selos';

const CHAVE_RECENTES = 'acokey_lotes_recentes';
const MAX_RECENTES = 6;
const ESPERA_MS = 150;

function lerRecentes(): number[] {
  try {
    const valor: unknown = JSON.parse(localStorage.getItem(CHAVE_RECENTES) ?? '[]');
    return Array.isArray(valor) ? valor.filter((v): v is number => Number.isInteger(v)).slice(0, MAX_RECENTES) : [];
  } catch {
    return [];
  }
}

function guardarRecente(id: number): void {
  try {
    const lista = [id, ...lerRecentes().filter((v) => v !== id)].slice(0, MAX_RECENTES);
    localStorage.setItem(CHAVE_RECENTES, JSON.stringify(lista));
  } catch {
    // navegador sem armazenamento local: a busca funciona, só não lembra os últimos lotes
  }
}

function ehTipo(valor: string): valor is TipoLote {
  return valor === 'PIN' || valor === 'BOX' || valor === 'ARK';
}

type Estado =
  | { fase: 'recentes'; itens: ItemBusca[] }
  | { fase: 'procurando' }
  | { fase: 'resultado'; itens: ItemBusca[]; total: number }
  | { fase: 'erro'; mensagem: string };

function IconeLupa() {
  return (
    <svg className="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4.5 4.5" />
    </svg>
  );
}

function Resultado({ item, id, selecionado, aoEscolher, aoApontar }: {
  item: ItemBusca;
  id: string;
  selecionado: boolean;
  aoEscolher: () => void;
  aoApontar: () => void;
}) {
  const semLote = item.tipo === 'op';
  const detalhes = [item.coditem && `Item ${item.coditem}`, item.descricao, item.etapa].filter(Boolean).join(' · ');
  return (
    <li
      id={id}
      role="option"
      aria-selected={selecionado}
      className={`busca-item ${selecionado ? 'busca-item-sel' : ''} ${semLote ? 'busca-item-op' : ''}`}
      onClick={aoEscolher}
      onMouseMove={aoApontar}
    >
      <span className="busca-item-icone" aria-hidden="true">
        {semLote ? '!' : <IconeLupa />}
      </span>
      <span className="busca-item-texto">
        <span className="busca-item-titulo">
          <strong className="mono">OP {item.op}</strong>
          {ehTipo(item.formato) && <SeloTipo tipo={item.formato} />}
          {semLote ? <small>(sem lote iniciado)</small> : <small className="mono">Lote {item.numero}</small>}
          {item.nc && <SeloNcAberta curto />}
          {item.enviado && <span className="selo busca-enviado">Enviado-DB</span>}
        </span>
        <span className="busca-item-sub">
          {detalhes}
          {item.qtd !== null && item.qtd !== undefined && ` · ${inteiro(item.qtd)} ${item.qtd === 1 ? 'peça' : 'peças'}`}
        </span>
      </span>
    </li>
  );
}

export function BuscaGlobal() {
  const dialogo = useRef<HTMLDialogElement>(null);
  const campo = useRef<HTMLInputElement>(null);
  const [aberta, setAberta] = useState(false);
  const [termo, setTermo] = useState('');
  const [estado, setEstado] = useState<Estado>({ fase: 'recentes', itens: [] });
  const [selecionado, setSelecionado] = useState(0);
  const navegar = useNavigate();
  const local = useLocation();
  const base = useId();
  const idLista = `${base}-lista`;
  const idTitulo = `${base}-titulo`;

  // Guarda os lotes abertos (por qualquer caminho) para a lista de "últimos lotes abertos"
  useEffect(() => {
    const achado = /^\/lotes\/(\d+)(?:\/|$)/.exec(local.pathname);
    if (achado?.[1]) guardarRecente(Number(achado[1]));
  }, [local.pathname]);

  const abrir = useCallback(() => setAberta(true), []);
  const fechar = useCallback(() => setAberta(false), []);

  // Atalhos: Ctrl+K / Cmd+K em qualquer lugar; "/" quando não se está digitando num campo
  useEffect(() => {
    function tecla(evento: globalThis.KeyboardEvent) {
      if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === 'k') {
        evento.preventDefault();
        setAberta(true);
        return;
      }
      const alvo = evento.target as HTMLElement | null;
      const digitando = !!alvo && (['INPUT', 'TEXTAREA', 'SELECT'].includes(alvo.tagName) || alvo.isContentEditable);
      if (evento.key === '/' && !digitando && !evento.ctrlKey && !evento.metaKey && !evento.altKey) {
        evento.preventDefault();
        setAberta(true);
      }
    }
    document.addEventListener('keydown', tecla);
    return () => document.removeEventListener('keydown', tecla);
  }, []);

  // Abre e fecha o <dialog> nativo (prende o foco dentro dele e devolve ao fechar)
  useEffect(() => {
    const d = dialogo.current;
    if (!d) return;
    if (aberta && !d.open) {
      d.showModal();
      window.setTimeout(() => campo.current?.select(), 0);
    } else if (!aberta && d.open) {
      d.close();
    }
  }, [aberta]);

  // Fechar ao trocar de tela (ex.: escolheu um resultado)
  useEffect(() => setAberta(false), [local.pathname]);

  // Busca: sem termo, os últimos lotes abertos; com termo, espera parar de digitar e pergunta ao servidor
  useEffect(() => {
    if (!aberta) return;
    const controle = new AbortController();
    const texto = termo.trim();
    let espera: number | undefined;
    if (!texto) {
      const ids = lerRecentes();
      setSelecionado(0);
      if (ids.length === 0) {
        setEstado({ fase: 'recentes', itens: [] });
      } else {
        api<RespostaBusca>(`/buscar${consulta({ ids: ids.join(',') })}`, { sinal: controle.signal })
          .then((r) => setEstado({ fase: 'recentes', itens: r.itens }))
          .catch((erro: unknown) => {
            if (!foiCancelada(erro)) setEstado({ fase: 'recentes', itens: [] });
          });
      }
    } else {
      setEstado({ fase: 'procurando' });
      espera = window.setTimeout(() => {
        api<RespostaBusca>(`/buscar${consulta({ q: texto })}`, { sinal: controle.signal })
          .then((r) => {
            setEstado({ fase: 'resultado', itens: r.itens, total: r.total });
            setSelecionado(0);
          })
          .catch((erro: unknown) => {
            if (!foiCancelada(erro)) setEstado({ fase: 'erro', mensagem: mensagemDeErro(erro) });
          });
      }, ESPERA_MS);
    }
    return () => {
      window.clearTimeout(espera);
      controle.abort();
    };
  }, [aberta, termo]);

  const itens = estado.fase === 'recentes' || estado.fase === 'resultado' ? estado.itens : [];

  // Mantém o escolhido visível ao andar com as setas
  useEffect(() => {
    document.getElementById(`${base}-item-${selecionado}`)?.scrollIntoView({ block: 'nearest' });
  }, [selecionado, base]);

  function escolher(item: ItemBusca) {
    setAberta(false);
    if (item.tipo === 'lote' && item.id !== null) navegar(`/lotes/${item.id}`);
    else navegar('/'); // OP sem lote: vai ao painel, onde se cria o lote
  }

  function teclaNoCampo(evento: KeyboardEvent<HTMLInputElement>) {
    if (itens.length === 0) return;
    if (evento.key === 'ArrowDown') {
      evento.preventDefault();
      setSelecionado((s) => (s + 1) % itens.length);
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      setSelecionado((s) => (s - 1 + itens.length) % itens.length);
    } else if (evento.key === 'Enter') {
      evento.preventDefault();
      const item = itens[selecionado];
      if (item) escolher(item);
    }
  }

  let rodape = '';
  if (estado.fase === 'resultado') {
    rodape =
      estado.total > estado.itens.length
        ? `${inteiro(estado.itens.length)} de ${inteiro(estado.total)} resultados (refine a busca)`
        : `${inteiro(estado.total)} ${estado.total === 1 ? 'resultado' : 'resultados'}`;
  }

  return (
    <>
      <button type="button" className="botao botao-fantasma botao-pequeno busca-botao" onClick={abrir} aria-label="Buscar lote (Ctrl+K)" aria-haspopup="dialog">
        <IconeLupa />
        <span className="busca-botao-texto">Buscar lote</span>
        <kbd className="busca-botao-atalho">Ctrl K</kbd>
      </button>

      <dialog
        ref={dialogo}
        className="busca-dialogo"
        aria-labelledby={idTitulo}
        onCancel={(e) => {
          e.preventDefault(); // quem fecha é o React
          fechar();
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget) fechar(); // clique fora da caixa
        }}
      >
        <div className="busca-caixa">
          <h2 id={idTitulo} className="so-leitor">
            Buscar lote
          </h2>
          <div className="busca-topo">
            <IconeLupa />
            <input
              ref={campo}
              type="search"
              className="busca-campo"
              placeholder="OP, nº do lote, CODITEM ou descrição…"
              autoComplete="off"
              spellCheck={false}
              role="combobox"
              aria-expanded={itens.length > 0}
              aria-controls={idLista}
              aria-autocomplete="list"
              aria-activedescendant={itens.length > 0 ? `${base}-item-${selecionado}` : undefined}
              aria-label="Buscar lote por OP, número do lote, CODITEM ou descrição"
              maxLength={100}
              value={termo}
              onChange={(e) => setTermo(e.target.value)}
              onKeyDown={teclaNoCampo}
            />
            <button type="button" className="busca-esc" onClick={fechar} aria-label="Fechar a busca">
              Esc
            </button>
          </div>

          <div className="busca-lista-area">
            {estado.fase === 'recentes' && itens.length > 0 && <p className="busca-cabecalho">Últimos lotes abertos</p>}
            {estado.fase === 'recentes' && itens.length === 0 && (
              <p className="busca-vazio">Comece a digitar: OP, nº do lote, CODITEM ou descrição do produto.</p>
            )}
            {estado.fase === 'procurando' && (
              <p className="busca-vazio" role="status">
                Procurando…
              </p>
            )}
            {estado.fase === 'erro' && (
              <p className="busca-vazio texto-erro" role="alert">
                Não foi possível buscar: {estado.mensagem}
              </p>
            )}
            {estado.fase === 'resultado' && itens.length === 0 && (
              <p className="busca-vazio" role="status">
                Nada encontrado para “{termo.trim()}”.
              </p>
            )}
            <ul id={idLista} role="listbox" aria-label="Resultados" className="busca-lista">
              {itens.map((item, i) => (
                <Resultado
                  key={`${item.tipo}-${item.id ?? item.op}`}
                  id={`${base}-item-${i}`}
                  item={item}
                  selecionado={i === selecionado}
                  aoEscolher={() => escolher(item)}
                  aoApontar={() => setSelecionado(i)}
                />
              ))}
            </ul>
          </div>

          <div className="busca-rodape">
            <span>
              <kbd>↑</kbd> <kbd>↓</kbd> escolher · <kbd>Enter</kbd> abrir · <kbd>Esc</kbd> fechar
            </span>
            <span role="status">{rodape}</span>
          </div>
        </div>
      </dialog>
    </>
  );
}
