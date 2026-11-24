import { Component, lazy, Suspense, type ComponentType, type ErrorInfo, type ReactNode } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { Cabecalho, Carregando, Vazio } from './componentes/Estados';
import { Layout } from './componentes/Layout';
import { useSessao } from './lib/sessao';
import { MinhaConta, TrocaObrigatoria } from './paginas/Conta';
import { Login } from './paginas/Login';
import { Painel } from './paginas/Painel';

/** Cada módulo só é baixado quando alguém abre a tela dele (o site abre mais rápido nos PCs da fábrica). */
function sobDemanda<M extends Record<string, unknown>>(carregar: () => Promise<M>, nome: keyof M) {
  return lazy(async () => ({ default: (await carregar())[nome] as ComponentType }));
}
const Auditoria = sobDemanda(() => import('./paginas/Auditoria'), 'Auditoria');
const Equipamentos = sobDemanda(() => import('./paginas/cadastros'), 'Equipamentos');
const FornecedoresMP = sobDemanda(() => import('./paginas/cadastros'), 'FornecedoresMP');
const OrdensProducao = sobDemanda(() => import('./paginas/cadastros'), 'OrdensProducao');
const Parametros = sobDemanda(() => import('./paginas/cadastros'), 'Parametros');
const Prestadores = sobDemanda(() => import('./paginas/cadastros'), 'Prestadores');
const ModuloCargasTT = sobDemanda(() => import('./paginas/cargas-tt'), 'ModuloCargasTT');
const ModuloDatabooks = sobDemanda(() => import('./paginas/databooks'), 'ModuloDatabooks');
const VerificarDimensional = sobDemanda(() => import('./paginas/dimensional'), 'VerificarDimensional');
const ModuloEnvios = sobDemanda(() => import('./paginas/envios'), 'ModuloEnvios');
const Especificacoes = sobDemanda(() => import('./paginas/especificacoes'), 'Especificacoes');
const ModuloFaturamento = sobDemanda(() => import('./paginas/faturamento'), 'ModuloFaturamento');
const Inicio = sobDemanda(() => import('./paginas/inicio'), 'Inicio');
const ModuloLote = sobDemanda(() => import('./paginas/lotes'), 'ModuloLote');
const ModuloMateriaPrima = sobDemanda(() => import('./paginas/materia-prima'), 'ModuloMateriaPrima');
const ModuloNC = sobDemanda(() => import('./paginas/nc'), 'ModuloNC');
const Dashboard = sobDemanda(() => import('./paginas/paineis'), 'Dashboard');
const Gantt = sobDemanda(() => import('./paginas/paineis'), 'Gantt');
const Indicadores = sobDemanda(() => import('./paginas/paineis'), 'Indicadores');
const Kpis = sobDemanda(() => import('./paginas/paineis'), 'Kpis');
const ModuloRelatorios = sobDemanda(() => import('./paginas/relatorios'), 'ModuloRelatorios');
const Usuarios = sobDemanda(() => import('./paginas/Usuarios'), 'Usuarios');

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
        {/*
          Cada módulo é dono das suas sub-rotas (ex.: /envios/* → ModuloEnvios define /envios, /envios/novo,
          /envios/:id). As permissões seguem o menu do sistema antigo; o backend confere de novo em cada chamada.
        */}
        <Suspense fallback={<Carregando />}>
        <Routes>
          {/* Produção */}
          <Route path="/" element={<Painel />} />
          <Route path="/inicio" element={<Inicio />} />
          <Route path="/lotes/:id/*" element={<ModuloLote />} />
          <Route path="/relatorios/*" element={<ModuloRelatorios />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/gantt" element={<Gantt />} />
          <Route path="/cargas-tt/*" element={<Restrito permitido={pode.tt}><ModuloCargasTT /></Restrito>} />
          <Route path="/envios/*" element={<Restrito permitido={pode.expedicao}><ModuloEnvios /></Restrito>} />
          <Route path="/faturamento/*" element={<Restrito permitido={pode.expedicao}><ModuloFaturamento /></Restrito>} />
          <Route path="/kpis" element={<Restrito permitido={pode.kpis}><Kpis /></Restrito>} />
          {/* Qualidade */}
          <Route path="/materia-prima/*" element={<Restrito permitido={pode.qualidade}><ModuloMateriaPrima /></Restrito>} />
          <Route path="/nao-conformidades/*" element={<Restrito permitido={pode.qualidade}><ModuloNC /></Restrito>} />
          <Route path="/indicadores" element={<Restrito permitido={pode.qualidade}><Indicadores /></Restrito>} />
          <Route path="/verificar-dimensional" element={<Restrito permitido={pode.qualidade}><VerificarDimensional /></Restrito>} />
          <Route path="/equipamentos" element={<Restrito permitido={pode.equipamentos}><Equipamentos /></Restrito>} />
          <Route path="/databooks/*" element={<Restrito permitido={pode.qualidade}><ModuloDatabooks /></Restrito>} />
          <Route path="/auditoria" element={<Restrito permitido={pode.auditoria}><Auditoria /></Restrito>} />
          {/* Cadastros */}
          <Route path="/especificacoes" element={<Restrito permitido={pode.cadastros || pode.qualidade}><Especificacoes /></Restrito>} />
          <Route path="/ordens-producao" element={<Restrito permitido={pode.cadastros}><OrdensProducao /></Restrito>} />
          <Route path="/fornecedores-mp" element={<Restrito permitido={pode.cadastros}><FornecedoresMP /></Restrito>} />
          <Route path="/prestadores" element={<Restrito permitido={pode.cadastros}><Prestadores /></Restrito>} />
          {/* Administração */}
          <Route path="/parametros" element={<Restrito permitido={pode.admin}><Parametros /></Restrito>} />
          <Route path="/usuarios" element={<Restrito permitido={pode.admin}><Usuarios /></Restrito>} />
          <Route path="/conta" element={<MinhaConta />} />
          <Route path="*" element={<NaoEncontrada />} />
        </Routes>
        </Suspense>
      </LimiteDeErro>
    </Layout>
  );
}
