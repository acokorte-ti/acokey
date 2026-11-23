import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { Cabecalho, Carregando, Vazio } from './componentes/Estados';
import { Layout } from './componentes/Layout';
import { useSessao } from './lib/sessao';
import { Auditoria } from './paginas/Auditoria';
import { MinhaConta, TrocaObrigatoria } from './paginas/Conta';
import { Login } from './paginas/Login';
import { Lote } from './paginas/Lote';
import { Painel } from './paginas/Painel';
import { Usuarios } from './paginas/Usuarios';

/** Se uma tela quebrar, mostra uma mensagem em vez de deixar a página em branco. */
class LimiteDeErro extends Component<{ children: ReactNode }, { quebrou: boolean }> {
  state = { quebrou: false };

  static getDerivedStateFromError(): { quebrou: boolean } {
    return { quebrou: true };
  }

  componentDidCatch(erro: Error, info: ErrorInfo): void {
    console.error('Erro na tela:', erro, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.quebrou) return this.props.children;
    return (
      <div className="estado estado-erro" role="alert">
        <strong>Esta tela encontrou um erro inesperado.</strong>
        <span>Recarregue a página. Se continuar, avise o administrador do sistema.</span>
        <button type="button" className="botao" onClick={() => window.location.reload()}>
          Recarregar
        </button>
      </div>
    );
  }
}

function SemAcesso() {
  return (
    <>
      <Cabecalho titulo="Sem acesso" />
      <Vazio titulo="Seu usuário não tem permissão para abrir esta tela.">
        <Link to="/">Voltar para o início</Link>
      </Vazio>
    </>
  );
}

function NaoEncontrada() {
  return (
    <>
      <Cabecalho titulo="Página não encontrada" />
      <Vazio titulo="Este endereço não existe no sistema.">
        <Link to="/">Voltar para o início</Link>
      </Vazio>
    </>
  );
}

/** Esconde a tela de quem não tem a permissão (o backend recusa de qualquer forma). */
function Restrito({ permitido, children }: { permitido: boolean; children: ReactNode }) {
  return permitido ? <>{children}</> : <SemAcesso />;
}

export function App() {
  const { carregando, usuario, pode } = useSessao();

  if (carregando) {
    return (
      <div className="tela-entrada">
        <Carregando texto="Abrindo o sistema…" />
      </div>
    );
  }
  if (!usuario) return <Login />;
  // Senha provisória: nada funciona antes de trocar (o backend responde 403 TROCAR_SENHA)
  if (usuario.trocar_senha) return <TrocaObrigatoria />;

  return (
    <Layout>
      <LimiteDeErro>
        <Routes>
          <Route path="/" element={<Painel />} />
          <Route path="/lotes/:id" element={<Lote />} />
          <Route
            path="/auditoria"
            element={
              <Restrito permitido={pode.auditoria}>
                <Auditoria />
              </Restrito>
            }
          />
          <Route
            path="/usuarios"
            element={
              <Restrito permitido={pode.admin}>
                <Usuarios />
              </Restrito>
            }
          />
          <Route path="/conta" element={<MinhaConta />} />
          <Route path="*" element={<NaoEncontrada />} />
        </Routes>
      </LimiteDeErro>
    </Layout>
  );
}
