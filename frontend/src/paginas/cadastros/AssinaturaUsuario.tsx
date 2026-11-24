import { useEffect, useRef, useState, type DragEvent } from 'react';
import { Modal } from '../../componentes/Modal';
import { api, enderecoApi, enviarArquivos, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import type { Usuario } from '../../lib/tipos';
import './cadastros.css';

const LIMITE_MB = 5;
const TIPOS = ['image/png', 'image/jpeg'];

/** Imagem da assinatura do usuário. `versao` muda depois de trocar, para o navegador não mostrar a antiga. */
export function MiniaturaAssinatura({ usuario, versao }: { usuario: Pick<Usuario, 'id' | 'login'>; versao: number }) {
  return (
    <img
      className="cad-assinatura-mini"
      src={enderecoApi(`/usuarios/${usuario.id}/assinatura`, { v: versao })}
      alt={`Assinatura de ${usuario.login}`}
      loading="lazy"
    />
  );
}

/** Imagem colada com Ctrl+V vem sem nome: dá um nome pelo tipo. */
function comNome(arquivo: File): File {
  const extensao = arquivo.type === 'image/jpeg' ? 'jpg' : 'png';
  if (arquivo.name && arquivo.name !== 'image.png') return arquivo;
  return new File([arquivo], `assinatura_colada.${extensao}`, { type: arquivo.type });
}

interface Props {
  usuario: Usuario;
  versao: number;
  aoFechar: () => void;
  /** Depois de gravar ou tirar: o usuário como o servidor devolveu. */
  aoMudar: (usuario: Usuario) => void;
}

/**
 * Assinatura digital (PNG ou JPG), como no sistema antigo: clique na caixa e cole com Ctrl+V,
 * ou clique duas vezes para escolher o arquivo (também dá para arrastar). Só o administrador grava.
 */
export function ModalAssinatura({ usuario, versao, aoFechar, aoMudar }: Props) {
  const avisos = useAvisos();
  const entrada = useRef<HTMLInputElement>(null);
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [previa, setPrevia] = useState<string | null>(null);
  const [ativa, setAtiva] = useState(false);
  const [dica, setDica] = useState<string>('Clique na caixa (ela fica com borda azul) e aperte Ctrl+V.');
  const [confirmarTirar, setConfirmarTirar] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // A prévia é um endereço temporário do navegador: libera quando troca ou fecha
  useEffect(() => {
    if (!arquivo) {
      setPrevia(null);
      return undefined;
    }
    const url = URL.createObjectURL(arquivo);
    setPrevia(url);
    return () => URL.revokeObjectURL(url);
  }, [arquivo]);

  function receber(novo: File | undefined) {
    setErro(null);
    if (!novo) return;
    if (!TIPOS.includes(novo.type)) {
      setDica('O arquivo precisa ser uma imagem PNG ou JPG.');
      return;
    }
    if (novo.size > LIMITE_MB * 1024 * 1024) {
      setDica(`A imagem passa de ${LIMITE_MB} MB.`);
      return;
    }
    setArquivo(comNome(novo));
    setDica('Imagem recebida. Confira e clique em “Gravar assinatura”.');
  }

  // Ctrl+V em qualquer ponto da janela enquanto a caixa estiver ativa (alguns navegadores tiram o foco da caixa)
  useEffect(() => {
    if (!ativa) return undefined;
    function colar(evento: ClipboardEvent) {
      const itens = Array.from(evento.clipboardData?.items ?? []);
      const imagem = itens.find((i) => i.type.startsWith('image/'));
      if (!imagem) {
        setDica('O que está na área de transferência não é uma imagem. Copie uma imagem primeiro (ex.: um recorte da tela) e tente de novo.');
        return;
      }
      evento.preventDefault();
      receber(imagem.getAsFile() ?? undefined);
    }
    document.addEventListener('paste', colar);
    return () => document.removeEventListener('paste', colar);
  }, [ativa]);

  function soltar(evento: DragEvent<HTMLDivElement>) {
    evento.preventDefault();
    receber(evento.dataTransfer.files[0]);
  }

  async function gravar() {
    if (!arquivo) return;
    setErro(null);
    setEnviando(true);
    try {
      const atualizado = await enviarArquivos<Usuario>(`/usuarios/${usuario.id}/assinatura`, { arquivo });
      avisos.sucesso(`Assinatura de ${usuario.login} gravada.`);
      aoMudar(atualizado);
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  async function tirar() {
    setErro(null);
    setEnviando(true);
    try {
      const atualizado = await api<Usuario>(`/usuarios/${usuario.id}/assinatura`, { metodo: 'DELETE' });
      avisos.sucesso(`Assinatura de ${usuario.login} retirada.`);
      aoMudar(atualizado);
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Modal titulo={`Assinatura digital de ${usuario.login}`} aoFechar={aoFechar} largura="larga">
      <div className="modal-corpo">
        <p className="apoio">
          PNG ou JPG com fundo transparente ou branco, de preferência com uns 400 × 120 pixels. Aparece nos relatórios acima da
          linha “Executado por” ou “Aprovado por” e no carimbo APROVADO dos certificados de matéria-prima.
        </p>
        {usuario.tem_assinatura && (
          <div className="cad-assinatura-atual">
            <span className="rotulo-discreto">Assinatura atual</span>
            <MiniaturaAssinatura usuario={usuario} versao={versao} />
          </div>
        )}
        <div
          role="button"
          tabIndex={0}
          aria-label="Caixa da assinatura nova: clique e cole com Ctrl+V, ou clique duas vezes para escolher o arquivo"
          className={`cad-assinatura-caixa ${ativa ? 'cad-assinatura-ativa' : ''} ${previa ? 'cad-assinatura-com-imagem' : ''}`}
          onMouseDown={() => setAtiva(true)}
          onFocus={() => setAtiva(true)}
          onBlur={() => setAtiva(false)}
          onDoubleClick={() => entrada.current?.click()}
          onKeyDown={(evento) => {
            if (evento.key === 'Enter' || evento.key === ' ') {
              evento.preventDefault();
              entrada.current?.click();
            }
          }}
          onDragOver={(evento) => evento.preventDefault()}
          onDrop={soltar}
        >
          {previa ? (
            <img src={previa} alt="Prévia da assinatura nova" />
          ) : (
            <span className="cad-assinatura-convite">
              Clique na caixa e <strong>cole (Ctrl+V)</strong> a assinatura,
              <br />
              ou <strong>clique 2 vezes</strong> para escolher um arquivo
            </span>
          )}
        </div>
        <p className="dica" aria-live="polite">
          {dica}
        </p>
        <input
          ref={entrada}
          type="file"
          hidden
          accept=".png,.jpg,.jpeg,image/png,image/jpeg"
          onChange={(evento) => {
            receber(evento.target.files?.[0]);
            evento.target.value = '';
          }}
        />
        {confirmarTirar && (
          <p className="erro-formulario">
            Tirar a assinatura de {usuario.login}? Os próximos relatórios e carimbos dessa pessoa sairão sem a imagem (a imagem
            antiga continua guardada no servidor).
          </p>
        )}
        {erro && (
          <p className="erro-formulario" role="alert">
            {erro}
          </p>
        )}
      </div>
      <div className="modal-rodape">
        {usuario.tem_assinatura &&
          (confirmarTirar ? (
            <button type="button" className="botao botao-perigo" disabled={enviando} onClick={() => void tirar()}>
              Sim, tirar a assinatura
            </button>
          ) : (
            <button type="button" className="botao botao-perigo-contorno" disabled={enviando} onClick={() => setConfirmarTirar(true)}>
              Tirar assinatura
            </button>
          ))}
        {arquivo && (
          <button type="button" className="botao" disabled={enviando} onClick={() => setArquivo(null)}>
            Limpar
          </button>
        )}
        <button type="button" className="botao" onClick={aoFechar} disabled={enviando}>
          Fechar
        </button>
        <button type="button" className="botao botao-primario" disabled={!arquivo || enviando} onClick={() => void gravar()}>
          {enviando ? 'Gravando…' : 'Gravar assinatura'}
        </button>
      </div>
    </Modal>
  );
}
