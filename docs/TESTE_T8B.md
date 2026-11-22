# T8b — teste no PS4 do PKG corrigido, do catálogo gerado pelo robô e da atualização

**Antes de tudo:** apague **só** o app defeituoso "PS4 Store BR Test" (Biblioteca → Opções → Excluir). Não toque em outros apps. Remova do SSPI as fontes de teste antigas (T4–T9).

| Parte | Arquivo | Conteúdo |
|---|---|---|
| 1 | `dist/t8b/ps4storebr-t8b-antes-v1.00.gssource` (fonte `1.0.2`) | gerado pelo robô: PKG corrigido **v1.00** |
| 2 | `dist/t8b/ps4storebr-t8b-depois-v1.01.gssource` (fonte `1.0.3`) | gerado pelo robô depois de a v1.01 aparecer na pasta; mesma fonte, versão maior |

## Parte 1 — ciclo completo (USB)
1. Copie o arquivo da Parte 1 para o pendrive → SSPI → *Install source from USB* → Install.
2. Pesquise `ps4 store br test` ou `CUSA95417` → detalhes (versão 1.00) → baixe (6,6 MB) → instale.
3. **Abra o app.** Esperado: tela verde "PS4 STORE BR TEST / INSTALACAO OK / VERSAO 1.00". Saia com o botão PS.

## Parte 2 — atualização da fonte e do app (só se a Parte 1 abriu)
1. **Atualizar a fonte** (a pergunta do mecanismo): importe o arquivo da Parte 2 **por USB** ou, melhor, **por link** (mais próximo do uso real): na página do celular do SSPI (aba *Sources*) cole
   `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/dist/auto/ps4storebr-auto.gssource` → *Install source on PS4*.
   Anote: aceitou como versão nova? A lista de fontes mostra `1.0.3`? O item agora é v1.01?
2. Para instalar a v1.01 sobre a v1.00: o ID é `CUSA` (o SSPI trata como jogo, sem substituição automática). Use *Reinstall* do SSPI se existir, ou exclua o app e instale de novo.
3. Abra: deve mostrar "VERSAO 1.01".

## Registro (copie e preencha)
```text
Parte 1: fonte [ok/erro:__] | achado [sim/não] | download [ok/erro:__] | instalou [sim/não+msg] | ABRE [sim/não+msg]
Parte 2: atualização da fonte [USB/link] aceita [sim/não+msg] | versão da fonte exibida [__] | v1.01 instalada [sim/não+msg] | abre mostrando 1.01 [sim/não]
```

| Resultado | Conclusão |
|---|---|
| Parte 1 abre | Correção confirmada; ciclo descoberta→catálogo→instalação→abertura comprovado **para este pacote próprio** |
| Parte 1 instala mas não abre | A causa não era só `sce_module`; investigar `eboot`/ID `CUSA` (ver `DIAGNOSTICO_T8.md`) |
| Parte 2 aceita | Atualização de fonte por reimportação (versão maior) comprovada |
| Parte 2 recusa "já existe" | Comparar versões das fontes; o robô só sobe a versão quando o conteúdo muda |
