/**
 * Início (legado: rota /inicio e TEMPLATES["home"]): um cartão por módulo, só os que o usuário pode abrir,
 * com os números de hoje. No primeiro acesso, o convite "Quer uma visita guiada?".
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga } from '../../componentes/Estados';
import { Icone } from '../../componentes/Layout';
import { api, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { useCarga } from '../../lib/useCarga';
import type { CartaoInicio, RespostaInicio } from '../paineis/tipos';
import './inicio.css';

const ICONE: Record<CartaoInicio['chave'], Parameters<typeof Icone>[0]['nome']> = {
  producao: 'fabrica',
  qualidade: 'auditoria',
  tt: 'forno',
  equipamentos: 'equipamento',
  cadastros: 'engrenagem',
};

/**
 * Evento que abre a visita guiada da tela. Quem implementar a visita escuta este evento e chama
 * `preventDefault()`; enquanto ninguém escutar, a tela avisa que a visita ainda não está pronta.
 */
export const EVENTO_VISITA_GUIADA = 'acokey:visita-guiada';

function ConviteVisita({ nome, aoResponder }: { nome: string; aoResponder: () => void }) {
  const avisos = useAvisos();
  const [enviando, setEnviando] = useState(false);

  async function responder(querVisita: boolean) {
    setEnviando(true);
    try {
      await api('/inicio/tutorial-visto', { metodo: 'POST' });
      aoResponder();
      if (querVisita) {
        const tratado = !window.dispatchEvent(new CustomEvent(EVENTO_VISITA_GUIADA, { cancelable: true, detail: { tela: 'inicio' } }));
        if (!tratado) avisos.info('A visita guiada ainda está sendo preparada. Quando estiver pronta, ela aparece nesta tela.');
      }
    } catch (erro) {
      avisos.erro(mensagemDeErro(erro));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="inicio-convite" aria-labelledby="inicio-convite-titulo">
      <div>
        <strong id="inicio-convite-titulo">Bem-vindo(a) ao sistema, {nome}!</strong>
        <p>Quer uma visita guiada rápida por esta tela?</p>
      </div>
      <div className="inicio-convite-acoes">
        <button type="button" className="botao botao-primario" onClick={() => void responder(true)} disabled={enviando}>
          Sim, mostrar
        </button>
        <button type="button" className="botao" onClick={() => void responder(false)} disabled={enviando}>
          Agora não
        </button>
      </div>
    </section>
  );
}

export function Inicio() {
  const carga = useCarga<RespostaInicio>((sinal) => api('/inicio', { sinal }), []);
  const dados = carga.dados;

  return (
    <>
      <Cabecalho titulo="Início" apoio={dados ? `Olá, ${dados.nome}. Escolha um módulo para entrar.` : 'Escolha um módulo para entrar.'} />

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
      {!dados && carga.carregando && <Carregando />}

      {dados && (
        <>
          {dados.mostrar_tutorial && <ConviteVisita nome={dados.nome} aoResponder={() => carga.definir({ ...dados, mostrar_tutorial: false })} />}

          <ul className="inicio-cartoes" aria-label="Módulos">
            {dados.cartoes.map((c) => (
              <li key={c.chave}>
                <Link to={c.link} className={`inicio-cartao inicio-${c.chave} ${c.alerta ? 'inicio-cartao-alerta' : ''}`}>
                  {c.alerta && <span className="selo selo-alerta inicio-flag">Atenção</span>}
                  <span className="inicio-icone" aria-hidden="true">
                    <Icone nome={ICONE[c.chave]} />
                  </span>
                  <span className="inicio-nome">{c.nome}</span>
                  <span className="inicio-texto">{c.texto}</span>
                </Link>
              </li>
            ))}
          </ul>

          <p className="inicio-dica">
            <strong>Dica:</strong> o menu ao lado continua com todas as telas; aqui é um atalho por módulo, com os números de agora. Para achar um
            lote, use <kbd>Ctrl</kbd> + <kbd>K</kbd> em qualquer tela.
          </p>
        </>
      )}
    </>
  );
}
