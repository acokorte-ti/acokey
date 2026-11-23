import { Cabecalho, Faixa } from '../componentes/Estados';
import { FormSenha } from '../componentes/FormSenha';
import { dataHoraSistema, resumoDoAcesso, TRACO } from '../lib/formato';
import { useSessao, useUsuario } from '../lib/sessao';

/** Tela obrigatória do primeiro acesso (ou depois de o administrador redefinir a senha). */
export function TrocaObrigatoria() {
  const usuario = useUsuario();
  const { sair } = useSessao();

  return (
    <main className="tela-entrada">
      <div className="cartao-entrada">
        <img className="entrada-logo" src="/logo-acokorte.png" alt="AçoKorte" width={216} height={44} />
        <div>
          <h1>Escolha a sua senha</h1>
          <p className="entrada-sub">AçoKey Q · Controle de lotes — Qualidade</p>
        </div>
        <Faixa tipo="info">
          Olá, {usuario.nome}. A senha que você recebeu é provisória: antes de usar o sistema, troque por uma senha só
          sua.
        </Faixa>
        <FormSenha rotuloSenhaAtual="Senha provisória (a que você acabou de usar)" />
        <button type="button" className="botao botao-fantasma entrada-link" onClick={() => void sair()}>
          Sair
        </button>
      </div>
    </main>
  );
}

export function MinhaConta() {
  const usuario = useUsuario();

  return (
    <>
      <Cabecalho titulo="Minha conta" />
      <div className="grade-conta">
        <section className="cartao" aria-labelledby="titulo-dados">
          <h2 id="titulo-dados">Meus dados</h2>
          <dl className="ficha">
            <div>
              <dt>Nome</dt>
              <dd>{usuario.nome}</dd>
            </div>
            <div>
              <dt>Usuário</dt>
              <dd className="mono">{usuario.login}</dd>
            </div>
            <div>
              <dt>Cargo</dt>
              <dd>{usuario.cargo.trim() || TRACO}</dd>
            </div>
            <div>
              <dt>Acesso</dt>
              <dd>{resumoDoAcesso(usuario)}</dd>
            </div>
            <div>
              <dt>Pode aprovar (assinar relatórios e decidir desvios)</dt>
              <dd>{usuario.pode_aprovar ? 'Sim' : 'Não'}</dd>
            </div>
            <div>
              <dt>Assinatura digital</dt>
              <dd>{usuario.tem_assinatura ? 'Cadastrada' : 'Não cadastrada'}</dd>
            </div>
            <div>
              <dt>Último acesso</dt>
              <dd>{dataHoraSistema(usuario.ultimo_login_em)}</dd>
            </div>
          </dl>
          <p className="dica">Para corrigir o nome, o cargo ou o acesso, fale com o administrador.</p>
        </section>
        <section className="cartao" aria-labelledby="titulo-senha">
          <h2 id="titulo-senha">Trocar senha</h2>
          <FormSenha />
        </section>
      </div>
    </>
  );
}
