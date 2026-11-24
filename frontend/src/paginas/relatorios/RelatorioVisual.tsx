import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, Faixa } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api, enviarArquivos, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useCarga } from '../../lib/useCarga';
import { ErroRelatorio, escolhaInicial, Resumo, SeletorPessoa, SlotImagem } from './Comuns';
import type { RespostaRelatorio, TelaVisual } from './tipos';

const USAR_COMO_ESTA = 'USAR COMO ESTÁ (RNC)';
const CAMPO_LASER = /\{(\w+)(?::0?(\d+)d)?\}/g;
const LOTE_COMPLETO = /^\d{2}-\d-\d+$/;

/** Mesmo formato do servidor (parâmetro laser_formato): troca {ano}, {tri}, {corrida}, {lote} e {seq:03d}. */
export function formatarLaser(formato: string, valores: Record<string, string | number>): string {
  return formato.replace(CAMPO_LASER, (inteiro, nome: string, largura?: string) => {
    if (!(nome in valores)) return inteiro;
    const texto = String(valores[nome]);
    return largura ? texto.padStart(Number(largura), '0') : texto;
  });
}

/** Lote no formato completo (AA-T-NNNNN): o número já completo fica como está; senão monta com ano e trimestre. */
function loteCompleto(numero: string, ano: string, tri: string): string {
  return LOTE_COMPLETO.test(numero) ? numero : `${ano.slice(-2)}-${tri}-${numero}`;
}

type Fotos = { geral: File | null; peca: File | null; laser: File | null };

export function RelatorioVisual({ loteId }: { loteId: number }) {
  const navegar = useNavigate();
  const avisos = useAvisos();
  const tela = useCarga<TelaVisual>((sinal) => api(`/relatorios/visual/${loteId}`, { sinal }), [loteId]);
  const dados = tela.dados;

  const [resultado, setResultado] = useState('APROVADO');
  const [qtd, setQtd] = useState('');
  const [rnc, setRnc] = useState('N/A');
  const [obs, setObs] = useState(['', '', '']);
  const [fotos, setFotos] = useState<Fotos>({ geral: null, peca: null, laser: null });
  const [ano, setAno] = useState('');
  const [tri, setTri] = useState('');
  const [executor, setExecutor] = useState<number | ''>('');
  const [aprovador, setAprovador] = useState<number | ''>('');
  const [data, setData] = useState('');
  const [dataAprovacao, setDataAprovacao] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (!dados) return;
    setResultado('APROVADO');
    setQtd(String(dados.lote.qtd || ''));
    setRnc('N/A');
    setObs([dados.info.obs1, dados.info.obs2, dados.info.obs3]);
    setAno(String(dados.ano));
    setTri(String(dados.tri));
    setExecutor(escolhaInicial(dados.executores, dados.usuario_id));
    setAprovador(escolhaInicial(dados.aprovadores, dados.usuario_id));
    setData(dados.hoje);
    setDataAprovacao(dados.hoje);
    setErro(null);
  }, [dados]);

  const previa = useMemo(() => {
    if (!dados) return null;
    const quantidade = Number.parseInt(qtd, 10);
    if (!ano.trim() || !tri.trim() || !Number.isFinite(quantidade) || quantidade < 1) return null;
    const base = { ano: ano.trim(), tri: tri.trim(), corrida: dados.laser.corrida, lote: dados.laser.lote };
    return {
      primeiro: formatarLaser(dados.laser.formato, { ...base, seq: 1 }),
      ultimo: formatarLaser(dados.laser.formato, { ...base, seq: quantidade }),
      quantidade,
    };
  }, [dados, ano, tri, qtd]);

  if (tela.erro) {
    return (
      <>
        <Cabecalho titulo="Relatório de Inspeção Visual e Marcação a Laser" />
        <ErroRelatorio mensagem={tela.erro} loteId={loteId} />
      </>
    );
  }
  if (!dados) return <Carregando />;
  const { lote, info } = dados;
  const loteMostrado = ano.trim() && tri.trim() ? loteCompleto(lote.numero, ano.trim(), tri.trim()) : lote.numero;
  const usarComoEsta = resultado === USAR_COMO_ESTA;

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    if (!previa) {
      setErro('Informe a quantidade inspecionada, o ano e o trimestre do código a laser.');
      return;
    }
    if (usarComoEsta && ['', 'N/A', 'NA', '-'].includes(rnc.trim().toUpperCase())) {
      setErro('Para “Usar como está”, informe o número da RNC (não conformidade) que autoriza.');
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await enviarArquivos<RespostaRelatorio>(`/relatorios/visual/${lote.id}`, {
        resultado,
        qtd,
        rnc,
        obs1: obs[0],
        obs2: obs[1],
        obs3: obs[2],
        ano,
        tri,
        executado_por: executor,
        aprovado_por: aprovador,
        data,
        data_aprovacao: dataAprovacao,
        foto_geral: fotos.geral,
        foto_peca: fotos.peca,
        foto_laser: fotos.laser,
      });
      if (resposta.status === 'REPROVADO') avisos.info(resposta.mensagem);
      else avisos.sucesso(resposta.mensagem);
      navegar(`/lotes/${lote.id}`);
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setEnviando(false);
    }
  }

  return (
    <>
      <Cabecalho
        titulo="Relatório de Inspeção Visual e Marcação a Laser"
        apoio={
          <>
            <Link to={`/lotes/${lote.id}`}>Lote {lote.numero}</Link> · As 3 observações padrão já vêm preenchidas conforme o tipo da
            peça ({lote.tipo}); edite se precisar.
          </>
        }
      />
      <div className="pilha rel-pagina">
        <Resumo
          itens={[
            ['Cliente', info.cliente],
            ['Designação', info.nome_peca],
            ['OP', <span className="mono">{lote.op}</span>],
            ['Lote', <span className="mono">{loteMostrado}</span>],
            ['Tipo', <SeloTipo tipo={lote.tipo} />],
            ['Cód. item', <span className="mono">{lote.coditem}</span>],
            ['Desenho / revisão', info.desenho],
            ['Padrão de aceitação', info.padrao_aceitacao],
          ]}
        />

        <form className="pilha" onSubmit={enviar} onKeyDown={enterVaiParaProximo} noValidate>
          <section className="cartao" aria-labelledby="titulo-status-visual">
            <h2 id="titulo-status-visual">Status da inspeção</h2>
            <div className="form-grade">
              <Campo rotulo="Resultado" para="vis-resultado" classe="col-2" obrigatorio>
                <select
                  id="vis-resultado"
                  className={`rel-resultado rel-resultado-${resultado === 'APROVADO' ? 'ok' : resultado === 'REPROVADO' ? 'erro' : 'alerta'}`}
                  value={resultado}
                  onChange={(e) => setResultado(e.target.value)}
                >
                  {dados.resultados.map((r) => (
                    <option key={r} value={r} disabled={r === USAR_COMO_ESTA && !dados.pode_usar_como_esta}>
                      {r}
                      {r === USAR_COMO_ESTA && !dados.pode_usar_como_esta ? ' — só quem pode aprovar' : ''}
                    </option>
                  ))}
                </select>
              </Campo>
              <Campo rotulo="Quantidade inspecionada" para="vis-qtd" classe="col-1" obrigatorio>
                <input
                  id="vis-qtd"
                  type="text"
                  inputMode="numeric"
                  className="rel-numero-grande"
                  value={qtd}
                  maxLength={6}
                  onChange={(e) => setQtd(e.target.value.replace(/\D/g, ''))}
                />
              </Campo>
              <Campo
                rotulo="RNC nº (se aplicável)"
                para="vis-rnc"
                classe="col-1"
                obrigatorio={usarComoEsta}
                dica={usarComoEsta ? 'A não conformidade aberta desta etapa é encerrada como “uso como está”.' : undefined}
              >
                <input id="vis-rnc" type="text" value={rnc} maxLength={60} onChange={(e) => setRnc(e.target.value)} />
              </Campo>
            </div>
            {resultado === 'REPROVADO' && (
              <Faixa tipo="alerta">Reprovado: ao salvar, o sistema abre uma não conformidade para esta etapa.</Faixa>
            )}
          </section>

          <section className="cartao" aria-labelledby="titulo-obs-visual">
            <h2 id="titulo-obs-visual">Observações</h2>
            <p className="dica">As 3 linhas padrão já vêm sugeridas; edite se necessário.</p>
            {obs.map((texto, i) => (
              <Campo key={i} rotulo={`Observação ${i + 1}`} para={`vis-obs-${i + 1}`}>
                <input
                  id={`vis-obs-${i + 1}`}
                  type="text"
                  value={texto}
                  maxLength={400}
                  onChange={(e) => setObs((atual) => atual.map((o, j) => (j === i ? e.target.value : o)))}
                />
              </Campo>
            ))}
          </section>

          <section className="cartao" aria-labelledby="titulo-fotos">
            <h2 id="titulo-fotos">Fotos (3 imagens para o PDF)</h2>
            <p className="dica">
              Clique na caixa e cole (Ctrl+V) um recorte, ou dê duplo clique para escolher o arquivo. Foto que não for enviada aparece no
              PDF como “imagem a anexar”.
            </p>
            <div className="rel-slots">
              <SlotImagem rotulo="Foto geral (lote embalado)" campo="foto_geral" arquivo={fotos.geral} aoMudar={(f) => setFotos((x) => ({ ...x, geral: f }))} />
              <SlotImagem rotulo="Foto da peça (detalhe)" campo="foto_peca" arquivo={fotos.peca} aoMudar={(f) => setFotos((x) => ({ ...x, peca: f }))} />
              <SlotImagem rotulo="Foto da gravação laser" campo="foto_laser" arquivo={fotos.laser} aoMudar={(f) => setFotos((x) => ({ ...x, laser: f }))} />
            </div>
          </section>

          <section className="cartao" aria-labelledby="titulo-laser">
            <h2 id="titulo-laser">Código de rastreabilidade a laser</h2>
            <div className="linha-campos">
              <Campo rotulo="Ano" para="vis-ano">
                <input id="vis-ano" type="text" inputMode="numeric" value={ano} maxLength={4} onChange={(e) => setAno(e.target.value.replace(/\D/g, ''))} />
              </Campo>
              <Campo rotulo="Trimestre" para="vis-tri" dica="1 a 4">
                <input id="vis-tri" type="text" inputMode="numeric" value={tri} maxLength={1} onChange={(e) => setTri(e.target.value.replace(/[^1-4]/g, ''))} />
              </Campo>
            </div>
            <div className="rel-laser" aria-live="polite">
              {previa ? (
                <>
                  <span className="mono">
                    {previa.primeiro} → {previa.ultimo}
                  </span>
                  <span className="sub-linha">
                    ({previa.quantidade} {previa.quantidade === 1 ? 'código' : 'códigos sequenciais'})
                  </span>
                </>
              ) : (
                <span className="sub-linha">Preencha a quantidade, o ano e o trimestre para ver os códigos.</span>
              )}
            </div>
          </section>

          <section className="cartao" aria-labelledby="titulo-resp-visual">
            <h2 id="titulo-resp-visual">Responsáveis e datas</h2>
            {dados.aprovadores.length === 0 && (
              <Faixa tipo="erro">Nenhum usuário ativo tem “pode aprovar”. Peça ao administrador para marcar quem aprova pela Qualidade.</Faixa>
            )}
            <div className="linha-campos">
              <SeletorPessoa
                id="vis-executor"
                rotulo="Executado por — Controle de Qualidade"
                lista={dados.executores}
                valor={executor}
                aoMudar={setExecutor}
              />
              <SeletorPessoa
                id="vis-aprovador"
                rotulo="Aprovado por — Gerente da Qualidade"
                lista={dados.aprovadores}
                valor={aprovador}
                aoMudar={setAprovador}
              />
              <Campo rotulo="Data do ensaio" para="vis-data" dica="Usada como data de emissão do laudo.">
                <input id="vis-data" type="date" value={data} onChange={(e) => setData(e.target.value)} />
              </Campo>
              <Campo rotulo="Data de aprovação" para="vis-data-aprovacao">
                <input id="vis-data-aprovacao" type="date" value={dataAprovacao} onChange={(e) => setDataAprovacao(e.target.value)} />
              </Campo>
            </div>
          </section>

          <section className="cartao acoes-form rel-rodape">
            {erro && (
              <p className="erro-formulario" role="alert">
                {erro}
              </p>
            )}
            <div className="acoes">
              <button type="submit" className="botao botao-primario" disabled={enviando || dados.aprovadores.length === 0}>
                {enviando ? 'Gerando o PDF…' : 'Salvar e gerar PDF'}
              </button>
              <Link to={`/lotes/${lote.id}`} className="botao">
                Cancelar
              </Link>
              <span className="dica">PDF anexado na etapa Visual / Laser. Aprovado (ou “usar como está”), a etapa é concluída.</span>
            </div>
          </section>
        </form>
      </div>
    </>
  );
}
