/* Verificação dimensional automática de um relatório RIP-33A (PDF enviado agora ou anexo de um lote: ?anexo=ID). */
import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { EnvioArquivos } from '../../componentes/EnvioArquivos';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api, enviarArquivos, ErroApi, mensagemDeErro } from '../../lib/api';
import { inteiro, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import type { Caracteristica, ResultadoAnalise, RespostaVerificacao } from './tipos';
import './dimensional.css';

const AMOSTRAS = 10;

function numero(valor: number | null | undefined, casas?: number): string {
  if (valor === null || valor === undefined) return TRACO;
  return (casas === undefined ? String(valor) : valor.toFixed(casas)).replace('.', ',');
}

function faixa(car: Caracteristica): string {
  return car.faixa ? `${numero(car.faixa[0], 2)} a ${numero(car.faixa[1], 2)}` : TRACO;
}

// ---------------------------------------------------------------- resultado

function CarFora({ car }: { car: Caracteristica }) {
  return (
    <li className="dim-fora">
      <p>
        <strong>
          CAR {car.car} — {car.requisito || TRACO}
        </strong>
      </p>
      <p className="dim-meta">
        Especificação: {car.espec || TRACO} · Tolerância: {car.tol || TRACO} · Faixa aceitável: {faixa(car)}
      </p>
      <p className="dim-valores-fora">
        {car.fora.map((f) => `${f.amostra} = ${numero(f.valor)}`).join(', ')}
      </p>
      {car.minimo !== null && (
        <p className="dim-meta">
          Amostras medidas: de {numero(car.minimo)} a {numero(car.maximo)}
        </p>
      )}
    </li>
  );
}

function TodasAsCaracteristicas({ cars }: { cars: Caracteristica[] }) {
  return (
    <details className="recolhivel">
      <summary>Ver todas as características ({inteiro(cars.length)})</summary>
      <div className="tabela-rolagem">
        <table className="tabela dim-tabela">
          <caption className="so-leitor">Características lidas do relatório</caption>
          <thead>
            <tr>
              <th scope="col">CAR</th>
              <th scope="col">Requisito</th>
              <th scope="col">Especificação</th>
              <th scope="col">Tolerância</th>
              <th scope="col">Faixa aceitável</th>
              {Array.from({ length: AMOSTRAS }, (_, i) => (
                <th key={i} scope="col" className="num">
                  P{i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cars.map((car) => {
              const fora = new Set(car.fora.map((f) => f.amostra));
              return (
                <tr key={car.car} className={car.fora.length ? 'dim-linha-fora' : car.aviso ? 'dim-linha-aviso' : undefined}>
                  <td className="mono">{car.car}</td>
                  <td>{car.requisito || TRACO}</td>
                  <td>{car.espec || TRACO}</td>
                  <td>{car.tol || TRACO}</td>
                  <td className="mono">{car.aviso ? 'revisar à mão' : faixa(car)}</td>
                  {Array.from({ length: AMOSTRAS }, (_, i) => {
                    const valor = car.amostras[i];
                    const ruim = fora.has(`P${i + 1}`);
                    return (
                      <td key={i} className={`num ${ruim ? 'dim-celula-fora' : ''}`}>
                        {valor === 'ok' ? 'OK' : valor === null || valor === undefined ? '' : numero(valor)}
                        {ruim && <span className="so-leitor"> (fora da tolerância)</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Resultado({ nome, resultado }: { nome: string; resultado: ResultadoAnalise }) {
  return (
    <section className="cartao" aria-labelledby="dim-titulo-resultado">
      <h2 id="dim-titulo-resultado">
        Resultado <span className="sub-linha">— {nome}</span>
      </h2>
      {!resultado.ok ? (
        <Faixa tipo="erro" papel="alert">
          {resultado.erro}
        </Faixa>
      ) : (
        <>
          <div className="cartoes dim-numeros">
            <div className="cartao-numero">
              <span className="cartao-rotulo">Características (CAR)</span>
              <span className="cartao-valor">{inteiro(resultado.total_cars)}</span>
            </div>
            <div className={`cartao-numero ${resultado.cars_fora.length ? 'dim-numero-fora' : 'dim-numero-ok'}`}>
              <span className="cartao-rotulo">Fora da tolerância</span>
              <span className="cartao-valor">{inteiro(resultado.cars_fora.length)}</span>
            </div>
            {resultado.cars_aviso.length > 0 && (
              <div className="cartao-numero dim-numero-aviso">
                <span className="cartao-rotulo">Não verificado automaticamente</span>
                <span className="cartao-valor">{inteiro(resultado.cars_aviso.length)}</span>
              </div>
            )}
          </div>

          {resultado.cars_fora.length > 0 ? (
            <div>
              <h3 className="texto-erro">Cotas fora da tolerância</h3>
              <ul className="dim-lista">
                {resultado.cars_fora.map((car) => (
                  <CarFora key={car.car} car={car} />
                ))}
              </ul>
            </div>
          ) : (
            <Faixa tipo="sucesso">Nenhuma cota fora da tolerância encontrada.</Faixa>
          )}

          {resultado.cars_aviso.length > 0 && (
            <div>
              <h3>Não foi possível calcular automaticamente</h3>
              <p className="dica">Revise à mão: o formato da especificação ou da tolerância não foi reconhecido pelo verificador.</p>
              <ul className="dim-avisos">
                {resultado.cars_aviso.map((car) => (
                  <li key={car.car}>
                    CAR {car.car} — {car.requisito || TRACO} ({car.espec || TRACO} / {car.tol || TRACO})
                  </li>
                ))}
              </ul>
            </div>
          )}

          {Object.keys(resultado.rodape).length > 0 && (
            <div>
              <h3>Rodapé do relatório</h3>
              <dl className="ficha ficha-linha">
                <div>
                  <dt>Situação</dt>
                  <dd>{resultado.rodape.status || 'não identificada'}</dd>
                </div>
                <div>
                  <dt>Inspecionado por</dt>
                  <dd>
                    {resultado.rodape.inspecionado_por || TRACO}
                    <span className="sub-linha"> em {resultado.rodape.data_inspecao || TRACO}</span>
                  </dd>
                </div>
                <div>
                  <dt>Aprovado por</dt>
                  <dd>
                    {resultado.rodape.aprovado_por || TRACO}
                    <span className="sub-linha"> em {resultado.rodape.data_aprovacao || TRACO}</span>
                  </dd>
                </div>
              </dl>
            </div>
          )}

          <TodasAsCaracteristicas cars={resultado.cars} />
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- entradas

function DoAnexo({ anexoId }: { anexoId: string }) {
  const valido = /^\d+$/.test(anexoId);
  const carga = useCarga<RespostaVerificacao>(
    (sinal) => (valido ? api(`/dimensional/anexos/${anexoId}`, { sinal }) : Promise.reject(new ErroApi(404, 'Anexo não encontrado.'))),
    [anexoId],
  );
  const dados = carga.dados;
  const voltar =
    dados?.lote && dados.anexo
      ? dados.anexo.etapa && dados.anexo.etapa !== 'outros'
        ? `/lotes/${dados.lote.id}/etapas/${dados.anexo.etapa}${dados.anexo.sub ? `?sub=${encodeURIComponent(dados.anexo.sub)}` : ''}`
        : `/lotes/${dados.lote.id}`
      : null;

  if (carga.erro) return <ErroCarga mensagem={carga.erro} aoTentar={valido ? carga.recarregar : undefined} />;
  if (!dados) return <Carregando texto="Lendo o relatório…" />;
  return (
    <>
      {dados.lote && (
        <div className="acoes">
          {voltar && (
            <Link to={voltar} className="botao">
              ← Voltar ao lote
            </Link>
          )}
          <span>
            Lote <span className="mono">{dados.lote.numero}</span> · OP <span className="mono">{dados.lote.op || TRACO}</span>{' '}
            <SeloTipo tipo={dados.lote.tipo} />
          </span>
        </div>
      )}
      <Resultado nome={dados.nome} resultado={dados.resultado} />
    </>
  );
}

function PorEnvio() {
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resposta, setResposta] = useState<RespostaVerificacao | null>(null);

  async function analisar(evento: FormEvent) {
    evento.preventDefault();
    if (arquivos.length === 0) {
      setErro('Selecione um arquivo PDF.');
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      setResposta(await enviarArquivos<RespostaVerificacao>('/dimensional/verificar', { arquivo: arquivos[0] }));
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  if (resposta) {
    return (
      <>
        <Resultado nome={resposta.nome} resultado={resposta.resultado} />
        <div className="acoes">
          <button
            type="button"
            className="botao"
            onClick={() => {
              setResposta(null);
              setArquivos([]);
            }}
          >
            Verificar outro arquivo
          </button>
        </div>
      </>
    );
  }

  return (
    <form className="cartao form-coluna" onSubmit={analisar} noValidate>
      <EnvioArquivos
        arquivos={arquivos}
        aoMudar={setArquivos}
        aceita=".pdf"
        multiplos={false}
        rotulo="Arquivo PDF do relatório"
        dica="PDF gerado no computador (não escaneado), até 25 MB. O arquivo só é lido: não fica guardado no sistema."
        desabilitado={enviando}
      />
      {erro && (
        <p className="erro-formulario" role="alert">
          {erro}
        </p>
      )}
      <div className="acoes acoes-form">
        <button type="submit" className="botao botao-primario" disabled={enviando || arquivos.length === 0}>
          {enviando ? 'Analisando…' : 'Analisar relatório'}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- tela

export function VerificarDimensional() {
  const [parametros, setParametros] = useSearchParams();
  const anexo = parametros.get('anexo');

  return (
    <>
      <Cabecalho
        titulo="Verificar relatório dimensional (RIP-33A)"
        apoio="Analisa um Registro de Inspeção Final - Relatório Dimensional e aponta as cotas (CAR) fora da tolerância, comparando a especificação e a tolerância com cada amostra P1 a P10. Funciona com PDF gerado no computador (não com PDF escaneado ou foto)."
      >
        {anexo && (
          <button type="button" className="botao" onClick={() => setParametros({})}>
            Verificar outro arquivo
          </button>
        )}
      </Cabecalho>
      <div className="pilha">{anexo ? <DoAnexo key={anexo} anexoId={anexo} /> : <PorEnvio />}</div>
    </>
  );
}
