import { useMemo } from 'react';
import { Campo } from '../../componentes/Campo';
import { Cabecalho } from '../../componentes/Estados';
import type { Coluna } from '../../componentes/Tabela';
import { dataCurta, TRACO } from '../../lib/formato';
import { useSessao } from '../../lib/sessao';
import { CadastroSimples } from './CadastroSimples';
import type { Equipamento } from './tipos';

interface Formulario {
  codigo: string;
  descricao: string;
  setor: string;
  marca: string;
  data_calibracao: string;
  validade_calibracao: string;
  certificado: string;
  empresa_calibracao: string;
}

function Validade({ e }: { e: Equipamento }) {
  if (!e.validade_calibracao) return <>{TRACO}</>;
  return (
    <span className="cad-validade">
      {dataCurta(e.validade_calibracao)}
      {e.vencido && <strong className="texto-erro">⚠ vencida</strong>}
      {e.vence_logo && (
        <span className="texto-alerta">{e.dias_para_vencer === 0 ? 'vence hoje' : `vence em ${e.dias_para_vencer} dia(s)`}</span>
      )}
    </span>
  );
}

export function Equipamentos() {
  const { pode } = useSessao();

  const colunas = useMemo<Coluna<Equipamento>[]>(
    () => [
      { chave: 'codigo', titulo: 'Código', mono: true, valor: (e) => e.codigo, celula: (e) => <strong>{e.codigo}</strong> },
      { chave: 'descricao', titulo: 'Descrição', valor: (e) => e.descricao },
      { chave: 'setor', titulo: 'Setor', valor: (e) => e.setor, celula: (e) => e.setor || TRACO },
      { chave: 'marca', titulo: 'Marca', valor: (e) => e.marca, celula: (e) => e.marca || TRACO },
      { chave: 'calibrado', titulo: 'Calibrado em', valor: (e) => e.data_calibracao, celula: (e) => dataCurta(e.data_calibracao) },
      { chave: 'validade', titulo: 'Validade', valor: (e) => e.validade_calibracao, celula: (e) => <Validade e={e} /> },
      { chave: 'certificado', titulo: 'Certificado', mono: true, valor: (e) => e.certificado, celula: (e) => e.certificado || TRACO },
      { chave: 'empresa', titulo: 'Empresa calibração', valor: (e) => e.empresa_calibracao, celula: (e) => e.empresa_calibracao || TRACO },
    ],
    [],
  );

  return (
    <>
      <Cabecalho
        titulo="Equipamentos"
        apoio="Fornos, durômetros e demais equipamentos usados nos ensaios, com marca, certificado e validade da calibração. O que estiver ativo aqui aparece para escolher nos relatórios de Dureza e Tratamento Térmico."
      />
      <CadastroSimples<Equipamento, Formulario>
        rota="/equipamentos"
        nome="equipamento"
        podeEditar={pode.cadastros}
        colunas={colunas}
        textoBusca={(e) => `${e.codigo} ${e.descricao} ${e.setor} ${e.marca} ${e.certificado} ${e.empresa_calibracao}`}
        ordemInicial={{ chave: 'codigo', direcao: 'asc' }}
        classeLinha={(e) => (e.vencido && e.ativo ? 'cad-linha-vencida' : undefined)}
        efeitoInativar="O equipamento deixa de aparecer para escolher nos relatórios."
        filtro={{
          rotulo: 'Calibração',
          opcoes: [
            { valor: 'vencida', rotulo: 'Vencida' },
            { valor: 'logo', rotulo: 'Vence em até 30 dias' },
            { valor: 'em_dia', rotulo: 'Em dia' },
            { valor: 'sem', rotulo: 'Sem validade informada' },
          ],
          passa: (e, valor) =>
            (valor === 'vencida' && e.vencido) ||
            (valor === 'logo' && e.vence_logo) ||
            (valor === 'em_dia' && !!e.validade_calibracao && !e.vencido && !e.vence_logo) ||
            (valor === 'sem' && !e.validade_calibracao),
        }}
        novo={() => ({ codigo: '', descricao: '', setor: '', marca: '', data_calibracao: '', validade_calibracao: '', certificado: '', empresa_calibracao: '' })}
        editar={(e) => ({
          codigo: e.codigo,
          descricao: e.descricao,
          setor: e.setor,
          marca: e.marca,
          data_calibracao: e.data_calibracao ?? '',
          validade_calibracao: e.validade_calibracao ?? '',
          certificado: e.certificado,
          empresa_calibracao: e.empresa_calibracao,
        })}
        envio={(f) => ({
          codigo: f.codigo.trim(),
          descricao: f.descricao.trim(),
          setor: f.setor.trim(),
          marca: f.marca.trim(),
          data_calibracao: f.data_calibracao || null,
          validade_calibracao: f.validade_calibracao || null,
          certificado: f.certificado.trim(),
          empresa_calibracao: f.empresa_calibracao.trim(),
        })}
        campos={(f, mudar, _item, todos) => {
          const setores = [...new Set(todos.map((e) => e.setor).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'pt-BR'));
          return (
            <div className="form-grade">
              <Campo rotulo="Código" para="eq-codigo" obrigatorio classe="col-2">
                <input id="eq-codigo" type="text" className="mono" required maxLength={30} placeholder="Ex.: DUR-900001" value={f.codigo}
                  onChange={(e) => mudar({ codigo: e.target.value })} />
              </Campo>
              <Campo rotulo="Setor" para="eq-setor" classe="col-2">
                <input id="eq-setor" type="text" list="eq-lista-setores" maxLength={80} placeholder="Ex.: Qualidade" value={f.setor}
                  onChange={(e) => mudar({ setor: e.target.value })} />
                <datalist id="eq-lista-setores">
                  {setores.map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
              </Campo>
              <Campo rotulo="Descrição do equipamento" para="eq-descricao" obrigatorio classe="col-4">
                <input id="eq-descricao" type="text" required maxLength={200} placeholder="Ex.: Forno de têmpera - atmosfera controlada"
                  value={f.descricao} onChange={(e) => mudar({ descricao: e.target.value })} />
              </Campo>
              <Campo rotulo="Marca" para="eq-marca">
                <input id="eq-marca" type="text" maxLength={80} value={f.marca} onChange={(e) => mudar({ marca: e.target.value })} />
              </Campo>
              <Campo rotulo="Nº do certificado" para="eq-certificado">
                <input id="eq-certificado" type="text" className="mono" maxLength={80} value={f.certificado}
                  onChange={(e) => mudar({ certificado: e.target.value })} />
              </Campo>
              <Campo rotulo="Empresa de calibração" para="eq-empresa" classe="col-2">
                <input id="eq-empresa" type="text" maxLength={160} value={f.empresa_calibracao}
                  onChange={(e) => mudar({ empresa_calibracao: e.target.value })} />
              </Campo>
              <Campo rotulo="Data da calibração" para="eq-data" classe="col-2">
                <input id="eq-data" type="date" value={f.data_calibracao} onChange={(e) => mudar({ data_calibracao: e.target.value })} />
              </Campo>
              <Campo rotulo="Validade da calibração" para="eq-validade" classe="col-2" dica="A linha fica vermelha quando a calibração vence.">
                <input id="eq-validade" type="date" min={f.data_calibracao || undefined} value={f.validade_calibracao}
                  onChange={(e) => mudar({ validade_calibracao: e.target.value })} />
              </Campo>
            </div>
          );
        }}
      />
    </>
  );
}
