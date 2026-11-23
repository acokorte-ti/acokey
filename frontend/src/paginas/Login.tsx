import { useState, type FormEvent } from 'react';
import { Campo } from '../componentes/Campo';
import { CampoSenha } from '../componentes/CampoSenha';
import { mensagemDeErro } from '../lib/api';
import { useSessao } from '../lib/sessao';

export function Login() {
  const { entrar } = useSessao();
  const [login, setLogin] = useState('');
  const [senha, setSenha] = useState('');
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    setErro(null);
    setEnviando(true);
    try {
      await entrar(login.trim(), senha);
      // Com a sessão aberta, a aplicação troca esta tela pelo sistema (ou pela troca de senha)
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setSenha('');
      setEnviando(false);
    }
  }

  return (
    <main className="tela-entrada">
      <div className="cartao-entrada">
        <img className="entrada-logo" src="/logo-acokorte.png" alt="AçoKorte" width={216} height={44} />
        <div>
          <h1>AçoKey Q</h1>
          <p className="entrada-sub">Controle de lotes — Qualidade</p>
        </div>
        <form onSubmit={enviar} className="form-coluna">
          <Campo rotulo="Usuário" para="login">
            <input
              id="login"
              type="text"
              autoComplete="username"
              autoCapitalize="off"
              spellCheck={false}
              autoFocus
              required
              maxLength={60}
              value={login}
              onChange={(e) => setLogin(e.target.value)}
            />
          </Campo>
          <Campo rotulo="Senha" para="senha">
            <CampoSenha
              id="senha"
              autoComplete="current-password"
              required
              maxLength={200}
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
            />
          </Campo>
          {erro && (
            <p className="erro-formulario" role="alert">
              {erro}
            </p>
          )}
          <button type="submit" className="botao botao-primario botao-largo" disabled={enviando}>
            {enviando ? 'Entrando…' : 'Entrar'}
          </button>
        </form>
        <p className="dica">Esqueceu a senha? Peça ao administrador do sistema para redefinir.</p>
      </div>
    </main>
  );
}
