/* Especificações: limites por tipo (dureza, tração, Charpy) e cotas dimensionais por item/desenho. */
import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { Confirmacao } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, enderecoApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { inteiro, TRACO } from '../../lib/formato';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useAtrasado, useCarga } from '../../lib/useCarga';
import type {
  CampoEspecificacao,
  Cota,
  CotasDoItem,
  EspecificacaoTipo,
  RespostaCotas,
  RespostaTipo,
  TelaEspecificacoes,
} from './tipos';
import './especificacoes.css';

interface DefCampo {
  campo: CampoEspecificacao;
  rotulo: string;
  numerico: boolean;
  dica?: string;
}

const GRUPOS: { titulo: string; campos: DefCampo[] }[] = [
  {
    titulo: 'Dureza (HRC)',
    campos: [
      { campo: 'dureza_min', rotulo: 'Mínima', numerico: true },
      { campo: 'dureza_max', rotulo: 'Máxima', numerico: true },
    ],
  },
  {
    titulo: 'Tração',
    campos: [
      { campo: 'tr_le_min', rotulo: 'LE mín. (MPa)', numerico: true },
      { campo: 'tr_le_max', rotulo: 'LE máx. (MPa)', numerico: true },
      { campo: 'tr_lr_min', rotulo: 'LR mín. (MPa)', numerico: true },
      { campo: 'tr_lr_max', rotulo: 'LR máx. (MPa)', numerico: true },
      { campo: 'tr_al_min', rotulo: 'Along. mín. (%)', numerico: true },
      { campo: 'tr_ra_min', rotulo: 'RA mín. (%)', numerico: true },
    ],
  },
  {
    titulo: 'Charpy',
    campos: [
      { campo: 'ch_temp', rotulo: 'Temperatura de ensaio (°C)', numerico: false, dica: 'Texto: ex. -20 ou Ambiente' },
      { campo: 'ch_dim_cp', rotulo: 'Corpo de prova', numerico: false },
      { campo: 'ch_med_min', rotulo: 'Energia média mín. (J)', numerico: true },
      { campo: 'ch_ind_min', rotulo: 'Energia individual mín. (J)', numerico: true },
    ],
  },
];
const CAMPOS = GRUPOS.flatMap((g) => g.campos);
const NUMERO = /^-?\d{1,6}([.,]\d{1,2})?$/;
const LINHAS_EM_BRANCO = 4;

/** "39.5" -> "39,5" (o servidor manda com ponto). */
function comVirgula(texto: string): string {
  return texto.replace('.', ',');
}

function numeroInvalido(texto: string): boolean {
  const limpo = texto.trim();
  return limpo !== '' && !NUMERO.test(limpo);
}

function resumoDureza(spec: EspecificacaoTipo): string {
  if (!spec.cadastrada) return 'não cadastrada';
  if (spec.dureza_min || spec.dureza_max) return `dureza ${comVirgula(spec.dureza_min) || TRACO} a ${comVirgula(spec.dureza_max) || TRACO} HRc`;
  return 'sem dureza cadastrada';
}

// ---------------------------------------------------------------- limites por tipo

function valoresDoForm(spec: EspecificacaoTipo): Record<CampoEspecificacao, string> {
  return Object.fromEntries(CAMPOS.map((c) => [c.campo, c.numerico ? comVirgula(spec[c.campo]) : spec[c.campo]])) as Record<
    CampoEspecificacao,
    string
  >;
}

function FormTipo({ spec, podeEditar, aoSalvar }: { spec: EspecificacaoTipo; podeEditar: boolean; aoSalvar: (s: EspecificacaoTipo) => void }) {
  const avisos = useAvisos();
  const [valores, setValores] = useState(() => valoresDoForm(spec));
  const [original, setOriginal] = useState(() => valoresDoForm(spec));
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const mudou = CAMPOS.some((c) => valores[c.campo] !== original[c.campo]);
  const invalidos = CAMPOS.filter((c) => c.numerico && numeroInvalido(valores[c.campo]));

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    if (invalidos.length > 0) {
      setErro(`${invalidos.map((c) => c.rotulo).join(', ')}: use um número com até 2 casas decimais (ex.: 30 ou 30,5).`);
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await api<RespostaTipo>(`/especificacoes/tipos/${spec.tipo}`, { metodo: 'PUT', corpo: valores });
      const novos = valoresDoForm(resposta.tipo);
      setValores(novos);
      setOriginal(novos);
      aoSalvar(resposta.tipo);
      avisos.sucesso(resposta.mensagem);
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={salvar} onKeyDown={enterVaiParaProximo} className="form-coluna" noValidate>
      {GRUPOS.map((grupo) => (
        <fieldset key={grupo.titulo} className="esp-grupo">
          <legend>{grupo.titulo}</legend>
          <div className="form-grade">
            {grupo.campos.map((c) => {
              const id = `esp-${spec.tipo}-${c.campo}`;
              const invalido = c.numerico && numeroInvalido(valores[c.campo]);
              return (
                <div key={c.campo} className="campo">
                  <label htmlFor={id}>{c.rotulo}</label>
                  <input
                    id={id}
                    type="text"
                    inputMode={c.numerico ? 'decimal' : undefined}
                    className={invalido ? 'esp-invalido' : undefined}
                    aria-invalid={invalido || undefined}
                    maxLength={c.numerico ? 20 : 40}
                    value={valores[c.campo]}
                    disabled={!podeEditar}
                    onChange={(e) => setValores((atual) => ({ ...atual, [c.campo]: e.target.value }))}
                  />
                  {c.dica && <span className="dica">{c.dica}</span>}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}
      {erro && (
        <p className="erro-formulario" role="alert">
          {erro}
        </p>
      )}
      {podeEditar && (
        <div className="acoes acoes-form">
          <button type="submit" className="botao botao-primario" disabled={enviando || !mudou}>
            {enviando ? 'Gravando…' : `Salvar especificações de ${spec.tipo}`}
          </button>
          {mudou && (
            <button type="button" className="botao botao-fantasma" onClick={() => setValores(original)} disabled={enviando}>
              Desfazer alterações
            </button>
          )}
          {mudou && <span className="texto-alerta">Alterações ainda não salvas.</span>}
        </div>
      )}
    </form>
  );
}

// ---------------------------------------------------------------- cotas por item

function linhasIniciais(cotas: Cota[]): Cota[] {
  if (cotas.length > 0) return cotas.map((c) => ({ descricao: c.descricao, nominal: c.nominal, tol_min: c.tol_min, tol_max: c.tol_max }));
  return Array.from({ length: LINHAS_EM_BRANCO }, () => ({ descricao: '', nominal: '', tol_min: '', tol_max: '' }));
}

function iguais(a: Cota[], b: Cota[]): boolean {
  const limpar = (lista: Cota[]) =>
    JSON.stringify(
      lista
        .map((c) => [c.descricao.trim(), c.nominal.trim(), c.tol_min.trim(), c.tol_max.trim()])
        .filter((c) => c.some((v) => v !== '')),
    );
  return limpar(a) === limpar(b);
}

interface PropsEditor {
  item: CotasDoItem;
  podeEditar: boolean;
  aoSalvar: () => void;
}

function EditorCotas({ item, podeEditar, aoSalvar }: PropsEditor) {
  const avisos = useAvisos();
  const [linhas, setLinhas] = useState<Cota[]>(() => linhasIniciais(item.cotas));
  const [salvas, setSalvas] = useState<Cota[]>(item.cotas);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [confirmarLimpar, setConfirmarLimpar] = useState(false);
  const mudou = !iguais(linhas, salvas);

  function mudar(i: number, campo: keyof Cota, valor: string) {
    setLinhas((atual) => atual.map((l, k) => (k === i ? { ...l, [campo]: valor } : l)));
  }

  async function gravar(lista: Cota[]) {
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await api<RespostaCotas>('/especificacoes/cotas', {
        metodo: 'PUT',
        corpo: { coditem: item.coditem, cotas: lista.map(({ descricao, nominal, tol_min, tol_max }) => ({ descricao, nominal, tol_min, tol_max })) },
      });
      setSalvas(resposta.cotas);
      setLinhas(linhasIniciais(resposta.cotas));
      avisos.sucesso(resposta.mensagem);
      aoSalvar();
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
      setConfirmarLimpar(false);
    }
  }

  function salvar(evento: FormEvent) {
    evento.preventDefault();
    const semDescricao = linhas.findIndex((l) => !l.descricao.trim() && (l.nominal.trim() || l.tol_min.trim() || l.tol_max.trim()));
    if (semDescricao >= 0) {
      setErro(`A cota da linha ${semDescricao + 1} está sem descrição: preencha a descrição ou limpe a linha.`);
      return;
    }
    void gravar(linhas);
  }

  return (
    <form onSubmit={salvar} onKeyDown={enterVaiParaProximo} className="form-coluna" noValidate>
      <p className="dica">
        {item.desenho ? (
          <>
            Desenho: {item.desenho.classificacao && <SeloTipo tipo={item.desenho.classificacao} />} {item.desenho.descricao}
          </>
        ) : (
          'Não há desenho com este código na pasta de desenhos.'
        )}
        {' · '}
        {salvas.length > 0 ? `${inteiro(salvas.length)} cota(s) cadastrada(s).` : 'Nenhuma cota cadastrada para este item.'}
      </p>
      <div className="tabela-rolagem">
        <table className="tabela esp-cotas">
          <caption className="so-leitor">Cotas do item {item.coditem}</caption>
          <thead>
            <tr>
              <th scope="col">Cota</th>
              <th scope="col">Nominal</th>
              <th scope="col">Tol. inferior</th>
              <th scope="col">Tol. superior</th>
              {podeEditar && (
                <th scope="col">
                  <span className="so-leitor">Ações</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {linhas.map((linha, i) => (
              <tr key={i}>
                <td>
                  <input
                    type="text"
                    aria-label={`Cota, linha ${i + 1}`}
                    placeholder={i === 0 ? 'Ex.: Diâmetro externo' : undefined}
                    maxLength={200}
                    value={linha.descricao}
                    disabled={!podeEditar}
                    onChange={(e) => mudar(i, 'descricao', e.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    inputMode="decimal"
                    aria-label={`Nominal, linha ${i + 1}`}
                    maxLength={40}
                    value={linha.nominal}
                    disabled={!podeEditar}
                    onChange={(e) => mudar(i, 'nominal', e.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    inputMode="decimal"
                    aria-label={`Tolerância inferior, linha ${i + 1}`}
                    placeholder={i === 0 ? '-0,05' : undefined}
                    maxLength={40}
                    value={linha.tol_min}
                    disabled={!podeEditar}
                    onChange={(e) => mudar(i, 'tol_min', e.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    inputMode="decimal"
                    aria-label={`Tolerância superior, linha ${i + 1}`}
                    placeholder={i === 0 ? '+0,05' : undefined}
                    maxLength={40}
                    value={linha.tol_max}
                    disabled={!podeEditar}
                    onChange={(e) => mudar(i, 'tol_max', e.target.value)}
                  />
                </td>
                {podeEditar && (
                  <td className="esp-acao-linha">
                    <button
                      type="button"
                      className="botao botao-fantasma botao-pequeno"
                      onClick={() => setLinhas((atual) => atual.filter((_, k) => k !== i))}
                      aria-label={`Tirar a linha ${i + 1}`}
                    >
                      Tirar
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {erro && (
        <p className="erro-formulario" role="alert">
          {erro}
        </p>
      )}
      {podeEditar && (
        <div className="acoes acoes-form">
          <button
            type="button"
            className="botao"
            onClick={() => setLinhas((atual) => [...atual, { descricao: '', nominal: '', tol_min: '', tol_max: '' }])}
          >
            + Cota
          </button>
          <button type="submit" className="botao botao-primario" disabled={enviando || !mudou}>
            {enviando ? 'Gravando…' : 'Salvar cotas deste item'}
          </button>
          {salvas.length > 0 && (
            <button type="button" className="botao botao-perigo-contorno" onClick={() => setConfirmarLimpar(true)} disabled={enviando}>
              Tirar todas as cotas deste item
            </button>
          )}
          {mudou && <span className="texto-alerta">Alterações ainda não salvas.</span>}
        </div>
      )}
      {confirmarLimpar && (
        <Confirmacao
          titulo={`Tirar as cotas do item ${item.coditem}`}
          rotuloConfirmar="Tirar todas as cotas"
          aoConfirmar={() => void gravar([])}
          aoFechar={() => setConfirmarLimpar(false)}
          enviando={enviando}
          perigo
        >
          <p>
            O item {item.coditem} vai ficar sem cotas cadastradas ({inteiro(salvas.length)} hoje). A inspeção dimensional dele volta a usar
            campos livres. A lista atual fica guardada na auditoria.
          </p>
        </Confirmacao>
      )}
    </form>
  );
}

interface PropsSecaoCotas {
  tela: TelaEspecificacoes;
  podeEditar: boolean;
  aoMudar: () => void;
  abrirItem: (coditem: string) => void;
}

function SecaoCotas({ tela, podeEditar, aoMudar, abrirItem }: PropsSecaoCotas) {
  const [parametros, setParametros] = useSearchParams();
  const [digitado, setDigitado] = useState(() => parametros.get('coditem') ?? '');
  const coditem = useAtrasado(digitado.trim(), 400);
  const [versao, setVersao] = useState(0);
  const carga = useCarga<CotasDoItem | null>(
    (sinal) => (coditem ? api<CotasDoItem>(`/especificacoes/cotas/${encodeURIComponent(coditem)}`, { sinal }) : Promise.resolve(null)),
    [coditem, versao],
  );
  const item = carga.dados && carga.dados.coditem === coditem ? carga.dados : null;

  // Botões "Cotas" / "Editar" das tabelas trocam o item pela URL (?coditem=)
  const daUrl = parametros.get('coditem') ?? '';
  useEffect(() => {
    if (daUrl && daUrl !== digitado.trim()) setDigitado(daUrl);
    // Só reage à URL; o que se digita no campo não volta para ela a cada tecla
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [daUrl]);

  return (
    <section id="cotas" className="cartao" aria-labelledby="esp-titulo-cotas">
      <h2 id="esp-titulo-cotas">Cotas dimensionais por item/desenho</h2>
      <p className="dica">
        Cadastre aqui as características e cotas de cada item quando estiverem definidas. Em branco, a inspeção dimensional segue com campos
        livres.
      </p>
      <div className="campo campo-em-linha">
        <label htmlFor="esp-coditem">Código do item (CODITEM)</label>
        <input
          id="esp-coditem"
          type="text"
          list="esp-lista-coditens"
          maxLength={40}
          value={digitado}
          placeholder="Ex.: 90009"
          onChange={(e) => setDigitado(e.target.value)}
          onBlur={() => setParametros(digitado.trim() ? { coditem: digitado.trim() } : {}, { replace: true })}
        />
        <datalist id="esp-lista-coditens">
          {tela.desenhos.map((d) => (
            <option key={d.coditem} value={d.coditem}>
              {[d.classificacao, d.descricao].filter(Boolean).join(' - ')}
            </option>
          ))}
        </datalist>
      </div>
      {!coditem && <p className="dica">Digite ou escolha um código para ver e editar as cotas.</p>}
      {coditem && carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
      {coditem && !carga.erro && !item && <Carregando />}
      {item && (
        <EditorCotas
          key={`${item.coditem}-${versao}`}
          item={item}
          podeEditar={podeEditar}
          aoSalvar={() => {
            setVersao((v) => v + 1);
            aoMudar();
          }}
        />
      )}

      {tela.itens.length > 0 && (
        <div className="secao-seguinte">
          <h3>Itens já cadastrados</h3>
          <div className="tabela-rolagem tabela-estreita">
            <table className="tabela">
              <thead>
                <tr>
                  <th scope="col">Código do item</th>
                  <th scope="col">Descrição</th>
                  <th scope="col" className="num">
                    Nº de cotas
                  </th>
                  <th scope="col">
                    <span className="so-leitor">Ações</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {tela.itens.map((i) => (
                  <tr key={i.coditem}>
                    <td className="mono">{i.coditem}</td>
                    <td>{i.descricao || TRACO}</td>
                    <td className="num">{inteiro(i.n_cotas)}</td>
                    <td>
                      <button type="button" className="botao-link" onClick={() => abrirItem(i.coditem)}>
                        {podeEditar ? 'Editar' : 'Ver'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- tela

export function Especificacoes() {
  const carga = useCarga<TelaEspecificacoes>((sinal) => api('/especificacoes', { sinal }), []);
  const [, setParametros] = useSearchParams();
  const tela = carga.dados;

  function abrirItem(coditem: string) {
    setParametros({ coditem }, { replace: true });
    document.getElementById('cotas')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function trocarTipo(nova: EspecificacaoTipo) {
    if (tela) carga.definir({ ...tela, tipos: tela.tipos.map((t) => (t.tipo === nova.tipo ? nova : t)) });
  }

  return (
    <>
      <Cabecalho
        titulo="Especificações"
        apoio="Limites por tipo de peça (dureza, tração, Charpy) e cotas dimensionais por item/desenho. Preenchido aqui, aparece pré-preenchido (mas editável) no registro de cada lote."
      />
      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={carga.recarregar} />}
      {!carga.erro && !tela && <Carregando />}
      {tela && (
        <div className="pilha">
          <Faixa tipo="alerta">
            Use só os valores da especificação técnica do cliente. Se um limite não estiver na especificação, deixe o campo <strong>vazio</strong>
            : o sistema nunca completa nem arredonda valores.
          </Faixa>
          {!tela.pode_editar && <Faixa tipo="info">Você pode consultar. Só quem tem o módulo Cadastros altera as especificações.</Faixa>}

          <section aria-labelledby="esp-titulo-tipos" className="pilha">
            <h2 id="esp-titulo-tipos">Dureza, tração e Charpy por tipo</h2>
            {tela.tipos.map((spec) => (
              <details key={spec.tipo} className="cartao esp-tipo">
                <summary>
                  <SeloTipo tipo={spec.tipo} /> <strong>Dureza / Tração / Charpy — {spec.tipo}</strong>{' '}
                  <span className="sub-linha">· {resumoDureza(spec)}</span>
                </summary>
                <FormTipo spec={spec} podeEditar={tela.pode_editar} aoSalvar={trocarTipo} />
              </details>
            ))}
          </section>

          <section className="cartao" aria-labelledby="esp-titulo-desenhos">
            <h2 id="esp-titulo-desenhos">Desenhos cadastrados</h2>
            <p className="dica">Classificação detectada automaticamente pelo nome do arquivo do desenho.</p>
            {tela.desenhos.length === 0 ? (
              <Vazio titulo="Nenhum desenho encontrado na pasta de desenhos." />
            ) : (
              <div className="tabela-rolagem">
                <table className="tabela">
                  <thead>
                    <tr>
                      <th scope="col">Código do item</th>
                      <th scope="col">Classificação</th>
                      <th scope="col">Descrição</th>
                      <th scope="col">
                        <span className="so-leitor">Ações</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {tela.desenhos.map((d) => (
                      <tr key={d.coditem}>
                        <td className="mono">
                          <strong>{d.coditem}</strong>
                        </td>
                        <td>{d.classificacao ? <SeloTipo tipo={d.classificacao} /> : TRACO}</td>
                        <td>{d.descricao}</td>
                        <td>
                          <span className="acoes-linha">
                            <a href={enderecoApi(`/recursos/desenhos/${encodeURIComponent(d.coditem)}`)} target="_blank" rel="noopener" className="botao-link">
                              Ver desenho<span className="so-leitor"> (abre em outra aba)</span>
                            </a>
                            <button type="button" className="botao-link" onClick={() => abrirItem(d.coditem)}>
                              Cotas{d.n_cotas > 0 && ` (${inteiro(d.n_cotas)})`}
                            </button>
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <SecaoCotas tela={tela} podeEditar={tela.pode_editar} aoMudar={carga.recarregar} abrirItem={abrirItem} />
        </div>
      )}
    </>
  );
}
