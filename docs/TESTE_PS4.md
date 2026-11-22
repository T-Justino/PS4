# Gate 2 — Teste manual no PS4 Pro 9.00 / GoldHEN / SSPI 5.11.7

**Objetivo:** provar importação, busca e detalhes com **IDs reais**. **Não instalar nada.** Duração: ~5 min.

## Arquivos (pasta `dist/`)

| Arquivo | ID | contentSha256 (início) | Observação |
|---|---|---|---|
| `ps4storebr-t2-npxs39041.gssource` | `NPXS39041` | `e574eddb…` | Prefixo NPXS. Já instalado no console: **não reinstalar** |
| `ps4storebr-t3-apol00004.gssource` | `APOL00004` | `e3537c5c…` | ID que o console rejeitou antes. Download falha TLS: **não instalar** |

Se o hash do ZIP for diferente de um ambiente para outro, é normal (ver `AUDITORIA_GATE1.md`). Vale o conteúdo.
São duas fontes separadas de propósito: a rejeição de uma não esconde o resultado da outra.

## Preparação (1 vez)

1. Baixe os dois `.gssource` do GitHub (pasta `dist/`, botão Download raw) no PC.
2. Copie para a **raiz** de um pendrive FAT32 ou exFAT. Não renomeie, não descompacte.
3. Pendrive no PS4, GoldHEN carregado, abra o SSPI.

## Passos — T2 primeiro, depois T3 (repita tudo)

1. SSPI → adicionar fonte → arquivo USB → selecione o arquivo.
2. Anote: **importou?** Se falhar, fotografe a mensagem exata.
3. Busque pelo **nome**: `store` (T2) ou `apollo` (T3).
4. Busque pelo **ID**: `NPXS39041` (T2) ou `APOL00004` (T3).
5. Abra os detalhes. Confira ID, nome, tipo `base` e hoster.
6. **Não** toque em instalar/baixar. Volte e, se quiser, remova a fonte.

## O que me enviar (copie e preencha)

```text
T2: importou [sim/não + erro] | busca nome [ok/vazio] | busca ID [ok/vazio] | ID exibido: ____
T3: importou [sim/não + erro] | busca nome [ok/vazio] | busca ID [ok/vazio] | ID exibido: ____
```
Fotos da tela de erro ou de detalhes, se houver. Se algo falhar, diga também a hora aproximada.

## Interpretação e próximo passo

| Resultado | Conclusão | Próximo passo |
|---|---|---|
| T2 ok, T3 ok | NPXS e APOL aceitos; a rejeição antiga teve outra causa | Gate 1 aceito; seguir ao Gate 3 |
| T2 ok, T3 erro de ID | Binário restringe prefixos; APOL fora | Registrar prefixos permitidos no validador |
| T2 erro de ID | Binário mais restrito que o código público | Testar homebrew com ID `CUSA` real e autorizado |
| Erro que não é de ID (ex.: formato/campo) | Divergência de schema | Gerar variante com `version` nas linhas de pacote e repetir |
| Importou mas busca vazia | Problema de indexação/normalização | Enviar o termo exato digitado; investigar `searchText` |

Compatibilidade só será registrada depois do seu relato.
