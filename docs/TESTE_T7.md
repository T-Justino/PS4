> ## RESULTADO (22/11/2026, relato do usuário; PS4 Pro 9.00, SSPI 5.11.7 Final, rodapé `BETA 5.11 / 0eb783eca1f3`)
>
> | Etapa | Resultado |
> |---|---|
> | Fonte importada | **sim** |
> | Item encontrado na pesquisa | **sim** |
> | Download | **concluído** (24,8 MB / 24,8 MB) |
> | PKG aceito pela instalação | **RECUSADO**: `Base game package · expected CUSA90004 got NPXS39041` |
> | Instalação concluída | **não** (bloqueada antes de concluir) |
>
> A linha "Installed" exibida embaixo é a instalação anterior do Store-R2.pkg por link direto, **não** o T7.
> **Conclusão: falha de compatibilidade de identidade** (não é erro de download nem de "já instalado"). O SSPI compara a chave
> do catálogo com o ID interno do PKG na instalação. **Chaves sintéticas `CUSA` não instalam pacotes de ID diferente.**
> Estratégia abandonada em produção; ver `docs/SDD_REVISADO.md` §12.

# T7 — Instalação do PKG sob chave sintética (teste histórico) (PS4 Pro 9.00 / GoldHEN / SSPI 5.11.7)

**Pergunta:** o SSPI instala um PKG cujo ID interno (`NPXS39041`) é diferente da chave de catálogo (`CUSA90004`)?
Os testes T4/T5/T6 provaram só a importação da fonte. **Este é o primeiro teste de instalação de PKG.**

| Item | Valor |
|---|---|
| Arquivo | `dist/probes/ps4storebr-t7-cusa90004.gssource` |
| contentSha256 | `52c24cbee26789a10c509cab80fca3ced33c53e1f2e8bae1c8b72c46afce3d5f` (o hash do ZIP pode variar; ver `AUDITORIA_GATE1.md`) |
| Chave de catálogo | `CUSA90004` (sintética, experimental) |
| Pacote | Store-R2.pkg oficial do PKG-Zone, URL `https://pkg-zone.com/update/Store-R2.pkg`, **sem modificação**; ID interno real `NPXS39041` |

## Segurança

- O PKG não é alterado nem tem o ID falsificado: a única coisa sintética é a chave no catálogo.
- A Homebrew Store **já está instalada**. **Não desinstale nada.** Se o SSPI oferecer *desinstalar primeiro*, *substituir* ou
  *apagar dados*, escolha **Cancelar/Não** e anote o texto. Nada neste teste exige remover dados ou mexer no firmware.
- Se a instalação for aceita, ela funciona como reinstalação/atualização do mesmo PKG por cima do atual (procedimento normal;
  não é destrutivo por design, mas não é garantido por este projeto).

## Passos (anote o resultado de cada etapa; pare na primeira que falhar)

1. **Fonte importada.** Pendrive → SSPI → *Install source from USB* → `ps4storebr-t7-cusa90004.gssource` → Install.
   Remova antes as fontes T4/T5/T6, para não misturar resultados.
2. **Encontrado na pesquisa.** Busque `store` e `CUSA90004` (e `teste t7`). Deve aparecer **1 item** "PKG-Zone Store". Abra os detalhes.
3. **Download iniciado.** Toque em Instalar/Baixar no item. O download (≈ 24,8 MB) aparece na fila de downloads? Anote.
4. **Download concluído.** Aguarde terminar (a barra chega ao fim / status "baixado" ou "verificando").
5. **PKG aceito ou recusado.** Após baixar, o SSPI valida o PKG e tenta instalar. Anote **a mensagem exata** (foto) se recusar.
6. **Instalação concluída.** Confirme no console: a Homebrew Store continua abrindo e aparece normalmente na tela inicial. Anote
   se o SSPI mostra "instalado/concluído".

## Como registrar (copie e preencha)

```text
T7
1 fonte importada:        [sim / não + erro]
2 achado na pesquisa:     [sim (1 item) / não / mais de 1]
3 download iniciado:      [sim / não + mensagem]
4 download concluído:     [sim / não / parou em __%]
5 PKG aceito/recusado:    [aceito / recusado + mensagem EXATA]
6 instalação concluída:   [sim, Store abre / não + mensagem]
Prompt de desinstalar/substituir: [não apareceu / apareceu: texto ___ → cancelei]
Foto das mensagens: [anexada]
```

## Como interpretar

| Resultado | Significa | Próximo passo |
|---|---|---|
| 6 = sim | **Chave sintética `CUSA` instala PKG de ID interno diferente**, para este PKG nesta versão do SSPI. Não generaliza | Testar um PKG não instalado (T8) antes de adotar a estratégia |
| 5 = recusado com `Package does not belong to CUSA90004` ou `expected CUSA90004 got NPXS39041` | **Recusa de identidade**: o SSPI confere a chave com o ID do PKG. Chaves sintéticas não servem para instalar | Mudar de estratégia (ID real quando aceito, ou outra) |
| 5 = recusado com `Package type mismatch…` | Tipo do PKG (base/update) diferente do declarado; **não** é identidade | Corrigir `kind` e repetir |
| 3 ou 4 falham (TLS, rede, HTTP) | Problema de download, **não** de identidade | Testar de novo; verificar o host |
| Falha em 5/6 falando de app **já instalado** / código `AppExists` / erro de instalação genérico, **sem** mensagem de identidade | **Inconclusivo**: pode ser a Store já instalada, não a identidade | Não concluir nada; testar um homebrew ainda não instalado (T8) |
| Prompt de desinstalar/substituir | Cancelar; anote o texto | Inconclusivo para identidade |

**Leitura do código público (hipótese, não prova):** a checagem de identidade (`CheckRequestedIdentity`) roda **antes** da checagem
"app já existe". Se isso valer no seu binário, uma recusa de identidade apareceria mesmo com a Store instalada, e uma
recusa **sem** mensagem de identidade tenderia a ser "já instalado". Só confirme isso com a mensagem exata.

Compatibilidade só será registrada depois do seu relato.
