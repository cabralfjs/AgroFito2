# AgroFito — pacote final para publicar em agrofito.org

## Ficheiros incluídos e o que cada um faz

| Ficheiro | O que é | Ação |
|---|---|---|
| `.nojekyll` | Ficheiro vazio. Desliga o processamento Jekyll do GitHub Pages, que por defeito ignora ficheiros/pastas começadas por `_` (como `lmr/_index.json`). **Sem isto, o LMR não funciona.** | Copiar para a raiz. |
| `usos.html` | A página de usos autorizados, com: (1) a secção de LMR no painel de "Detalhe"; (2) a correção da barra de filtros a desalinhar as barras de baixo. | **Substitui** o `usos.html` atual. |
| `produtos.html` | A ficha de produtos, com a mesma correção da barra de filtros aplicada (a barra de legenda deixa de desalinhar). Não tem alterações de LMR — o LMR só existe em `usos.html`. | **Substitui** o `produtos.html` atual. |
| `update_lmr.py` | Script que descarrega os dados da Comissão Europeia e gera a pasta `lmr/`. | Copiar para a raiz. Não precisas de correr manualmente — o *workflow* trata disso. |
| `culturas_crosswalk.json` | Correspondência cultura SIFITO → código de produto da UE (142 culturas mapeadas). | Copiar para a raiz. |
| `substancias_crosswalk.json` | Correspondência substância ativa SIFITO → identificador de resíduo da UE (261 substâncias mapeadas). | Copiar para a raiz. |
| `.github/workflows/update-lmr.yml` | *Workflow* do GitHub Actions que corre o script semanalmente (segundas-feiras) e publica a pasta `lmr/` automaticamente. | Copiar a pasta `.github/workflows/` inteira, mantendo esse caminho exato. |

## O que NÃO está neste pacote (nasce sozinho)

- **A pasta `lmr/`** — criada automaticamente pelo *workflow* na primeira execução depois deste `push`. Não a copies de nenhum sítio.

## O bug da barra de filtros — o que foi corrigido

A posição das barras coladas por baixo da barra de filtros (legenda, "Autorizações a Cancelar") é calculada uma vez, no arranque da página. Se depois disso a barra de filtros mudar de altura por qualquer razão — o botão "✕ Limpar" a aparecer, texto a ajustar, contadores a carregar e forçarem quebra de linha — essa medição inicial ficava desatualizada, e as barras de baixo ficavam mal posicionadas.

A correção passa a **observar a própria barra de filtros** (via `ResizeObserver`), recalculando a posição sempre que a sua altura muda de facto — não só quando a janela é redimensionada, que era o único caso já coberto antes. Aplicado da mesma forma em `usos.html` e `produtos.html`.

## Passo a passo para publicar

1. Copia todos os ficheiros deste pacote (incluindo `.nojekyll` e a pasta `.github/`) para a raiz do repositório de produção, substituindo o `usos.html` e o `produtos.html` existentes.
2. Faz *commit* e *push*.
3. Vai a **Actions** (github.com) → workflow **"Atualizar dados de LMR (UE)"** → **"Run workflow"**, para não esperares pela segunda-feira.
4. Confirma que a pasta `lmr/` apareceu no repositório.
5. Faz *hard refresh* (`Ctrl+Shift+R`) em `agrofito.org` e testa: (a) o LMR num "Detalhe" de uma cultura mapeada (ex.: Tomateiro, Macieira); (b) a barra de filtros em `usos.html` e `produtos.html`, confirmando que a legenda/estatísticas não desalinham quando o "Limpar" aparece.

## Culturas já mapeadas para LMR (142)

Cereais, vinha, olival, citrinos, pomóideas, prunóideas, principais
hortícolas, leguminosas, oleaginosas, frutos secos, pequenos frutos e
ervas aromáticas comuns. Fora deste conjunto, "Sem dados de LMR
disponíveis para esta cultura" é o comportamento esperado, não um erro.
