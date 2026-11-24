/**
 * Botão "+ Novo lote" do painel (legado: formulário "+ Novo lote" do painel, com autocompletar pela OP).
 * Escolhendo uma OP do cadastro, formato, item e quantidade vêm preenchidos (dá para ajustar antes de criar) e o
 * número do lote acompanha a OP enquanto a pessoa não digitar outro.
 */
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { ModalFormulario } from '../../componentes/Modal';
import { api, consulta, foiCancelada, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { useSessao } from '../../lib/sessao';
import { enterVaiParaProximo } from '../../lib/teclado';
import type { TipoLote } from '../../lib/tipos';
import { useAtrasado } from '../../lib/useCarga';
import type { Desenho, SugestaoOp } from './tipos';

interface Formulario {
  op: string;
  numero: string;
  tipo: TipoLote;
  qtd: string;
  coditem: string;
}

const VAZIO: Formulario = { op: '', numero: '', tipo: 'PIN', qtd: '', coditem: '' };

function classificar(descricao: string): string {
  const d = descricao.toUpperCase();
  return d.includes('PIN') ? 'PIN' : d.includes('BOX') ? 'BOX' : d.includes('ARK') ? 'ARK' : '';
}

function NovoLote({ aoFechar, aoCriar }: { aoFechar: () => void; aoCriar?: () => void }) {
  const avisos = useAvisos();
  const navegar = useNavigate();
  const [form, setForm] = useState<Formulario>(VAZIO);
  const [sugestoes, setSugestoes] = useState<SugestaoOp[]>([]);
  const [desenhos, setDesenhos] = useState<Desenho[]>([]);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  // O número do lote espelha a OP enquanto for igual à última OP copiada; digitou outro, para de espelhar
  const espelho = useRef({ ativo: true, ultima: '' });
  const preenchidaPara = useRef('');
  const opAtrasada = useAtrasado(form.op.trim(), 250);

  useEffect(() => {
    const controle = new AbortController();
    api<Desenho[]>('/recursos/desenhos', { sinal: controle.signal }).then(setDesenhos, () => setDesenhos([]));
    return () => controle.abort();
  }, []);

  useEffect(() => {
    const controle = new AbortController();
    api<SugestaoOp[]>(`/lotes/sugestoes-op${consulta({ q: opAtrasada })}`, { sinal: controle.signal }).then(setSugestoes, (e: unknown) => {
      if (!foiCancelada(e)) setSugestoes([]);
    });
    return () => controle.abort();
  }, [opAtrasada]);

  /** OP do cadastro: formato, item e quantidade (só na primeira vez que a OP aparece, para não desfazer ajustes). */
  function aplicarCadastro(base: Formulario, lista: SugestaoOp[]): Formulario {
    const op = base.op.trim();
    const achada = lista.find((s) => s.op === op);
    if (!achada || preenchidaPara.current === op) return base;
    preenchidaPara.current = op;
    return {
      ...base,
      tipo: achada.tipo ?? base.tipo,
      coditem: achada.coditem || base.coditem,
      qtd: achada.qtd ? String(achada.qtd) : base.qtd,
    };
  }

  // Quando as sugestões chegam e a OP digitada é exatamente uma delas, preenche
  useEffect(() => {
    const preenchido = aplicarCadastro(form, sugestoes);
    if (preenchido !== form) setForm(preenchido);
    // Só reage à chegada das sugestões (a digitação já passa por mudarOp)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sugestoes]);

  function mudarOp(op: string) {
    const proximo = { ...form, op };
    const e = espelho.current;
    if (e.ativo && (form.numero.trim() === '' || form.numero.trim() === e.ultima)) {
      proximo.numero = op.trim();
      e.ultima = op.trim();
    }
    setForm(aplicarCadastro(proximo, sugestoes));
  }

  function mudarNumero(numero: string) {
    if (numero.trim() !== form.op.trim()) espelho.current.ativo = false;
    setForm({ ...form, numero });
  }

  async function criar() {
    const qtd = Number(form.qtd);
    if (!form.op.trim() || !form.numero.trim() || !Number.isInteger(qtd) || qtd <= 0) {
      setErro('Preencha OP, lote, formato (PIN/BOX/ARK) e quantidade válida.');
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const r = await api<{ id: number; numero: string }>('/lotes', {
        metodo: 'POST',
        corpo: { op: form.op.trim(), numero: form.numero.trim(), tipo: form.tipo, qtd, coditem: form.coditem.trim() },
      });
      avisos.sucesso(`Lote ${r.numero} criado.`);
      aoCriar?.();
      navegar(`/lotes/${r.id}`);
    } catch (e) {
      setErro(mensagemDeErro(e));
      setEnviando(false);
    }
  }

  const escolhida = sugestoes.find((s) => s.op === form.op.trim());

  return (
    <ModalFormulario titulo="Novo lote" aoFechar={aoFechar} aoEnviar={criar} enviando={enviando} erro={erro} rotuloEnviar="Criar lote" largura="larga">
      <div className="lt-novo" onKeyDown={(e) => enterVaiParaProximo(e as unknown as KeyboardEvent<HTMLFormElement>)}>
        <div className="linha-campos">
          <Campo rotulo="Nº da OP" para="novo-op" obrigatorio dica={escolhida ? `${escolhida.descricao_curta || escolhida.descricao}${escolhida.cliente ? ` · ${escolhida.cliente}` : ''}` : 'Digite para buscar no cadastro de OPs.'}>
            <input id="novo-op" type="text" value={form.op} onChange={(e) => mudarOp(e.target.value)} list="lt-lista-ops" maxLength={20} autoComplete="off" />
            <datalist id="lt-lista-ops">
              {sugestoes.map((s) => (
                <option key={s.op} value={s.op}>
                  {[s.tipo, s.coditem, s.descricao_curta || s.descricao].filter(Boolean).join(' - ')}
                </option>
              ))}
            </datalist>
          </Campo>
          <Campo rotulo="Nº do lote" para="novo-numero" obrigatorio>
            <input id="novo-numero" type="text" value={form.numero} onChange={(e) => mudarNumero(e.target.value)} maxLength={40} autoComplete="off" />
          </Campo>
          <Campo rotulo="Formato da peça" para="novo-tipo">
            <select id="novo-tipo" value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value as TipoLote })}>
              <option>PIN</option>
              <option>BOX</option>
              <option>ARK</option>
            </select>
          </Campo>
          <Campo rotulo="Quantidade de peças" para="novo-qtd" obrigatorio>
            <input id="novo-qtd" type="number" min={1} value={form.qtd} onChange={(e) => setForm({ ...form, qtd: e.target.value })} />
          </Campo>
          <Campo
            rotulo="Código do item / desenho (opcional)"
            para="novo-coditem"
            dica="CODITEM: define o desenho técnico e as cotas usadas na inspeção dimensional."
          >
            <input id="novo-coditem" type="text" value={form.coditem} onChange={(e) => setForm({ ...form, coditem: e.target.value })} list="lt-lista-coditens" maxLength={40} autoComplete="off" />
            <datalist id="lt-lista-coditens">
              {desenhos.map((d) => (
                <option key={d.arquivo} value={d.coditem}>
                  {[classificar(d.descricao), d.descricao].filter(Boolean).join(' - ')}
                </option>
              ))}
            </datalist>
          </Campo>
        </div>
        {escolhida && escolhida.lotes > 0 && (
          <p className="dica texto-alerta">
            A OP {escolhida.op} já tem {escolhida.lotes} lote{escolhida.lotes > 1 ? 's' : ''} no sistema.
          </p>
        )}
        <p className="dica">
          Escolhendo uma OP já cadastrada, o formato, o código do item e a quantidade são preenchidos automaticamente (pode ajustar antes de criar). O código do item também
          permite usar as cotas cadastradas em Especificações para pré-preencher a inspeção dimensional.
        </p>
      </div>
    </ModalFormulario>
  );
}

/** Aparece só para quem pode criar lote (Qualidade ou PCP). `aoCriar` recarrega o painel. */
export function BotaoNovoLote({ aoCriar }: { aoCriar?: () => void }) {
  const { pode } = useSessao();
  const [aberto, setAberto] = useState(false);
  if (!(pode.qualidade || pode.pcp)) return null;
  return (
    <>
      <button type="button" className="botao botao-primario" onClick={() => setAberto(true)}>
        + Novo lote
      </button>
      {aberto && <NovoLote aoFechar={() => setAberto(false)} aoCriar={aoCriar} />}
    </>
  );
}
