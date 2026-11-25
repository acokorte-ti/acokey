import { useState, type FormEvent } from 'react';
import { api, mensagemDeErro } from '../lib/api';
import { useAvisos } from '../lib/avisos';
import { useSessao } from '../lib/sessao';
import type { Usuario } from '../lib/tipos';
import { Campo } from './Campo';
import { CampoSenha } from './CampoSenha';

/** Troca da própria senha: usada na tela obrigatória do primeiro acesso e em "Minha conta". */
export function FormSenha({ rotuloSenhaAtual = 'Senha atual' }: { rotuloSenhaAtual?: string }) {
  const { atualizarUsuario } = useSessao();
  const avisos = useAvisos();
  const [atual, setAtual] = useState('');
  const [nova, setNova] = useState('');
  const [confirmacao, setConfirmacao] = useState('');
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    if (nova !== confirmacao) {
      setErro('A confirmação não é igual à senha nova.');
      return;
    }
    setErro(null);
    setEnviando(true);
    try {
      const resposta = await api<{ usuario: Usuario }>('/auth/trocar-senha', {
        metodo: 'POST',
        corpo: { senha_atual: atual, senha_nova: nova },
      });
      setAtual('');
      setNova('');
      setConfirmacao('');
      avisos.sucesso('Senha trocada.');
      atualizarUsuario(resposta.usuario);
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} className="form-coluna">
      <Campo rotulo={rotuloSenhaAtual} para="senha-atual" obrigatorio>
        <CampoSenha
          id="senha-atual"
          autoComplete="current-password"
          required
          value={atual}
          onChange={(e) => setAtual(e.target.value)}
        />
      </Campo>
      <Campo rotulo="Senha nova" para="senha-nova" obrigatorio>
        <CampoSenha
          id="senha-nova"
          autoComplete="new-password"
          required
          value={nova}
          onChange={(e) => setNova(e.target.value)}
        />
      </Campo>
      <Campo rotulo="Repita a senha nova" para="senha-confirmacao" obrigatorio>
        <CampoSenha
          id="senha-confirmacao"
          autoComplete="new-password"
          required
          value={confirmacao}
          onChange={(e) => setConfirmacao(e.target.value)}
        />
      </Campo>
      {erro && (
        <p className="erro-formulario" role="alert">
          {erro}
        </p>
      )}
      <div className="acoes">
        <button type="submit" className="botao botao-primario" disabled={enviando}>
          {enviando ? 'Gravando…' : 'Trocar senha'}
        </button>
      </div>
    </form>
  );
}
