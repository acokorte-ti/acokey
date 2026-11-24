import { useId, useRef, useState, type ClipboardEvent, type DragEvent } from 'react';

interface PropsEnvioArquivos {
  /** Arquivos escolhidos até agora (a tela guarda e manda com enviarArquivos). */
  arquivos: File[];
  aoMudar: (arquivos: File[]) => void;
  /** Ex.: ".pdf,.jpg,.jpeg,.png" */
  aceita?: string;
  multiplos?: boolean;
  rotulo?: string;
  /** Texto curto embaixo (ex.: "PDF, JPG ou PNG, até 25 MB"). */
  dica?: string;
  desabilitado?: boolean;
  /** Tamanho máximo por arquivo, em MB (o servidor confere de novo). */
  limiteMb?: number;
}

function extensaoAceita(nome: string, aceita?: string): boolean {
  if (!aceita) return true;
  const extensao = `.${nome.split('.').pop()?.toLowerCase() ?? ''}`;
  return aceita.split(',').map((e) => e.trim().toLowerCase()).includes(extensao);
}

/** Imagem colada com Ctrl+V vem sem nome: dá um nome com data e hora. */
function comNome(arquivo: File, indice: number): File {
  if (arquivo.name && arquivo.name !== 'image.png') return arquivo;
  const carimbo = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '');
  const extensao = arquivo.type === 'image/jpeg' ? 'jpg' : 'png';
  return new File([arquivo], `imagem_colada_${carimbo}_${indice + 1}.${extensao}`, { type: arquivo.type });
}

/**
 * Área de envio igual à do sistema antigo: clique ou duplo clique abre o seletor, arrastar e soltar funciona,
 * e Ctrl+V cola uma imagem copiada (print, foto do celular no WhatsApp Web...).
 */
export function EnvioArquivos({
  arquivos,
  aoMudar,
  aceita,
  multiplos = true,
  rotulo = 'Arquivos',
  dica,
  desabilitado = false,
  limiteMb = 25,
}: PropsEnvioArquivos) {
  const id = useId();
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastando, setArrastando] = useState(false);
  const [recusados, setRecusados] = useState<string[]>([]);

  function acrescentar(novos: File[]) {
    if (desabilitado || novos.length === 0) return;
    const aceitos: File[] = [];
    const fora: string[] = [];
    novos.forEach((arquivo, indice) => {
      const nomeado = comNome(arquivo, indice);
      if (!extensaoAceita(nomeado.name, aceita)) fora.push(`${nomeado.name}: tipo não aceito`);
      else if (nomeado.size > limiteMb * 1024 * 1024) fora.push(`${nomeado.name}: passa de ${limiteMb} MB`);
      else aceitos.push(nomeado);
    });
    setRecusados(fora);
    if (aceitos.length) aoMudar(multiplos ? [...arquivos, ...aceitos] : aceitos.slice(0, 1));
  }

  function soltar(evento: DragEvent<HTMLDivElement>) {
    evento.preventDefault();
    setArrastando(false);
    acrescentar(Array.from(evento.dataTransfer.files));
  }

  function colar(evento: ClipboardEvent<HTMLDivElement>) {
    const colados = Array.from(evento.clipboardData.files);
    if (colados.length) {
      evento.preventDefault();
      acrescentar(colados);
    }
  }

  return (
    <div className="envio-arquivos">
      <span className="envio-rotulo" id={`${id}-rotulo`}>
        {rotulo}
      </span>
      <div
        role="button"
        tabIndex={desabilitado ? -1 : 0}
        aria-labelledby={`${id}-rotulo`}
        aria-describedby={dica ? `${id}-dica` : undefined}
        aria-disabled={desabilitado}
        className={`envio-area ${arrastando ? 'envio-area-ativa' : ''} ${desabilitado ? 'envio-area-desabilitada' : ''}`}
        onClick={() => !desabilitado && entrada.current?.click()}
        onKeyDown={(evento) => {
          if ((evento.key === 'Enter' || evento.key === ' ') && !desabilitado) {
            evento.preventDefault();
            entrada.current?.click();
          }
        }}
        onDragOver={(evento) => {
          evento.preventDefault();
          if (!desabilitado) setArrastando(true);
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={soltar}
        onPaste={colar}
      >
        <strong>Clique para escolher, arraste até aqui ou cole com Ctrl+V</strong>
        {dica && <span id={`${id}-dica`}>{dica}</span>}
      </div>
      <input
        ref={entrada}
        type="file"
        hidden
        multiple={multiplos}
        accept={aceita}
        onChange={(evento) => {
          acrescentar(Array.from(evento.target.files ?? []));
          evento.target.value = '';
        }}
      />
      {recusados.length > 0 && (
        <ul className="envio-recusados" role="alert">
          {recusados.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {arquivos.length > 0 && (
        <ul className="envio-lista">
          {arquivos.map((arquivo, indice) => (
            <li key={`${arquivo.name}-${indice}`}>
              <span className="envio-nome">{arquivo.name}</span>
              <span className="envio-tamanho">{(arquivo.size / 1024 / 1024).toFixed(1)} MB</span>
              <button
                type="button"
                className="botao botao-fantasma botao-pequeno"
                onClick={() => aoMudar(arquivos.filter((_, i) => i !== indice))}
                disabled={desabilitado}
              >
                Tirar
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
