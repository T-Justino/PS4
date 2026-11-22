# Automação do catálogo e atualização no SSPI

## Automação (GitHub Actions; sem servidor, sem banco, sem VPS)

`.github/workflows/catalogo.yml`: a cada 6 h (e sob demanda em *Actions → catalogo → Run workflow*) roda os testes, depois `ps4store run`, e **só commita se o `.gssource`, o catálogo canônico ou o estado mudaram**.

- **Atualiza somente quando necessário:** a versão da fonte (`1.0.N`) só sobe se o conteúdo muda; sem mudança, o artefato é byte a byte o mesmo.
- **Preserva o último catálogo válido:** sem entradas publicáveis, ou com **fonte crítica fora do ar** (`critical`, padrão `true`), o `.gssource` anterior é mantido e o job fica vermelho (código de saída 3). PKG-Zone e Apollo estão `critical: false` (só descoberta/relatório).
- **Registra resultados e erros:** relatório completo no *Summary* do job; estado em `data/state/`.
- **Carga no PKG-Zone:** o estado commitado guarda a verificação por 30 dias (`recheck_hours: 720`); só itens novos são sondados. Mesmo assim, defina antes se quer manter o PKG-Zone no agendado (permissão pendente, `docs/PKGZONE_PEDIDO.md`).
- **Não executado ainda:** o workflow nunca rodou no GitHub (só aqui, com o mesmo comando). Primeira execução: *Run workflow*. O token do Actions dá acesso à API de repositórios de terceiros, o que esta sessão não tinha (conector Releases/Apollo).
- **Hospedagem:** o próprio repositório (`raw.githubusercontent.com`, download de 6,6 MB comprovado no seu console no T8). Link estável do catálogo:
  `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/dist/auto/ps4storebr-auto.gssource`

## Como o SSPI atualiza fontes (lido no código/documentação públicos; **não provado no console**)

| Forma de instalar a fonte | Atualização |
|---|---|
| **Link** (página do celular do SSPI, aba *Sources*; "URL do próprio arquivo", PS4 baixa, verifica e instala) | **Não é automática.** Reenviar o mesmo link instala a revisão nova **se `source.version` for maior** (mesmo ID de fonte; o estado ligado/desligado é mantido). Mesma versão com conteúdo diferente é recusada |
| **USB** | igual: reimportar o arquivo com versão maior |
| Diretório de fontes da comunidade | o SSPI acompanha sozinho pelo ID permanente: **não é o nosso caso** |
| Engine `embedded-catalog-refresh-v1` | buscaria conteúdo novo sozinho, mas o engine estático proíbe origem de rede; **não usado nem testado** |

**Alternativa mais simples (a recomendada):** o robô mantém o link estável acima; quando houver versão nova, abra a página do celular e cole o **mesmo link** de novo (ou use USB). Um toque, sem PC ligado.
O T8b, Parte 2, testa exatamente isso.

**Limite do ID `CUSA`:** o SSPI só substitui apps antigos automaticamente para homebrew (ID **não** `CUSA`); para IDs `CUSA` (como o nosso) é preciso usar *Reinstall* ou excluir o app antes. Isso vem do código público; não testado.
