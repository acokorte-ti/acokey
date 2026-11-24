# Integração com o ERP Mega — mapeamento do AçoKey Q

Mapeado em 24/11/2026 a partir do system-lab, com o usuário `acokey_ro` (somente leitura). OP, item, cliente e
pedido seguem o mapeamento já validado do EstoqueACK (`estoqueack/docs/integracao_mega.md`). Esquema `ACOKORTE`,
filial de Itu `FIL_IN_CODIGO = 3`.

## De onde vem cada dado das ordens de produção (antiga planilha de OPs)

| Dado | Mega | Validação (amostra da planilha) |
|---|---|---|
| OP | `PRO_ORDENS.ORD_IN_CODIGO` | 8/8 encontradas |
| Item (CODITEM) | `PRO_ORDENS.PRO_IN_CODIGO` | 8/8 |
| Descrição | `EST_PRODUTOS.PRO_ST_DESCRICAO` | — |
| Classificação PIN/BOX/ARK | calculada pela descrição (não vem do Mega) | — |
| Quantidade da OP | `PRO_ORDENS.ORD_RE_QTDE_ORDEM` | 6/8: em 2 OPs a planilha tem a quantidade do lote, menor que a da OP (confirmar com a Qualidade) |
| Situação da OP | `PRO_ORDENS.ORD_ST_SITUACAO` (`AB` aberta, `EN` encerrada, `CA` cancelada...) | — |
| Pedido (PIV) | `PRO_ORIGEM` (`ORI_CH_TIPOORIGEM = 'D'`) → `VEN_PEDIDOVENDA.PED_IN_CODIGO`; sem origem, `PRO_ORDENS.ORD_ST_ALTERNATIVO` | 6/6 |
| Cliente | `VEN_PEDIDOVENDA` (`CLI_*`) → `GLO_AGENTES.AGN_ST_FANTASIA` | — |
| PO (pedido do cliente) | `VEN_ITEMPEDIDOVENDA.ITP_ST_PEDIDOCLIENTE` (também `VEN_ITEMNOTAFISCAL.ITN_ST_PEDIDOCLIENTE`) | presente nas 6 (a planilha não tinha) |
| NF de saída e data | `VEN_ITEMPEDI_VEN_ITEMNOT` (vínculo item do pedido ↔ item da nota) → `VEN_NOTAFISCAL.NOT_IN_NUMERO`, `NOT_DT_EMISSAO` | 6/6 NF e data |
| Quantidade faturada | por nota: `VEN_ITEMPEDI_VEN_ITEMNOT.IPN_RE_QUANTIDADE`; total do item do pedido: `VEN_ITEMPEDIDOVENDA.ITP_RE_QTDEFATURADA` | 5/6 com o total do pedido; usar a do vínculo |
| Nota cancelada | `VEN_NOTAFISCAL.NOT_CH_SITUACAO`, `NOT_DT_CANCELAMENTO` | — |
| "Projeto" da planilha | **não é do Mega**: é o código da especificação técnica do cliente (parâmetro `especificacao_codigo`); os campos `PROJ_*` do Mega estão vazios | — |

### Chaves do vínculo pedido ↔ nota (`VEN_ITEMPEDI_VEN_ITEMNOT`)

- Lado do pedido: `PE_ORG_TAB_IN_CODIGO, PE_ORG_PAD_IN_CODIGO, PE_ORG_IN_CODIGO, PE_ORG_TAU_ST_CODIGO, PE_SER_ST_CODIGO,
  PE_PED_IN_CODIGO, PE_ITP_IN_SEQUENCIA` (item do pedido em `VEN_ITEMPEDIDOVENDA`).
- Lado da nota: `NF_ORG_TAB_IN_CODIGO, NF_ORG_PAD_IN_CODIGO, NF_ORG_IN_CODIGO, NF_ORG_TAU_ST_CODIGO, NF_SEQ_TAB_IN_CODIGO,
  NF_SEQ_IN_CODIGO, NF_NOT_IN_CODIGO, NF_ITN_IN_SEQUENCIA` (item da nota em `VEN_ITEMNOTAFISCAL`, nota em `VEN_NOTAFISCAL`).
- Quantidade daquele item do pedido naquela nota: `IPN_RE_QUANTIDADE`.

## Matéria-prima (a mapear)

NF de entrada e fornecedor: `EST_RECEBIMENTO` / `EST_ITENSRECEB` + `GLO_AGENTES` (mapeados nos Indicadores de
Manutenção). Falta confirmar como a entrada das peças fundidas aparece (produto, quantidade) e se a corrida existe
no Mega (provavelmente só no certificado).

## Permissões

Bloco C de `scripts/mega/01_criar_usuario_leitura.sql`. Durante o mapeamento o usuário tem `SELECT ANY TABLE`
(bloco B); depois que a sincronização estiver pronta, rodar o bloco D (revoga).
