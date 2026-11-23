import { useState, type InputHTMLAttributes } from 'react';

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>;

/** Campo de senha com o botão de olho, para conferir o que está sendo digitado. */
export function CampoSenha(props: Props) {
  const [visivel, setVisivel] = useState(false);
  return (
    <div className="campo-senha">
      <input {...props} type={visivel ? 'text' : 'password'} autoCapitalize="off" autoCorrect="off" spellCheck={false} />
      <button
        type="button"
        className="olho-senha"
        aria-label={visivel ? 'Ocultar a senha' : 'Mostrar a senha'}
        aria-pressed={visivel}
        aria-controls={props.id}
        title={visivel ? 'Ocultar a senha' : 'Mostrar a senha'}
        onClick={() => setVisivel((v) => !v)}
      >
        <svg className="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
          {visivel && <path d="M4 4l16 16" />}
        </svg>
      </button>
    </div>
  );
}
