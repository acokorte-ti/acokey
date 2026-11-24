/**
 * Formulário detalhado de registro de cada tipo de etapa (legado/templates_html.py, TEMPLATES["etapa"]).
 * O resultado (aprovado/reprovado) aparece ao vivo, em verde/vermelho pela especificação; quem grava e decide é o
 * servidor (backend/app/formularios.py). Limite cadastrado na especificação aparece travado: só o que não está
 * cadastrado é digitado (nunca se inventa valor da especificação técnica).
 */
import { useMemo, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Campo, Marcacao } from '../../componentes/Campo';
import { Faixa } from '../../componentes/Estados';
import { api, enderecoApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { useSessao } from '../../lib/sessao';
import { enterVaiParaProximo } from '../../lib/teclado';
import { codigoLaser, dentro, fmt, lerCurva, lerLeituras, num, tempoNoPatamar, tokens } from './calculos';
import type { PaginaEtapaDados, RespostaRegistro } from './tipos';

type Linha = Record<string, string>;
interface Campos {
  [chave: string]: string | boolean | Linha[] | Record<string, Linha>;
}

const VAZIO_TRACAO: Linha = { cp: '', le: '', lr: '', al: '', ra: '' };
const VAZIO_CHARPY: Linha = { cp: '', j1: '', j2: '', j3: '' };
const VAZIO_COTA: Linha = { cota_id: '', descricao: '', nominal: '', tol_min: '', tol_max: '', medidas: '' };

/** Valores com que cada formulário abre (os mesmos padrões do sistema antigo). */
export function camposIniciais(d: PaginaEtapaDados): Campos {
  const qtd = String(d.lote.qtd ?? '');
  const base: Campos = { obs: '', decisao: 'aprovado' };
  switch (d.etapa.formulario) {
    case 'quimica':
      return { ...base, corrida: d.lote.corrida ?? '', fornecedor: '', cert: '', norma: '', elementos: {} };
    case 'tt':
      return { ...base, ciclo: d.padroes.ciclos_tt[0] ?? '', forno: '', alvo: '', tol: '10', patamar: '', meio: '', curva: '' };
    case 'dureza':
      return { ...base, min: '', max: '', equip: '', leituras: '' };
    case 'lab':
      return {
        ...base,
        laboratorio: '',
        rel_lab: '',
        le_min: '', le_max: '', lr_min: '', lr_max: '', al_min: '', ra_min: '',
        temp: d.espec?.ch_temp ?? '', dim_cp: d.espec?.ch_dim_cp ?? '', med_min: '', ind_min: '',
        cps: [1, 2, 3].map((n) => ({ ...VAZIO_TRACAO, cp: `CP${n}` })),
        conjuntos: [1, 2].map((n) => ({ ...VAZIO_CHARPY, cp: `Conjunto ${n}` })),
        validado: false,
        validador: d.padroes.usuario,
      }; // prettier-ignore
    case 'dim':
      return {
        ...base,
        instrumento: '',
        calib: '',
        amostra: '',
        cotas:
          d.cotas.length > 0
            ? d.cotas.map((c) => ({ ...VAZIO_COTA, cota_id: String(c.id), descricao: c.descricao, nominal: c.nominal, tol_min: c.tol_min, tol_max: c.tol_max }))
            : [1, 2, 3, 4].map(() => ({ ...VAZIO_COTA })),
      };
    case 'lp':
      return { ...base, norma: '', penetrante: '', revelador: '', temp: '', t_pen: '', inspetor: '', qtd_insp: qtd, indicacoes: '0', desc_ind: '' };
    case 'simples':
      return { ...base, tempo: '', midia: '', ok: false };
    case 'fosfato':
      return { ...base, fornecedor: '', cert: '', envio: '', retorno: '', esp: '', qtd_rec: qtd };
    case 'visual':
      return { ...base, qtd_aprov: qtd, qtd_reprov: '0', ano: String(d.padroes.ano), tri: String(d.padroes.trimestre), laser: '' };
    case 'embalagem':
      return { ...base, tipo_emb: '', qtd_emb: qtd, parafusos: qtd, volumes: '' };
    default:
      return base;
  }
}

// ---------------------------------------------------------------- peças comuns

interface PropsForm {
  dados: PaginaEtapaDados;
  campos: Campos;
  definir: (chave: string, valor: Campos[string]) => void;
}

function texto(campos: Campos, chave: string): string {
  const valor = campos[chave];
  return typeof valor === 'string' ? valor : '';
}

function linhas(campos: Campos, chave: string): Linha[] {
  const valor = campos[chave];
  return Array.isArray(valor) ? valor : [];
}

/** Campo de texto simples ligado ao estado do formulário. */
function CampoTexto({
  id,
  rotulo,
  campos,
  definir,
  chave,
  obrigatorio,
  dica,
  numero,
  tipo = 'text',
  lista,
  dicaTexto,
  classe,
  estado,
}: {
  id: string;
  rotulo: string;
  chave: string;
  obrigatorio?: boolean;
  dica?: ReactNode;
  numero?: boolean;
  tipo?: 'text' | 'date';
  lista?: string;
  dicaTexto?: string;
  classe?: string;
  estado?: 'ok' | 'fora' | null;
} & Omit<PropsForm, 'dados'>) {
  return (
    <Campo rotulo={rotulo} para={id} obrigatorio={obrigatorio} dica={dica} classe={classe}>
      <input
        id={id}
        type={tipo}
        inputMode={numero ? 'decimal' : undefined}
        value={texto(campos, chave)}
        onChange={(e) => definir(chave, e.target.value)}
        list={lista}
        placeholder={dicaTexto}
        className={estado ? `lt-valor-${estado}` : undefined}
        autoComplete="off"
      />
    </Campo>
  );
}

/** Limite da especificação: travado quando cadastrado, digitável quando não. */
function CampoLimite({
  id,
  rotulo,
  chave,
  cadastrado,
  campos,
  definir,
}: { id: string; rotulo: string; chave: string; cadastrado: number | null | undefined } & Omit<PropsForm, 'dados'>) {
  if (cadastrado !== null && cadastrado !== undefined) {
    return (
      <Campo rotulo={rotulo} para={id} dica="Do cadastro de especificações">
        <input id={id} type="text" value={fmt(cadastrado)} readOnly className="lt-cadastro" />
      </Campo>
    );
  }
  return <CampoTexto id={id} rotulo={rotulo} chave={chave} numero campos={campos} definir={definir} dica="Não cadastrado: informe" />;
}

/** O limite que vale: o cadastrado ou o digitado. */
function limite(cadastrado: number | null | undefined, digitado: string): number | null {
  return cadastrado !== null && cadastrado !== undefined ? cadastrado : num(digitado);
}

function Resultado({ ok, texto: rotulo }: { ok: boolean | null; texto?: string }) {
  if (ok === null) return <span className="lt-res lt-res-vazio">—</span>;
  return <span className={`lt-res ${ok ? 'lt-res-ok' : 'lt-res-fora'}`}>{rotulo ?? (ok ? 'OK' : 'FORA')}</span>;
}

/** Resumo do resultado calculado, em cima do botão de salvar. */
function Previa({ ok, children }: { ok: boolean | null; children: ReactNode }) {
  if (ok === null) return null;
  return (
    <div className={`lt-previa ${ok ? 'lt-previa-ok' : 'lt-previa-fora'}`} role="status">
      <strong>{ok ? 'Dentro da especificação' : 'Fora da especificação'}</strong>
      <span>{children}</span>
    </div>
  );
}

function NotaEspec({ dados, tem }: { dados: PaginaEtapaDados; tem: boolean }) {
  const { pode } = useSessao();
  return (
    <p className="dica">
      {tem ? `Limites do cadastro de especificações para ${dados.lote.tipo}.` : `Sem especificação cadastrada para ${dados.lote.tipo}: informe os limites.`}{' '}
      {pode.cadastros && <Link to="/especificacoes">Abrir especificações</Link>}
    </p>
  );
}

/** Seletor que preenche o campo com a frase do equipamento cadastrado (durômetro, instrumento, forno). */
function EscolherEquipamento({ dados, aoEscolher, id }: { dados: PaginaEtapaDados; aoEscolher: (texto: string) => void; id: string }) {
  if (dados.equipamentos.length === 0) return null;
  return (
    <Campo rotulo="Preencher com equipamento cadastrado" para={id}>
      <select
        id={id}
        value=""
        onChange={(e) => {
          const escolhido = dados.equipamentos.find((eq) => eq.codigo === e.target.value);
          if (escolhido) aoEscolher(escolhido.texto);
        }}
      >
        <option value="">— escolher —</option>
        {dados.equipamentos.map((eq) => (
          <option key={eq.codigo} value={eq.codigo}>
            {eq.codigo} — {eq.descricao}
            {eq.vencido ? ' (calibração vencida)' : ''}
          </option>
        ))}
      </select>
    </Campo>
  );
}

function TabelaEditavel({
  titulo,
  cabecalho,
  children,
  aoAcrescentar,
  rotuloAcrescentar,
}: {
  titulo: string;
  cabecalho: string[];
  children: ReactNode;
  aoAcrescentar?: () => void;
  rotuloAcrescentar?: string;
}) {
  return (
    <div className="col-4">
      <div className="tabela-rolagem">
        <table className="tabela lt-tabela-form">
          <caption className="so-leitor">{titulo}</caption>
          <thead>
            <tr>
              {cabecalho.map((c) => (
                <th key={c} scope="col">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
      {aoAcrescentar && (
        <button type="button" className="botao botao-pequeno lt-acrescentar" onClick={aoAcrescentar}>
          {rotuloAcrescentar}
        </button>
      )}
    </div>
  );
}

function celula(valor: string, aoMudar: (v: string) => void, rotulo: string, opcoes: { numero?: boolean; estado?: 'ok' | 'fora' | null; somenteLeitura?: boolean; dica?: string } = {}) {
  return (
    <td>
      <input
        type="text"
        aria-label={rotulo}
        inputMode={opcoes.numero ? 'decimal' : undefined}
        value={valor}
        readOnly={opcoes.somenteLeitura}
        placeholder={opcoes.dica}
        className={[opcoes.estado ? `lt-valor-${opcoes.estado}` : '', opcoes.somenteLeitura ? 'lt-cadastro' : ''].join(' ').trim() || undefined}
        onChange={(e) => aoMudar(e.target.value)}
        autoComplete="off"
      />
    </td>
  );
}

function trocarLinha(lista: Linha[], indice: number, chave: string, valor: string): Linha[] {
  return lista.map((l, i) => (i === indice ? { ...l, [chave]: valor } : l));
}

// ---------------------------------------------------------------- composição química (Receb. MP)

function FormQuimica({ dados, campos, definir }: PropsForm) {
  const elementos = (campos.elementos as Record<string, Linha>) ?? {};
  const mudar = (el: string, chave: string, valor: string) => definir('elementos', { ...elementos, [el]: { ...(elementos[el] ?? {}), [chave]: valor } });
  const avaliacao = dados.padroes.elementos.map((el) => {
    const e = elementos[el] ?? {};
    const v = num(e.valor ?? '');
    return v === null ? null : dentro(v, num(e.min ?? ''), num(e.max ?? ''));
  });
  const avaliados = avaliacao.filter((a): a is boolean => a !== null);
  return (
    <>
      <CampoTexto id="f-corrida" rotulo="Corrida nº" chave="corrida" obrigatorio lista="lt-corridas-mp" campos={campos} definir={definir} />
      <datalist id="lt-corridas-mp">
        {dados.corridas_mp.map((c) => (
          <option key={`${c.corrida}-${c.nf_entrada}`} value={c.corrida}>
            {[c.tipo_destino, c.nf_entrada && `NF ${c.nf_entrada}`, c.fornecedor].filter(Boolean).join(' · ')}
          </option>
        ))}
      </datalist>
      <CampoTexto id="f-fornecedor" rotulo="Fornecedor" chave="fornecedor" campos={campos} definir={definir} />
      <CampoTexto id="f-cert" rotulo="Certificado nº" chave="cert" campos={campos} definir={definir} />
      <CampoTexto id="f-norma" rotulo="Norma / grau do aço" chave="norma" campos={campos} definir={definir} />
      <TabelaEditavel titulo="Composição química" cabecalho={['Elemento', 'Valor (%)', 'Mín. (%)', 'Máx. (%)', 'Resultado']}>
        {dados.padroes.elementos.map((el, i) => {
          const e = elementos[el] ?? {};
          const estado = avaliacao[i] === null ? null : avaliacao[i] ? 'ok' : 'fora';
          return (
            <tr key={el}>
              <th scope="row">{el}</th>
              {celula(e.valor ?? '', (v) => mudar(el, 'valor', v), `Valor de ${el}`, { numero: true, estado })}
              {celula(e.min ?? '', (v) => mudar(el, 'min', v), `Mínimo de ${el}`, { numero: true })}
              {celula(e.max ?? '', (v) => mudar(el, 'max', v), `Máximo de ${el}`, { numero: true })}
              <td>
                <Resultado ok={avaliacao[i]} />
              </td>
            </tr>
          );
        })}
      </TabelaEditavel>
      <div className="col-4">
        <Previa ok={avaliados.length ? avaliados.every(Boolean) : null}>
          {avaliados.length} elemento(s) informado(s), {avaliados.filter((a) => !a).length} fora da faixa.
        </Previa>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- tratamento térmico

function GraficoCurva({ pontos, alvo, tol }: { pontos: [number, number][]; alvo: number | null; tol: number }) {
  if (pontos.length < 2) return null;
  const L = 640;
  const A = 220;
  const m = { e: 46, d: 12, t: 10, b: 30 };
  const xs = pontos.map((p) => p[0]);
  const ys = pontos.map((p) => p[1]).concat(alvo !== null ? [alvo + tol, alvo - tol] : []);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(0, ...ys), Math.max(...ys) * 1.05 || 1];
  const px = (x: number) => m.e + ((x - x0) / (x1 - x0 || 1)) * (L - m.e - m.d);
  const py = (y: number) => A - m.b - ((y - y0) / (y1 - y0 || 1)) * (A - m.t - m.b);
  const marcasY = [0, 0.25, 0.5, 0.75, 1].map((f) => y0 + f * (y1 - y0));
  return (
    <figure className="col-4 lt-grafico">
      <svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label="Curva do forno: temperatura pelo tempo">
        {marcasY.map((y) => (
          <g key={y}>
            <line x1={m.e} x2={L - m.d} y1={py(y)} y2={py(y)} className="lt-grafico-grade" />
            <text x={m.e - 6} y={py(y) + 4} textAnchor="end" className="lt-grafico-texto">
              {Math.round(y)}
            </text>
          </g>
        ))}
        {alvo !== null && <rect x={m.e} width={L - m.e - m.d} y={py(alvo + tol)} height={Math.max(py(alvo - tol) - py(alvo + tol), 1)} className="lt-grafico-faixa" />}
        <polyline points={pontos.map(([x, y]) => `${px(x)},${py(y)}`).join(' ')} className="lt-grafico-linha" />
        <text x={m.e} y={A - 8} className="lt-grafico-texto">
          {fmt(x0)} min
        </text>
        <text x={L - m.d} y={A - 8} textAnchor="end" className="lt-grafico-texto">
          {fmt(x1)} min
        </text>
      </svg>
      <figcaption className="dica">Temperatura (°C) pelo tempo (min). Faixa verde: temperatura alvo ± tolerância.</figcaption>
    </figure>
  );
}

function FormTT({ dados, campos, definir }: PropsForm) {
  const avisos = useAvisos();
  const pontos = useMemo(() => lerCurva(texto(campos, 'curva')), [campos]);
  const alvo = num(texto(campos, 'alvo'));
  const tol = num(texto(campos, 'tol')) ?? 10;
  const patamar = num(texto(campos, 'patamar'));
  const medido = alvo !== null && pontos.length >= 2 ? tempoNoPatamar(pontos, alvo - tol, alvo + tol) : null;
  const ok = medido !== null && patamar !== null ? medido >= patamar : null;

  function lerArquivo(evento: ChangeEvent<HTMLInputElement>) {
    const arquivo = evento.target.files?.[0];
    evento.target.value = '';
    if (!arquivo) return;
    if (arquivo.size > 2 * 1024 * 1024) {
      avisos.erro('O arquivo da curva passa de 2 MB.');
      return;
    }
    arquivo.text().then(
      (conteudo) => definir('curva', conteudo),
      () => avisos.erro('Não foi possível ler o arquivo da curva.'),
    );
  }

  return (
    <>
      <Campo rotulo="Ciclo" para="f-ciclo">
        <select id="f-ciclo" value={texto(campos, 'ciclo')} onChange={(e) => definir('ciclo', e.target.value)}>
          {dados.padroes.ciclos_tt.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </Campo>
      <CampoTexto id="f-forno" rotulo="Forno" chave="forno" lista="lt-fornos" campos={campos} definir={definir} />
      <datalist id="lt-fornos">
        {dados.equipamentos.map((eq) => (
          <option key={eq.codigo} value={`${eq.descricao} – ${eq.codigo}`} />
        ))}
      </datalist>
      <CampoTexto id="f-alvo" rotulo="Temperatura alvo (°C)" chave="alvo" numero obrigatorio campos={campos} definir={definir} />
      <CampoTexto id="f-tol" rotulo="Tolerância (± °C)" chave="tol" numero campos={campos} definir={definir} />
      <CampoTexto id="f-patamar" rotulo="Patamar exigido (min)" chave="patamar" numero obrigatorio campos={campos} definir={definir} />
      <CampoTexto id="f-meio" rotulo="Meio de resfriamento" chave="meio" dicaTexto="Água, óleo, ar..." campos={campos} definir={definir} />
      <Campo rotulo='Curva do forno: cole linhas "tempo(min); temperatura(°C)"' para="f-curva" classe="col-4" obrigatorio>
        <textarea id="f-curva" rows={6} value={texto(campos, 'curva')} onChange={(e) => definir('curva', e.target.value)} placeholder={'0; 25\n30; 450\n60; 850\n120; 850'} />
      </Campo>
      <Campo rotulo="ou carregue o arquivo CSV/TXT do forno" para="f-curva-arquivo" classe="col-2">
        <input id="f-curva-arquivo" type="file" accept=".csv,.txt" onChange={lerArquivo} />
      </Campo>
      <div className="col-2 lt-numeros">
        <span>
          Pontos lidos: <strong>{pontos.length}</strong>
        </span>
        {pontos.length >= 2 && (
          <>
            <span>
              Temperatura máxima: <strong>{fmt(Math.max(...pontos.map((p) => p[1])), 0)} °C</strong>
            </span>
            <span>
              Duração total: <strong>{fmt(pontos[pontos.length - 1][0] - pontos[0][0], 0)} min</strong>
            </span>
          </>
        )}
        {medido !== null && (
          <span>
            Tempo no patamar: <strong>{fmt(medido, 1)} min</strong>
          </span>
        )}
      </div>
      <GraficoCurva pontos={pontos} alvo={alvo} tol={tol} />
      <div className="col-4">
        <Previa ok={ok}>
          Medido no patamar {fmt(medido ?? 0, 1)} min; exigido {fmt(patamar ?? 0)} min.
        </Previa>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- dureza

function FormDureza({ dados, campos, definir }: PropsForm) {
  const minimo = limite(dados.espec?.dureza_min, texto(campos, 'min'));
  const maximo = limite(dados.espec?.dureza_max, texto(campos, 'max'));
  const leitura = useMemo(() => lerLeituras(texto(campos, 'leituras')), [campos]);
  const valores = leitura.pecas.flatMap((p) => p.valores);
  const temLimite = minimo !== null || maximo !== null;
  const fora = temLimite ? valores.filter((v) => !dentro(v, minimo, maximo)).length : 0;
  return (
    <>
      <div className="col-4">
        <NotaEspec dados={dados} tem={dados.espec?.dureza_min != null || dados.espec?.dureza_max != null} />
      </div>
      <CampoLimite id="f-min" rotulo="Dureza mínima (HRC)" chave="min" cadastrado={dados.espec?.dureza_min} campos={campos} definir={definir} />
      <CampoLimite id="f-max" rotulo="Dureza máxima (HRC)" chave="max" cadastrado={dados.espec?.dureza_max} campos={campos} definir={definir} />
      <CampoTexto id="f-equip" rotulo="Durômetro / certificado de calibração" chave="equip" classe="col-2" campos={campos} definir={definir} />
      <EscolherEquipamento id="f-equip-cadastro" dados={dados} aoEscolher={(t) => definir('equip', t)} />
      <Campo
        rotulo="Leituras (uma peça por linha; pode ter vários pontos)"
        para="f-leituras"
        classe="col-4"
        obrigatorio
        dica="Exemplos: P1 35 · P1 35 35 37 · P1-35-35-37 · 35;35;37"
      >
        <textarea id="f-leituras" rows={7} value={texto(campos, 'leituras')} onChange={(e) => definir('leituras', e.target.value)} placeholder={'P1 35 35 37\nP2 36 35 36\nP3 35 37 35'} />
      </Campo>
      {leitura.erro && (
        <div className="col-4">
          <Faixa tipo="erro">{leitura.erro}</Faixa>
        </div>
      )}
      {leitura.pecas.length > 0 && (
        <div className="col-4 lt-leituras" aria-label="Leituras conferidas">
          {leitura.pecas.flatMap((p) =>
            p.valores.map((v, j) => {
              const ok = temLimite ? dentro(v, minimo, maximo) : null;
              return (
                <span key={`${p.nome}-${j}`} className={`lt-leitura ${ok === null ? '' : ok ? 'lt-leitura-ok' : 'lt-leitura-fora'}`}>
                  {p.valores.length === 1 ? p.nome : `${p.nome} pt${j + 1}`}: <strong>{fmt(v, 2)}</strong>
                </span>
              );
            }),
          )}
        </div>
      )}
      {valores.length > 0 && (
        <div className="col-4 lt-numeros">
          <span>
            Leituras: <strong>{valores.length}</strong>
          </span>
          <span>
            Mín. / Máx.: <strong>{fmt(Math.min(...valores), 2)} / {fmt(Math.max(...valores), 2)} HRC</strong>
          </span>
          <span>
            Média: <strong>{fmt(valores.reduce((a, b) => a + b, 0) / valores.length, 1)} HRC</strong>
          </span>
        </div>
      )}
      <div className="col-4">
        <Previa ok={valores.length && temLimite && !leitura.erro ? fora === 0 : null}>
          {fora === 0 ? 'Todas as leituras dentro da faixa.' : `${fora} leitura(s) fora da faixa de ${fmt(minimo) || '-'} a ${fmt(maximo) || '-'} HRC.`}
        </Previa>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- laboratório externo (tração e Charpy)

function CamposLaboratorio({ dados, campos, definir }: PropsForm) {
  return (
    <>
      <CampoTexto id="f-laboratorio" rotulo="Laboratório" chave="laboratorio" lista="lt-laboratorios" campos={campos} definir={definir} />
      <datalist id="lt-laboratorios">
        {dados.prestadores.map((p) => (
          <option key={p.codigo} value={p.razao_social} />
        ))}
      </datalist>
      <CampoTexto id="f-rel-lab" rotulo="Nº do relatório do laboratório" chave="rel_lab" campos={campos} definir={definir} />
    </>
  );
}

function FormTracao({ dados, campos, definir }: PropsForm) {
  const e = dados.espec;
  const sp = {
    le_min: limite(e?.tr_le_min, texto(campos, 'le_min')),
    le_max: limite(e?.tr_le_max, texto(campos, 'le_max')),
    lr_min: limite(e?.tr_lr_min, texto(campos, 'lr_min')),
    lr_max: limite(e?.tr_lr_max, texto(campos, 'lr_max')),
    al_min: limite(e?.tr_al_min, texto(campos, 'al_min')),
    ra_min: limite(e?.tr_ra_min, texto(campos, 'ra_min')),
  };
  const cps = linhas(campos, 'cps');
  const avaliacao = cps.map((cp) => {
    const [le, lr, al, ra] = [num(cp.le), num(cp.lr), num(cp.al), num(cp.ra)];
    if (le === null || lr === null || al === null) return null;
    return dentro(le, sp.le_min, sp.le_max) && dentro(lr, sp.lr_min, sp.lr_max) && dentro(al, sp.al_min, null) && (ra === null || dentro(ra, sp.ra_min, null));
  });
  const avaliados = avaliacao.filter((a): a is boolean => a !== null);
  const mudar = (i: number, chave: string, valor: string) => definir('cps', trocarLinha(cps, i, chave, valor));
  const estado = (ok: boolean) => (ok ? 'ok' : 'fora');
  return (
    <>
      <CamposLaboratorio dados={dados} campos={campos} definir={definir} />
      <div className="col-4">
        <NotaEspec dados={dados} tem={e?.tr_le_min != null || e?.tr_lr_min != null} />
      </div>
      <CampoLimite id="f-le-min" rotulo="LE mín. (MPa)" chave="le_min" cadastrado={e?.tr_le_min} campos={campos} definir={definir} />
      <CampoLimite id="f-le-max" rotulo="LE máx. (MPa)" chave="le_max" cadastrado={e?.tr_le_max} campos={campos} definir={definir} />
      <CampoLimite id="f-lr-min" rotulo="LR mín. (MPa)" chave="lr_min" cadastrado={e?.tr_lr_min} campos={campos} definir={definir} />
      <CampoLimite id="f-lr-max" rotulo="LR máx. (MPa)" chave="lr_max" cadastrado={e?.tr_lr_max} campos={campos} definir={definir} />
      <CampoLimite id="f-al-min" rotulo="Along. mín. (%)" chave="al_min" cadastrado={e?.tr_al_min} campos={campos} definir={definir} />
      <CampoLimite id="f-ra-min" rotulo="RA mín. (%)" chave="ra_min" cadastrado={e?.tr_ra_min} campos={campos} definir={definir} />
      <TabelaEditavel
        titulo="Corpos de prova de tração"
        cabecalho={['CP', 'LE (MPa)', 'LR (MPa)', 'A (%)', 'RA (%)', 'Resultado']}
        aoAcrescentar={() => definir('cps', [...cps, { ...VAZIO_TRACAO, cp: `CP${cps.length + 1}` }])}
        rotuloAcrescentar="+ corpo de prova"
      >
        {cps.map((cp, i) => {
          const [le, lr, al, ra] = [num(cp.le), num(cp.lr), num(cp.al), num(cp.ra)];
          return (
            <tr key={i}>
              {celula(cp.cp, (v) => mudar(i, 'cp', v), `Nome do corpo de prova ${i + 1}`)}
              {celula(cp.le, (v) => mudar(i, 'le', v), `LE do ${cp.cp}`, { numero: true, estado: le === null ? null : estado(dentro(le, sp.le_min, sp.le_max)) })}
              {celula(cp.lr, (v) => mudar(i, 'lr', v), `LR do ${cp.cp}`, { numero: true, estado: lr === null ? null : estado(dentro(lr, sp.lr_min, sp.lr_max)) })}
              {celula(cp.al, (v) => mudar(i, 'al', v), `Alongamento do ${cp.cp}`, { numero: true, estado: al === null ? null : estado(dentro(al, sp.al_min, null)) })}
              {celula(cp.ra, (v) => mudar(i, 'ra', v), `RA do ${cp.cp}`, { numero: true, estado: ra === null ? null : estado(dentro(ra, sp.ra_min, null)) })}
              <td>
                <Resultado ok={avaliacao[i]} />
              </td>
            </tr>
          );
        })}
      </TabelaEditavel>
      <div className="col-4">
        <Previa ok={avaliados.length ? avaliados.every(Boolean) : null}>
          {avaliados.length} corpo(s) de prova, {avaliados.filter((a) => !a).length} fora da especificação.
        </Previa>
      </div>
    </>
  );
}

function FormCharpy({ dados, campos, definir }: PropsForm) {
  const e = dados.espec;
  const mediaMin = limite(e?.ch_med_min, texto(campos, 'med_min'));
  const indMin = limite(e?.ch_ind_min, texto(campos, 'ind_min'));
  const conjuntos = linhas(campos, 'conjuntos');
  const calculo = conjuntos.map((c) => {
    const j = [num(c.j1), num(c.j2), num(c.j3)];
    if (j.some((v) => v === null)) return null;
    const valores = j as number[];
    const media = (valores[0] + valores[1] + valores[2]) / 3;
    return { media, ok: (mediaMin === null || media >= mediaMin) && (indMin === null || Math.min(...valores) >= indMin) };
  });
  const avaliados = calculo.filter((c): c is { media: number; ok: boolean } => c !== null);
  const mudar = (i: number, chave: string, valor: string) => definir('conjuntos', trocarLinha(conjuntos, i, chave, valor));
  const travado = (valor: string | undefined) => Boolean(valor && valor.trim());
  return (
    <>
      <CamposLaboratorio dados={dados} campos={campos} definir={definir} />
      <div className="col-4">
        <NotaEspec dados={dados} tem={e?.ch_med_min != null || e?.ch_ind_min != null} />
      </div>
      {travado(e?.ch_temp) ? (
        <Campo rotulo="Temperatura de ensaio (°C)" para="f-temp" dica="Do cadastro de especificações">
          <input id="f-temp" type="text" value={e?.ch_temp} readOnly className="lt-cadastro" />
        </Campo>
      ) : (
        <CampoTexto id="f-temp" rotulo="Temperatura de ensaio (°C)" chave="temp" campos={campos} definir={definir} />
      )}
      {travado(e?.ch_dim_cp) ? (
        <Campo rotulo="Corpo de prova" para="f-dim-cp" dica="Do cadastro de especificações">
          <input id="f-dim-cp" type="text" value={e?.ch_dim_cp} readOnly className="lt-cadastro" />
        </Campo>
      ) : (
        <CampoTexto id="f-dim-cp" rotulo="Corpo de prova" chave="dim_cp" dicaTexto="10x10 mm, entalhe V" campos={campos} definir={definir} />
      )}
      <CampoLimite id="f-med-min" rotulo="Energia média mín. (J)" chave="med_min" cadastrado={e?.ch_med_min} campos={campos} definir={definir} />
      <CampoLimite id="f-ind-min" rotulo="Energia individual mín. (J)" chave="ind_min" cadastrado={e?.ch_ind_min} campos={campos} definir={definir} />
      <TabelaEditavel
        titulo="Energia absorvida (Charpy)"
        cabecalho={['Conjunto', 'CP1 (J)', 'CP2 (J)', 'CP3 (J)', 'Média (J)', 'Resultado']}
        aoAcrescentar={() => definir('conjuntos', [...conjuntos, { ...VAZIO_CHARPY, cp: `Conjunto ${conjuntos.length + 1}` }])}
        rotuloAcrescentar="+ conjunto"
      >
        {conjuntos.map((c, i) => (
          <tr key={i}>
            {celula(c.cp, (v) => mudar(i, 'cp', v), `Nome do conjunto ${i + 1}`)}
            {(['j1', 'j2', 'j3'] as const).map((k, n) => {
              const v = num(c[k]);
              return <ColunaJ key={k} valor={c[k]} aoMudar={(t) => mudar(i, k, t)} rotulo={`CP${n + 1} do ${c.cp}`} estado={v === null || indMin === null ? null : v >= indMin ? 'ok' : 'fora'} />;
            })}
            <td className="num">{calculo[i] ? fmt(calculo[i]?.media, 1) : '—'}</td>
            <td>
              <Resultado ok={calculo[i]?.ok ?? null} />
            </td>
          </tr>
        ))}
      </TabelaEditavel>
      <div className="col-4">
        <Previa ok={avaliados.length ? avaliados.every((c) => c.ok) : null}>
          {avaliados.length} conjunto(s), {avaliados.filter((c) => !c.ok).length} fora da especificação.
        </Previa>
      </div>
    </>
  );
}

function ColunaJ({ valor, aoMudar, rotulo, estado }: { valor: string; aoMudar: (v: string) => void; rotulo: string; estado: 'ok' | 'fora' | null }) {
  return celula(valor, aoMudar, rotulo, { numero: true, estado });
}

// ---------------------------------------------------------------- dimensional (usinagem e dimensional final)

function FormDim({ dados, campos, definir }: PropsForm) {
  const { pode } = useSessao();
  const cotas = linhas(campos, 'cotas');
  const mudar = (i: number, chave: string, valor: string) => definir('cotas', trocarLinha(cotas, i, chave, valor));
  const calculo = cotas.map((c) => {
    const medidas = tokens(c.medidas).map((t) => num(t));
    const [nominal, t1, t2] = [num(c.nominal), num(c.tol_min), num(c.tol_max)];
    if (medidas.length === 0 || medidas.some((m) => m === null) || nominal === null || t1 === null || t2 === null) return null;
    const [baixo, alto] = [nominal + t1, nominal + t2];
    const valores = medidas as number[];
    return { baixo, alto, ok: valores.every((v) => v >= baixo && v <= alto), min: Math.min(...valores), max: Math.max(...valores) };
  });
  const avaliados = calculo.filter((c): c is NonNullable<typeof c> => c !== null);
  return (
    <>
      <div className="col-4">
        <p className="dica">
          {dados.cotas.length > 0
            ? `Cotas do cadastro do item ${dados.lote.coditem} (travadas). `
            : dados.lote.coditem
              ? `Item ${dados.lote.coditem} ainda sem cotas cadastradas. `
              : 'Lote sem código de item: cotas em branco. '}
          {pode.cadastros && <Link to="/especificacoes">{dados.cotas.length > 0 || !dados.lote.coditem ? 'Abrir especificações' : 'Cadastrar cotas deste item'}</Link>}
          {dados.desenho && (
            <>
              {' · '}
              <a href={enderecoApi(`/recursos/desenhos/${encodeURIComponent(dados.desenho.coditem)}`)} target="_blank" rel="noopener">
                Desenho: {dados.desenho.descricao}
              </a>
            </>
          )}
        </p>
      </div>
      <CampoTexto id="f-instrumento" rotulo="Instrumento(s)" chave="instrumento" dicaTexto="Paquímetro, micrômetro..." campos={campos} definir={definir} />
      <CampoTexto id="f-calib" rotulo="Certificado de calibração" chave="calib" campos={campos} definir={definir} />
      <EscolherEquipamento id="f-calib-cadastro" dados={dados} aoEscolher={(t) => definir('calib', t)} />
      <CampoTexto id="f-amostra" rotulo="Peças medidas (ids)" chave="amostra" dicaTexto="Ex.: 1 a 5 / 100%" campos={campos} definir={definir} />
      <TabelaEditavel
        titulo="Cotas inspecionadas"
        cabecalho={['Cota', 'Nominal', 'Tol. inferior', 'Tol. superior', 'Medidas', 'Faixa', 'Resultado']}
        aoAcrescentar={() => definir('cotas', [...cotas, { ...VAZIO_COTA }])}
        rotuloAcrescentar="+ cota"
      >
        {cotas.map((c, i) => {
          const travada = Boolean(c.cota_id);
          const r = calculo[i];
          return (
            <tr key={i}>
              {celula(c.descricao, (v) => mudar(i, 'descricao', v), `Descrição da cota ${i + 1}`, { somenteLeitura: travada, dica: 'Ex.: Diâmetro externo' })}
              {celula(c.nominal, (v) => mudar(i, 'nominal', v), `Nominal da cota ${i + 1}`, { numero: true, somenteLeitura: travada })}
              {celula(c.tol_min, (v) => mudar(i, 'tol_min', v), `Tolerância inferior da cota ${i + 1}`, { numero: true, somenteLeitura: travada, dica: '-0,05' })}
              {celula(c.tol_max, (v) => mudar(i, 'tol_max', v), `Tolerância superior da cota ${i + 1}`, { numero: true, somenteLeitura: travada, dica: '+0,05' })}
              {celula(c.medidas, (v) => mudar(i, 'medidas', v), `Medidas da cota ${i + 1}`, { estado: r ? (r.ok ? 'ok' : 'fora') : null, dica: 'valores separados por ;' })}
              <td className="num">{r ? `${fmt(r.baixo)} a ${fmt(r.alto)}` : '—'}</td>
              <td>
                <Resultado ok={r ? r.ok : null} />
              </td>
            </tr>
          );
        })}
      </TabelaEditavel>
      <div className="col-4">
        <Previa ok={avaliados.length ? avaliados.every((c) => c.ok) : null}>
          {avaliados.length} cota(s) medida(s), {avaliados.filter((c) => !c.ok).length} fora da tolerância.
        </Previa>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- líquido penetrante, tamboreamento, revestimento

function FormLP({ campos, definir }: PropsForm) {
  const indicacoes = num(texto(campos, 'indicacoes'));
  return (
    <>
      <CampoTexto id="f-norma" rotulo="Norma / procedimento" chave="norma" dicaTexto="ASTM E165 / ISO 3452" campos={campos} definir={definir} />
      <CampoTexto id="f-penetrante" rotulo="Penetrante (marca/lote)" chave="penetrante" campos={campos} definir={definir} />
      <CampoTexto id="f-revelador" rotulo="Revelador (marca/lote)" chave="revelador" campos={campos} definir={definir} />
      <CampoTexto id="f-temp" rotulo="Temperatura da peça (°C)" chave="temp" numero campos={campos} definir={definir} />
      <CampoTexto id="f-t-pen" rotulo="Tempo de penetração (min)" chave="t_pen" numero campos={campos} definir={definir} />
      <CampoTexto id="f-inspetor" rotulo="Inspetor / nível" chave="inspetor" campos={campos} definir={definir} />
      <CampoTexto id="f-qtd-insp" rotulo="Peças inspecionadas" chave="qtd_insp" numero obrigatorio campos={campos} definir={definir} />
      <CampoTexto
        id="f-indicacoes"
        rotulo="Peças com indicação de trinca"
        chave="indicacoes"
        numero
        obrigatorio
        estado={indicacoes === null ? null : indicacoes === 0 ? 'ok' : 'fora'}
        campos={campos}
        definir={definir}
      />
      <CampoTexto id="f-desc-ind" rotulo="Descrição das indicações (se houver)" chave="desc_ind" classe="col-4" campos={campos} definir={definir} />
      <div className="col-4">
        <Previa ok={indicacoes === null ? null : indicacoes === 0}>{indicacoes === 0 ? 'Sem indicações relevantes.' : 'Indicações detectadas: o registro será REPROVADO.'}</Previa>
      </div>
    </>
  );
}

function FormSimples({ campos, definir }: PropsForm) {
  return (
    <>
      <CampoTexto id="f-tempo" rotulo="Tempo de processo (min)" chave="tempo" numero campos={campos} definir={definir} />
      <CampoTexto id="f-midia" rotulo="Mídia / abrasivo" chave="midia" campos={campos} definir={definir} />
      <div className="col-4">
        <Marcacao id="f-ok" marcado={campos.ok === true} aoMudar={(v) => definir('ok', v)}>
          Rebarbas removidas e peças sem danos
        </Marcacao>
        {campos.ok !== true && <p className="dica texto-alerta">Sem esta confirmação o registro é gravado como REPROVADO.</p>}
      </div>
    </>
  );
}

function FormFosfato({ dados, campos, definir }: PropsForm) {
  return (
    <>
      <CampoTexto id="f-fornecedor" rotulo="Fornecedor do revestimento" chave="fornecedor" lista="lt-revestidores" campos={campos} definir={definir} />
      <datalist id="lt-revestidores">
        {dados.prestadores.map((p) => (
          <option key={p.codigo} value={p.razao_social} />
        ))}
      </datalist>
      <CampoTexto id="f-cert" rotulo="Certificado nº" chave="cert" campos={campos} definir={definir} />
      <CampoTexto id="f-envio" rotulo="Data de envio" chave="envio" tipo="date" campos={campos} definir={definir} />
      <CampoTexto id="f-retorno" rotulo="Data de retorno" chave="retorno" tipo="date" campos={campos} definir={definir} />
      <CampoTexto id="f-esp" rotulo="Espessura da camada (µm)" chave="esp" numero campos={campos} definir={definir} />
      <CampoTexto id="f-qtd-rec" rotulo="Quantidade recebida" chave="qtd_rec" numero campos={campos} definir={definir} />
    </>
  );
}

// ---------------------------------------------------------------- inspeção visual e laser, embalagem

function FormVisual({ dados, campos, definir }: PropsForm) {
  const qtd = num(texto(campos, 'qtd_aprov'));
  const valores = { ano: texto(campos, 'ano'), tri: texto(campos, 'tri'), corrida: dados.lote.corrida || 'SC', lote: dados.lote.numero };
  const quantos = qtd !== null && qtd > 0 ? Math.floor(qtd) : 0;
  return (
    <>
      <CampoTexto id="f-qtd-aprov" rotulo="Peças aprovadas na inspeção visual" chave="qtd_aprov" numero obrigatorio campos={campos} definir={definir} />
      <CampoTexto id="f-qtd-reprov" rotulo="Peças reprovadas" chave="qtd_reprov" numero campos={campos} definir={definir} />
      <CampoTexto id="f-ano" rotulo="Ano" chave="ano" numero obrigatorio campos={campos} definir={definir} />
      <CampoTexto id="f-tri" rotulo="Trimestre (1 a 4)" chave="tri" numero obrigatorio campos={campos} definir={definir} />
      <CampoTexto id="f-laser" rotulo="Máquina laser / programa" chave="laser" classe="col-2" campos={campos} definir={definir} />
      <div className="col-4">
        <p className="dica">
          Código de cada peça: <strong className="mono">{dados.padroes.laser_formato_legivel}</strong> (corrida {dados.lote.corrida || 'sem corrida'}, lote{' '}
          {dados.lote.numero}). O arquivo do laser (CSV) fica disponível depois que a etapa for aprovada.
        </p>
        {quantos > 0 && (
          <p className="lt-numeros">
            <span>
              Primeiro código: <strong className="mono">{codigoLaser(dados.padroes.laser_formato, { ...valores, seq: 1 })}</strong>
            </span>
            <span>
              Último código: <strong className="mono">{codigoLaser(dados.padroes.laser_formato, { ...valores, seq: quantos })}</strong>
            </span>
            <span>
              Total: <strong>{quantos}</strong>
            </span>
          </p>
        )}
        {qtd === 0 && <p className="dica texto-alerta">Nenhuma peça aprovada: o registro é gravado como REPROVADO.</p>}
      </div>
    </>
  );
}

function FormEmbalagem({ dados, campos, definir }: PropsForm) {
  return (
    <>
      <CampoTexto id="f-tipo-emb" rotulo="Tipo de embalagem" chave="tipo_emb" campos={campos} definir={definir} />
      <CampoTexto id="f-qtd-emb" rotulo="Peças embaladas" chave="qtd_emb" numero obrigatorio campos={campos} definir={definir} />
      <CampoTexto id="f-parafusos" rotulo={`${dados.padroes.parafusos} incluídos`} chave="parafusos" numero obrigatorio campos={campos} definir={definir} />
      <CampoTexto id="f-volumes" rotulo="Volumes" chave="volumes" campos={campos} definir={definir} />
    </>
  );
}

// ---------------------------------------------------------------- o formulário

const FORMULARIOS: Record<string, (props: PropsForm) => ReactNode> = {
  quimica: FormQuimica,
  tt: FormTT,
  dureza: FormDureza,
  dim: FormDim,
  lp: FormLP,
  simples: FormSimples,
  fosfato: FormFosfato,
  visual: FormVisual,
  embalagem: FormEmbalagem,
};

export function FormularioDetalhado({ dados, aoGravar }: { dados: PaginaEtapaDados; aoGravar: () => void }) {
  const avisos = useAvisos();
  const [campos, setCampos] = useState<Campos>(() => camposIniciais(dados));
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const definir = (chave: string, valor: Campos[string]) => setCampos((atual) => ({ ...atual, [chave]: valor }));
  const formulario = dados.etapa.formulario;
  const laboratorio = formulario === 'lab';

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    setEnviando(true);
    setErro(null);
    try {
      const corpo = { ...campos } as Record<string, unknown>;
      if (formulario === 'quimica') {
        const elementos = (campos.elementos as Record<string, Linha>) ?? {};
        corpo.elementos = Object.entries(elementos).map(([elemento, v]) => ({ elemento, valor: v.valor ?? '', min: v.min ?? '', max: v.max ?? '' }));
      }
      const resposta = await api<RespostaRegistro>(`/lotes/${dados.lote.id}/etapas/${dados.etapa.chave}/registros`, {
        metodo: 'POST',
        corpo: { sub: dados.sub, campos: corpo },
      });
      const status = resposta.status.toUpperCase();
      if (resposta.status === 'aprovado') avisos.sucesso(`Registro salvo: ${status}.${resposta.nc_encerrada ? ` NC ${resposta.nc_encerrada} encerrada (retrabalho aprovado).` : ''}`);
      else if (resposta.status === 'reprovado') avisos.erro(`Registro salvo: ${status}.${resposta.nc ? ` Não conformidade ${resposta.nc.numero} aberta automaticamente.` : ''}`);
      else avisos.info(`Registro salvo: ${status}. ${resposta.aviso ?? 'Falta validar os resultados do laboratório.'}`);
      setCampos(camposIniciais(dados));
      aoGravar();
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  let corpo: ReactNode;
  if (laboratorio) {
    corpo =
      dados.sub === 'tracao' ? (
        <FormTracao dados={dados} campos={campos} definir={definir} />
      ) : (
        <FormCharpy dados={dados} campos={campos} definir={definir} />
      );
  } else {
    const Componente = FORMULARIOS[formulario];
    corpo = Componente ? <Componente dados={dados} campos={campos} definir={definir} /> : null;
  }

  return (
    <form className="form-grade lt-form" onSubmit={enviar} onKeyDown={enterVaiParaProximo} noValidate>
      {corpo}
      {laboratorio ? (
        <>
          <div className="col-2">
            <Marcacao id="f-validado" marcado={campos.validado === true} aoMudar={(v) => definir('validado', v)}>
              Resultados do laboratório conferidos e VALIDADOS
            </Marcacao>
            {campos.validado !== true && <p className="dica">Sem validação, o registro fica PENDENTE (não libera a etapa).</p>}
          </div>
          <CampoTexto id="f-validador" rotulo="Validado por" chave="validador" classe="col-2" campos={campos} definir={definir} />
        </>
      ) : (
        <Campo rotulo="Decisão" para="f-decisao" classe="col-2">
          <select id="f-decisao" value={texto(campos, 'decisao')} onChange={(e) => definir('decisao', e.target.value)}>
            <option value="aprovado">Aprovar (se dentro dos critérios)</option>
            <option value="reprovado">Reprovar manualmente</option>
          </select>
        </Campo>
      )}
      <Campo rotulo="Observações" para="f-obs" classe="col-4">
        <textarea id="f-obs" rows={2} value={texto(campos, 'obs')} onChange={(e) => definir('obs', e.target.value)} />
      </Campo>
      <p className="col-4 dica">
        Registrado por: <strong>{dados.padroes.usuario}</strong> (usuário logado). Reprovação abre uma não conformidade automaticamente.
      </p>
      {erro && (
        <p className="col-4 erro-formulario" role="alert">
          {erro}
        </p>
      )}
      <div className="col-4 acoes-form acoes">
        <button type="submit" className="botao botao-primario" disabled={enviando}>
          {enviando ? 'Gravando…' : 'Salvar registro'}
        </button>
        <button type="button" className="botao botao-fantasma" disabled={enviando} onClick={() => setCampos(camposIniciais(dados))}>
          Limpar
        </button>
      </div>
    </form>
  );
}
