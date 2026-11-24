import { useEffect, useId, useRef, useState, type ClipboardEvent, type DragEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Faixa } from '../../componentes/Estados';
import { dataCurta, TRACO } from '../../lib/formato';
import type { Equipamento, Pessoa } from './tipos';

/** "36,0" ou "36.0" -> 36; vazio ou inválido -> null. */
export function numeroDigitado(texto: string): number | null {
  const limpo = texto.trim().replace(',', '.');
  if (!limpo) return null;
  const numero = Number(limpo);
  return Number.isFinite(numero) ? numero : null;
}

/** 36 -> "36,0" */
export function decimal(numero: number, casas = 1): string {
  return numero.toFixed(casas).replace('.', ',');
}

/** Bloco "dados puxados do sistema": o que vem do cadastro e não se digita. */
export function Resumo({ itens }: { itens: [string, ReactNode][] }) {
  return (
    <section className="cartao rel-resumo" aria-label="Dados puxados do sistema">
      <span className="rel-origem">dados puxados do sistema</span>
      <dl className="rel-resumo-grade">
        {itens.map(([rotulo, valor]) => (
          <div key={rotulo}>
            <dt>{rotulo}</dt>
            <dd>{valor === '' || valor === null || valor === undefined ? TRACO : valor}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Erro ao abrir a tela (ex.: especificação não cadastrada): mensagem do servidor e o caminho de volta. */
export function ErroRelatorio({ mensagem, loteId }: { mensagem: string; loteId: number | null }) {
  return (
    <Faixa tipo="erro" papel="alert">
      <p>{mensagem}</p>
      <p className="acoes">
        {loteId !== null && <Link to={`/lotes/${loteId}`}>Voltar ao lote</Link>}
        {/especifica/i.test(mensagem) && <Link to="/especificacoes">Abrir Especificações</Link>}
      </p>
    </Faixa>
  );
}

// ---------------------------------------------------------------- equipamento (forno, durômetro)

interface PropsSeletorEquipamento {
  id: string;
  rotulo: string;
  lista: Equipamento[];
  valor: string;
  aoMudar: (codigo: string) => void;
  obrigatorio?: boolean;
  /** Texto quando o cadastro não tem nenhum equipamento deste tipo. */
  vazio: string;
}

/** Escolha do equipamento com o certificado e a validade da calibração (aviso se vencida). */
export function SeletorEquipamento({ id, rotulo, lista, valor, aoMudar, obrigatorio = false, vazio }: PropsSeletorEquipamento) {
  const escolhido = lista.find((e) => e.codigo === valor);
  const foraDaLista = valor !== '' && !escolhido;
  if (lista.length === 0 && !foraDaLista) {
    return (
      <div className="campo">
        <span className="rotulo">{rotulo}</span>
        <Faixa tipo="alerta">
          {vazio} <Link to="/equipamentos">Abrir Equipamentos</Link>
        </Faixa>
      </div>
    );
  }
  return (
    <Campo rotulo={rotulo} para={id} obrigatorio={obrigatorio}>
      <select id={id} value={valor} required={obrigatorio} onChange={(e) => aoMudar(e.target.value)}>
        {!obrigatorio && <option value="">— nenhum —</option>}
        {obrigatorio && valor === '' && <option value="">Escolha…</option>}
        {foraDaLista && <option value={valor}>{valor} (fora do cadastro ativo)</option>}
        {lista.map((e) => (
          <option key={e.codigo} value={e.codigo}>
            {e.rotulo}
          </option>
        ))}
      </select>
      {escolhido && <Calibracao equipamento={escolhido} />}
    </Campo>
  );
}

export function Calibracao({ equipamento }: { equipamento: Equipamento }) {
  const { certificado, data_calibracao, validade_calibracao, vencida } = equipamento;
  if (!certificado && !data_calibracao && !validade_calibracao) {
    return <span className="dica">Sem dados de calibração no cadastro.</span>;
  }
  return (
    <span className="dica">
      Certificado {certificado || TRACO} · calibrado em {dataCurta(data_calibracao)} · válido até {dataCurta(validade_calibracao)}
      {vencida && <strong className="texto-erro"> · Calibração vencida</strong>}
    </span>
  );
}

// ---------------------------------------------------------------- pessoas

interface PropsSeletorPessoa {
  id: string;
  rotulo: string;
  lista: Pessoa[];
  valor: number | '';
  aoMudar: (id: number | '') => void;
  dica?: ReactNode;
}

export function SeletorPessoa({ id, rotulo, lista, valor, aoMudar, dica }: PropsSeletorPessoa) {
  const escolhida = lista.find((p) => p.id === valor);
  return (
    <Campo
      rotulo={rotulo}
      para={id}
      obrigatorio
      dica={
        dica ?? (escolhida && !escolhida.tem_assinatura ? 'Sem imagem de assinatura cadastrada: o PDF sai só com o nome.' : undefined)
      }
    >
      <select id={id} value={valor} required onChange={(e) => aoMudar(e.target.value ? Number(e.target.value) : '')}>
        <option value="">Escolha…</option>
        {lista.map((p) => (
          <option key={p.id} value={p.id}>
            {p.cargo ? `${p.nome} — ${p.cargo}` : p.nome}
          </option>
        ))}
      </select>
    </Campo>
  );
}

/** Quem fica pré-escolhido: o usuário logado, se estiver na lista; senão, o único da lista. */
export function escolhaInicial(lista: Pessoa[], usuarioId: number): number | '' {
  if (lista.some((p) => p.id === usuarioId)) return usuarioId;
  return lista.length === 1 ? lista[0].id : '';
}

// ---------------------------------------------------------------- imagem colada (Ctrl+V) ou escolhida

const ACEITAS = ['image/png', 'image/jpeg'];
const LIMITE_MB = 25;

interface PropsSlotImagem {
  rotulo: string;
  /** Nome base do arquivo colado (ex.: "grafico_tempera"). */
  campo: string;
  arquivo: File | null;
  aoMudar: (arquivo: File | null) => void;
  desabilitado?: boolean;
}

function nomeado(arquivo: File, campo: string): File {
  if (arquivo.name && arquivo.name !== 'image.png' && /\.(png|jpe?g)$/i.test(arquivo.name)) return arquivo;
  const extensao = arquivo.type === 'image/jpeg' ? 'jpg' : 'png';
  return new File([arquivo], `${campo}.${extensao}`, { type: arquivo.type });
}

/**
 * Caixa de imagem igual à do sistema antigo: clique na caixa e cole (Ctrl+V) um recorte, ou dê duplo clique (ou Enter)
 * para escolher o arquivo. Também aceita arrastar. PNG ou JPG.
 */
export function SlotImagem({ rotulo, campo, arquivo, aoMudar, desabilitado = false }: PropsSlotImagem) {
  const id = useId();
  const entrada = useRef<HTMLInputElement>(null);
  const [previa, setPrevia] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [arrastando, setArrastando] = useState(false);

  useEffect(() => {
    if (!arquivo) {
      setPrevia(null);
      return;
    }
    const url = URL.createObjectURL(arquivo);
    setPrevia(url);
    return () => URL.revokeObjectURL(url);
  }, [arquivo]);

  function aceitar(candidato: File | undefined | null) {
    if (!candidato || desabilitado) return;
    if (!ACEITAS.includes(candidato.type) && !/\.(png|jpe?g)$/i.test(candidato.name)) {
      setErro('Use uma imagem PNG ou JPG.');
      return;
    }
    if (candidato.size > LIMITE_MB * 1024 * 1024) {
      setErro(`A imagem passa de ${LIMITE_MB} MB.`);
      return;
    }
    setErro(null);
    aoMudar(nomeado(candidato, campo));
  }

  function colar(evento: ClipboardEvent<HTMLDivElement>) {
    const item = Array.from(evento.clipboardData.items).find((i) => i.type.startsWith('image/'));
    if (item) {
      evento.preventDefault();
      aceitar(item.getAsFile());
    }
  }

  function soltar(evento: DragEvent<HTMLDivElement>) {
    evento.preventDefault();
    setArrastando(false);
    aceitar(evento.dataTransfer.files[0]);
  }

  return (
    <div className="rel-slot-campo">
      <span className="rotulo" id={`${id}-rotulo`}>
        {rotulo}
      </span>
      <div
        role="button"
        tabIndex={desabilitado ? -1 : 0}
        aria-labelledby={`${id}-rotulo`}
        aria-describedby={`${id}-dica`}
        className={`rel-slot ${previa ? 'rel-slot-com-imagem' : ''} ${arrastando ? 'rel-slot-arrastando' : ''}`}
        onDoubleClick={() => !arquivo && entrada.current?.click()}
        onKeyDown={(evento) => {
          if ((evento.key === 'Enter' || evento.key === ' ') && !arquivo) {
            evento.preventDefault();
            entrada.current?.click();
          }
          if ((evento.key === 'Delete' || evento.key === 'Backspace') && arquivo) {
            evento.preventDefault();
            aoMudar(null);
          }
        }}
        onPaste={colar}
        onDragOver={(evento) => {
          evento.preventDefault();
          setArrastando(true);
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={soltar}
      >
        {previa ? (
          <img src={previa} alt={`Imagem escolhida: ${rotulo}`} />
        ) : (
          <span className="rel-slot-texto" id={`${id}-dica`}>
            Clique aqui e cole (Ctrl+V)
            <br />
            ou dê duplo clique para escolher
          </span>
        )}
      </div>
      {previa && (
        <span className="rel-slot-acoes" id={`${id}-dica`}>
          <span className="dica">{arquivo?.name}</span>
          <button type="button" className="botao botao-pequeno botao-fantasma" onClick={() => aoMudar(null)} disabled={desabilitado}>
            Tirar
          </button>
        </span>
      )}
      {erro && (
        <span className="texto-erro" role="alert">
          {erro}
        </span>
      )}
      <input
        ref={entrada}
        type="file"
        hidden
        accept=".png,.jpg,.jpeg"
        onChange={(evento) => {
          aceitar(evento.target.files?.[0]);
          evento.target.value = '';
        }}
      />
    </div>
  );
}
