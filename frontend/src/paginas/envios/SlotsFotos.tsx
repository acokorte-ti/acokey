import { useEffect, useId, useMemo, useRef, useState, type DragEvent } from 'react';

const ACEITAS = ['.jpg', '.jpeg', '.png'];

interface Props {
  fotos: File[];
  aoMudar: (fotos: File[]) => void;
  desabilitado?: boolean;
  limiteMb?: number;
}

function aceita(arquivo: File): boolean {
  const extensao = `.${arquivo.name.split('.').pop()?.toLowerCase() ?? ''}`;
  return ACEITAS.includes(extensao);
}

/** Imagem colada (print, foto do WhatsApp Web) vem sem nome: dá um com data e hora. */
function nomeada(arquivo: File, indice: number): File {
  if (arquivo.name && arquivo.name !== 'image.png') return arquivo;
  const carimbo = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '');
  const extensao = arquivo.type === 'image/jpeg' ? 'jpg' : 'png';
  return new File([arquivo], `foto_colada_${carimbo}_${indice + 1}.${extensao}`, { type: arquivo.type });
}

/**
 * Fotos dos corpos de prova / das peças, como no sistema antigo: cada foto vira uma miniatura e sempre sobra um
 * espaço vazio. Ctrl+V cola uma imagem copiada (em qualquer ponto da tela), duplo clique abre o seletor de arquivos,
 * e também dá para arrastar e soltar.
 */
export function SlotsFotos({ fotos, aoMudar, desabilitado = false, limiteMb = 25 }: Props) {
  const id = useId();
  const entrada = useRef<HTMLInputElement>(null);
  const [recusadas, setRecusadas] = useState<string[]>([]);
  const [arrastando, setArrastando] = useState(false);
  const atuais = useRef(fotos);
  atuais.current = fotos;

  const enderecos = useMemo(() => fotos.map((f) => URL.createObjectURL(f)), [fotos]);
  useEffect(() => () => enderecos.forEach((e) => URL.revokeObjectURL(e)), [enderecos]);

  function acrescentar(novas: File[]) {
    if (desabilitado || novas.length === 0) return;
    const boas: File[] = [];
    const fora: string[] = [];
    novas.forEach((arquivo, indice) => {
      const foto = nomeada(arquivo, indice);
      if (!aceita(foto)) fora.push(`${foto.name}: só JPG ou PNG`);
      else if (foto.size > limiteMb * 1024 * 1024) fora.push(`${foto.name}: passa de ${limiteMb} MB`);
      else boas.push(foto);
    });
    setRecusadas(fora);
    if (boas.length) aoMudar([...atuais.current, ...boas]);
  }
  const acrescentarRef = useRef(acrescentar);
  acrescentarRef.current = acrescentar;

  // Ctrl+V em qualquer ponto da tela cola a imagem (só não rouba a colagem de texto num campo)
  useEffect(() => {
    function colar(evento: ClipboardEvent) {
      const dados = evento.clipboardData;
      if (!dados) return;
      const imagens = Array.from(dados.files).filter((f) => f.type.startsWith('image/'));
      if (!imagens.length) return;
      const alvo = evento.target as HTMLElement | null;
      const campoDeTexto = alvo && (alvo.tagName === 'TEXTAREA' || (alvo.tagName === 'INPUT' && (alvo as HTMLInputElement).type === 'text'));
      if (campoDeTexto && dados.types.includes('text/plain')) return;
      evento.preventDefault();
      acrescentarRef.current(imagens);
    }
    document.addEventListener('paste', colar);
    return () => document.removeEventListener('paste', colar);
  }, []);

  function soltar(evento: DragEvent<HTMLDivElement>) {
    evento.preventDefault();
    setArrastando(false);
    acrescentar(Array.from(evento.dataTransfer.files));
  }

  return (
    <div className="env-fotos">
      <div
        className={`env-fotos-grade ${arrastando ? 'env-fotos-arrastando' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!desabilitado) setArrastando(true);
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={soltar}
      >
        {fotos.map((foto, indice) => (
          <figure key={`${foto.name}-${indice}`} className="env-foto">
            <img src={enderecos[indice]} alt={foto.name} />
            <figcaption title={foto.name}>{foto.name}</figcaption>
            <button
              type="button"
              className="env-foto-tirar"
              aria-label={`Tirar a foto ${foto.name}`}
              onClick={() => aoMudar(fotos.filter((_, i) => i !== indice))}
              disabled={desabilitado}
            >
              ×
            </button>
          </figure>
        ))}
        <div
          role="button"
          tabIndex={desabilitado ? -1 : 0}
          aria-describedby={`${id}-dica`}
          aria-disabled={desabilitado}
          className="env-foto env-foto-vazia"
          onDoubleClick={() => !desabilitado && entrada.current?.click()}
          onKeyDown={(evento) => {
            if ((evento.key === 'Enter' || evento.key === ' ') && !desabilitado) {
              evento.preventDefault();
              entrada.current?.click();
            }
          }}
        >
          <span aria-hidden="true" className="env-foto-icone">
            📷
          </span>
          <span>Clique para focar</span>
          <span>Ctrl+V ou duplo clique</span>
        </div>
      </div>
      <p className="dica" id={`${id}-dica`}>
        Cole com <strong>Ctrl+V</strong>, dê <strong>duplo clique</strong> no quadro vazio para escolher no computador ou arraste as
        fotos até aqui. JPG ou PNG, até {limiteMb} MB cada.
      </p>
      <input
        ref={entrada}
        type="file"
        hidden
        multiple
        accept={ACEITAS.join(',')}
        onChange={(evento) => {
          acrescentar(Array.from(evento.target.files ?? []));
          evento.target.value = '';
        }}
      />
      {recusadas.length > 0 && (
        <ul className="envio-recusados" role="alert">
          {recusadas.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
