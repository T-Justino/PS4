# T9 — Instalação a partir do catálogo GERADO PELO ROBÔ (depois do T8)

Pré-requisito: o **T8** (`docs/TESTE_T8.md`) ter baixado e instalado o PKG pelo `raw.githubusercontent.com`. Se o T8 falhou no download por TLS, **não faça o T9**: veja a alternativa de hospedagem em `docs/GATE3.md`.

| Item | Valor |
|---|---|
| Fonte | `dist/auto/ps4storebr-auto.gssource` (v1.0.1), gerada por `ps4store run` |
| Como o PKG foi achado | API Contents do GitHub lista `dist/t8/` do repositório autorizado → link `raw` → leitura do PKG. **Nenhuma URL foi cadastrada à mão.** |
| contentSha256 | `b364e4a8d93190291a2c55a9ddb31c15172f1e6ab4e5ee32194c1861fac5d875` |
| Diferença para a fonte do T8 | linhas de pacote com `size` e `version` preenchidos (lidos do servidor e do PKG) |

Se o app do T8 **ainda está instalado**, apague só ele antes (Opções → Excluir), para o teste ser um ciclo completo. Não mexa em outros apps.

1. Importe `ps4storebr-auto.gssource` (USB → *Install source from USB*). Remova antes as fontes de teste anteriores.
2. Pesquise `ps4 store br test` ou `CUSA95417`. Abra os detalhes.
3. Baixe e instale. 4. Abra o app: deve mostrar "INSTALACAO OK".

```text
T9: fonte importada [sim/não+erro] | achado [sim/não] | download [concluído/erro: ___] | PKG [aceito/recusado+msg] | instalado e abre [sim/não]
```

Se instalar e abrir: está comprovado **um pacote autorizado, descoberto automaticamente, publicado no catálogo e instalado**, para este app e esta versão do SSPI.
Não comprova outros pacotes, hosts, updates ou DLC.
