/**
 * Cliente da API.
 *
 * A sessão é um cookie HttpOnly (o JavaScript não enxerga). O token CSRF vem no login e em
 * /auth/eu e fica SÓ em memória: toda requisição que não seja GET manda o cabeçalho X-CSRF-Token.
 */

export class ErroApi extends Error {
  readonly status: number;

  constructor(status: number, mensagem: string) {
    super(mensagem);
    this.name = 'ErroApi';
    this.status = status;
  }
}

type Metodo = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

interface OpcoesChamada {
  metodo?: Metodo;
  corpo?: unknown;
  sinal?: AbortSignal;
  /** Login: um 401 aqui é "senha errada", não "sessão expirada". */
  semTratarSessao?: boolean;
}

interface Tratadores {
  /** 401: a sessão acabou, volta para o login. */
  aoPerderSessao: () => void;
  /** 403 "TROCAR_SENHA": o usuário precisa trocar a senha antes de qualquer coisa. */
  aoExigirTrocaSenha: () => void;
}

let csrf: string | null = null;
let tratadores: Tratadores = { aoPerderSessao: () => {}, aoExigirTrocaSenha: () => {} };

export function definirCsrf(valor: string | null): void {
  csrf = valor;
}

export function registrarTratadores(novos: Tratadores): void {
  tratadores = novos;
}

export type Parametros = Record<string, string | number | boolean | null | undefined>;

/** Monta a query string ignorando o que está vazio. */
export function consulta(parametros: Parametros): string {
  const p = new URLSearchParams();
  for (const [chave, valor] of Object.entries(parametros)) {
    if (valor === null || valor === undefined || valor === '') continue;
    p.set(chave, String(valor));
  }
  const texto = p.toString();
  return texto ? `?${texto}` : '';
}

/** Endereço de um arquivo da API (ex.: anexo): é um GET comum, o navegador manda o cookie sozinho. */
export function enderecoApi(caminho: string, parametros: Parametros = {}): string {
  return `/api${caminho}${consulta(parametros)}`;
}

function mensagemPadrao(status: number): string {
  if (status === 401) return 'Sessão expirada. Entre novamente.';
  if (status === 403) return 'Seu usuário não tem permissão para esta ação.';
  if (status === 404) return 'Não encontrado.';
  if (status === 429) return 'Muitas tentativas. Aguarde um pouco e tente de novo.';
  if (status >= 500) return 'O servidor não conseguiu atender agora. Tente de novo em instantes.';
  return 'Não foi possível concluir a operação.';
}

async function lerDetalhe(resposta: Response): Promise<string | null> {
  try {
    const dados: unknown = await resposta.json();
    if (dados && typeof dados === 'object' && 'detail' in dados) {
      const detalhe = (dados as { detail: unknown }).detail;
      if (typeof detalhe === 'string' && detalhe.trim()) return detalhe;
    }
  } catch {
    // corpo vazio ou que não é JSON: usa a mensagem padrão
  }
  return null;
}

export async function api<T>(caminho: string, opcoes: OpcoesChamada = {}): Promise<T> {
  const metodo = opcoes.metodo ?? 'GET';
  const cabecalhos: Record<string, string> = { Accept: 'application/json' };
  if (opcoes.corpo !== undefined) cabecalhos['Content-Type'] = 'application/json';
  if (metodo !== 'GET' && csrf) cabecalhos['X-CSRF-Token'] = csrf;

  let resposta: Response;
  try {
    resposta = await fetch(`/api${caminho}`, {
      method: metodo,
      credentials: 'same-origin',
      headers: cabecalhos,
      body: opcoes.corpo !== undefined ? JSON.stringify(opcoes.corpo) : undefined,
      signal: opcoes.sinal,
    });
  } catch (erro) {
    if (erro instanceof DOMException && erro.name === 'AbortError') throw erro;
    throw new ErroApi(0, 'Não foi possível falar com o servidor. Confira a rede e tente de novo.');
  }

  if (!resposta.ok) {
    const detalhe = await lerDetalhe(resposta);
    if (resposta.status === 401 && !opcoes.semTratarSessao) {
      tratadores.aoPerderSessao();
    }
    if (resposta.status === 403 && detalhe === 'TROCAR_SENHA') {
      tratadores.aoExigirTrocaSenha();
      throw new ErroApi(403, 'Antes de continuar, é preciso trocar a senha.');
    }
    throw new ErroApi(resposta.status, detalhe ?? mensagemPadrao(resposta.status));
  }

  if (resposta.status === 204) return undefined as T;
  return (await resposta.json()) as T;
}

/**
 * Envia arquivos (multipart/form-data) junto com campos de texto. Mesmo tratamento de sessão, CSRF e erros de `api`.
 * Ex.: enviarArquivos('/lotes/7/etapas/receb_mp/anexos', { arquivos: lista, sub: '' })
 */
export async function enviarArquivos<T>(
  caminho: string,
  campos: Record<string, string | number | boolean | Blob | Blob[] | null | undefined>,
  opcoes: { metodo?: 'POST' | 'PUT'; sinal?: AbortSignal } = {},
): Promise<T> {
  const formulario = new FormData();
  for (const [chave, valor] of Object.entries(campos)) {
    if (valor === null || valor === undefined) continue;
    if (Array.isArray(valor)) {
      for (const item of valor) formulario.append(chave, item, item instanceof File ? item.name : undefined);
    } else if (valor instanceof Blob) {
      formulario.append(chave, valor, valor instanceof File ? valor.name : undefined);
    } else {
      formulario.append(chave, String(valor));
    }
  }
  const cabecalhos: Record<string, string> = { Accept: 'application/json' };
  if (csrf) cabecalhos['X-CSRF-Token'] = csrf;

  let resposta: Response;
  try {
    // Sem Content-Type: o navegador põe o multipart com a fronteira certa
    resposta = await fetch(`/api${caminho}`, {
      method: opcoes.metodo ?? 'POST',
      credentials: 'same-origin',
      headers: cabecalhos,
      body: formulario,
      signal: opcoes.sinal,
    });
  } catch (erro) {
    if (erro instanceof DOMException && erro.name === 'AbortError') throw erro;
    throw new ErroApi(0, 'Não foi possível enviar o arquivo. Confira a rede e tente de novo.');
  }
  if (!resposta.ok) {
    const detalhe = await lerDetalhe(resposta);
    if (resposta.status === 401) tratadores.aoPerderSessao();
    if (resposta.status === 403 && detalhe === 'TROCAR_SENHA') {
      tratadores.aoExigirTrocaSenha();
      throw new ErroApi(403, 'Antes de continuar, é preciso trocar a senha.');
    }
    if (resposta.status === 413) throw new ErroApi(413, detalhe ?? 'O arquivo é grande demais.');
    throw new ErroApi(resposta.status, detalhe ?? mensagemPadrao(resposta.status));
  }
  if (resposta.status === 204) return undefined as T;
  return (await resposta.json()) as T;
}

/**
 * Baixa um arquivo gerado por POST (ex.: exportação) ou GET autenticado, salvando com o nome que o servidor mandar.
 * Para só abrir um PDF/anexo, prefira um <a href={enderecoApi(...)} target="_blank">.
 */
export async function baixarArquivo(caminho: string, opcoes: { metodo?: Metodo; corpo?: unknown } = {}): Promise<void> {
  const metodo = opcoes.metodo ?? 'GET';
  const cabecalhos: Record<string, string> = {};
  if (opcoes.corpo !== undefined) cabecalhos['Content-Type'] = 'application/json';
  if (metodo !== 'GET' && csrf) cabecalhos['X-CSRF-Token'] = csrf;
  const resposta = await fetch(`/api${caminho}`, {
    method: metodo,
    credentials: 'same-origin',
    headers: cabecalhos,
    body: opcoes.corpo !== undefined ? JSON.stringify(opcoes.corpo) : undefined,
  });
  if (!resposta.ok) {
    const detalhe = await lerDetalhe(resposta);
    if (resposta.status === 401) tratadores.aoPerderSessao();
    throw new ErroApi(resposta.status, detalhe ?? mensagemPadrao(resposta.status));
  }
  const disposicao = resposta.headers.get('content-disposition') ?? '';
  const nome =
    decodeURIComponent(/filename\*=UTF-8''([^;]+)/i.exec(disposicao)?.[1] ?? '') ||
    /filename="?([^";]+)"?/i.exec(disposicao)?.[1] ||
    'arquivo';
  const url = URL.createObjectURL(await resposta.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = nome;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Texto de um erro qualquer, para mostrar na tela. */
export function mensagemDeErro(erro: unknown): string {
  if (erro instanceof Error && erro.message) return erro.message;
  return 'Erro inesperado.';
}

export function foiCancelada(erro: unknown): boolean {
  return erro instanceof DOMException && erro.name === 'AbortError';
}
