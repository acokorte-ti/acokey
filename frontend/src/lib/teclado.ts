import type { KeyboardEvent } from 'react';

/**
 * Em formulário com muitos campos, Enter passa para o próximo campo em vez de enviar sem querer
 * (padrão do sistema antigo: handler global de Enter→Tab nos formulários de registro).
 * Uso: <form onKeyDown={enterVaiParaProximo} ...>. Em <textarea> e em botões o Enter funciona normal.
 */
export function enterVaiParaProximo(evento: KeyboardEvent<HTMLFormElement>): void {
  if (evento.key !== 'Enter' || evento.shiftKey || evento.ctrlKey || evento.altKey) return;
  const alvo = evento.target as HTMLElement;
  if (alvo.tagName === 'TEXTAREA' || alvo.tagName === 'BUTTON' || (alvo as HTMLInputElement).type === 'submit') return;
  evento.preventDefault();
  const campos = Array.from(
    evento.currentTarget.querySelectorAll<HTMLElement>('input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), button[type=submit]'),
  ).filter((c) => c.offsetParent !== null);
  const posicao = campos.indexOf(alvo);
  campos[posicao + 1]?.focus();
}
