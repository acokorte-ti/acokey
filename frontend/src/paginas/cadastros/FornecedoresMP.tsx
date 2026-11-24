import { useMemo } from 'react';
import { Campo } from '../../componentes/Campo';
import { Cabecalho } from '../../componentes/Estados';
import type { Coluna } from '../../componentes/Tabela';
import { api } from '../../lib/api';
import { TRACO } from '../../lib/formato';
import { useSessao } from '../../lib/sessao';
import { useCarga } from '../../lib/useCarga';
import { CadastroSimples } from './CadastroSimples';
import type { FornecedorMP, ListasFixas } from './tipos';

interface Formulario {
  codigo: string;
  razao_social: string;
  materiais: string;
  contato: string;
  observacoes: string;
}

export function FornecedoresMP() {
  const { pode } = useSessao();
  const listas = useCarga<ListasFixas>((sinal) => api('/cadastros/listas', { sinal }), []);
  const materiais = listas.dados?.materiais_mp ?? [];

  const colunas = useMemo<Coluna<FornecedorMP>[]>(
    () => [
      { chave: 'codigo', titulo: 'Código', mono: true, valor: (f) => f.codigo, celula: (f) => <strong>{f.codigo}</strong> },
      { chave: 'razao', titulo: 'Razão social', valor: (f) => f.razao_social },
      { chave: 'materiais', titulo: 'Materiais', valor: (f) => f.materiais, celula: (f) => f.materiais || TRACO },
      { chave: 'contato', titulo: 'Contato', valor: (f) => f.contato, celula: (f) => f.contato || TRACO },
      { chave: 'obs', titulo: 'Observações', valor: (f) => f.observacoes, celula: (f) => f.observacoes || TRACO },
    ],
    [],
  );

  return (
    <>
      <Cabecalho
        titulo="Fornecedores de matéria-prima"
        apoio="Siderúrgicas e distribuidores que fornecem SC4330, H11 Modified, TENAX300IM e demais aços para as chavetas."
      />
      <CadastroSimples<FornecedorMP, Formulario>
        rota="/fornecedores-mp"
        nome="fornecedor"
        podeEditar={pode.cadastros}
        colunas={colunas}
        textoBusca={(f) => `${f.codigo} ${f.razao_social} ${f.materiais} ${f.contato}`}
        ordemInicial={{ chave: 'codigo', direcao: 'asc' }}
        efeitoInativar="O fornecedor deixa de aparecer como sugestão na matéria-prima e na etapa Receb. MP."
        novo={() => ({ codigo: '', razao_social: '', materiais: '', contato: '', observacoes: '' })}
        editar={(f) => ({ codigo: f.codigo, razao_social: f.razao_social, materiais: f.materiais, contato: f.contato, observacoes: f.observacoes })}
        envio={(f) => ({
          codigo: f.codigo.trim().toUpperCase(),
          razao_social: f.razao_social.trim(),
          materiais: f.materiais.trim(),
          contato: f.contato.trim(),
          observacoes: f.observacoes.trim(),
        })}
        campos={(f, mudar) => (
          <div className="form-grade">
            <Campo rotulo="Código" para="fo-codigo" obrigatorio classe="col-2" dica="Sempre em maiúsculas.">
              <input id="fo-codigo" type="text" className="mono cad-maiusculas" required maxLength={30} placeholder="Ex.: ACOS-EXEMPLO"
                value={f.codigo} onChange={(e) => mudar({ codigo: e.target.value.toUpperCase() })} />
            </Campo>
            <Campo rotulo="Materiais fornecidos" para="fo-materiais" classe="col-2" dica="Separe por ponto e vírgula.">
              <input id="fo-materiais" type="text" list="fo-lista-materiais" maxLength={200} placeholder="SC4330; H11 Modified"
                value={f.materiais} onChange={(e) => mudar({ materiais: e.target.value })} />
              <datalist id="fo-lista-materiais">
                {materiais.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </Campo>
            <Campo rotulo="Razão social" para="fo-razao" obrigatorio classe="col-4">
              <input id="fo-razao" type="text" required maxLength={160} placeholder="Ex.: Aços Exemplo S.A." value={f.razao_social}
                onChange={(e) => mudar({ razao_social: e.target.value })} />
            </Campo>
            <Campo rotulo="Contato" para="fo-contato" classe="col-2">
              <input id="fo-contato" type="text" maxLength={200} placeholder="Telefone, e-mail, responsável…" value={f.contato}
                onChange={(e) => mudar({ contato: e.target.value })} />
            </Campo>
            <Campo rotulo="Observações" para="fo-obs" classe="col-2">
              <input id="fo-obs" type="text" maxLength={2000} value={f.observacoes} onChange={(e) => mudar({ observacoes: e.target.value })} />
            </Campo>
          </div>
        )}
      />
    </>
  );
}
