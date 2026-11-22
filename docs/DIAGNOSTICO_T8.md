# Diagnóstico do T8: app instalado mas "dados corrompidos" ao abrir

**Sintoma (teste real do usuário, 22/11/2026):** fonte importada, item encontrado, download 6,6/6,6 MB, SSPI mostrou "Installed CUSA95417"; ao abrir:
"Não é possível continuar usando o aplicativo. Os dados do aplicativo a seguir estão corrompidos…".

## O que foi comparado (rede real + extração local com o `PkgTool.Core` do OpenOrbis)

| Item | Nosso T8 | Referências (funcionam em consoles reais) | Resultado |
|---|---|---|---|
| Cabeçalho do PKG (tipo, flags, DRM, tabela, 14 entradas) | igual | Store-R2 (instalou **e abriu** no console do usuário) e `BREW00086` (sample OpenOrbis do PKG-Zone) | **igual**, não é a causa |
| `param.sfo` | `CATEGORY=gd`, `APP_TYPE=1`, `SYSTEM_VER=0`… | `BREW00086` | **mesmo padrão**, só mudam título e ID |
| Cabeçalho do FSELF (`eboot.bin`) | magic/ver/flags/8 segmentos | `BREW00086` | equivalente |
| **Conteúdo do PFS interno** | `eboot.bin`, `right.sprx`, `keystone` | `BREW00086`: **também `sce_module/libc.prx` e `sce_module/libSceFios2.prx`** | **DIFERENÇA** |

## Causa (CONFIRMADA no console em 22/11/2026: o PKG corrigido, com `sce_module`, instalou e abriu — T8b Parte 1)

O PKG foi empacotado **sem `sce_module/libc.prx` e `sce_module/libSceFios2.prx`**. Apps OpenOrbis ligam com `-lc` e carregam a libc desses módulos empacotados; sem eles o PS4 instala
(o container é válido) mas não consegue iniciar o app. Origem do erro: copiei só o `Makefile` do sample e a pasta `sce_module/` ficou vazia (o `.gitkeep` do repositório não traz os módulos; os samples do release sim).
Descartado por comparação: estrutura do PKG, `param.sfo`, cabeçalho do FSELF. Não foi possível comparar o corpo do `eboot.bin` com o do sample (códigos diferentes).

## Correção aplicada (mínima)

`app/build.sh` agora copia os dois módulos do toolchain para `sce_module/`, **e falha** se o PKG gerado não os contiver (extrai com o `PkgTool.Core` e confere), e apaga o `param.sfo` antigo
(a versão ficava velha). A árvore interna do PKG corrigido é idêntica à do `BREW00086` (menos o PNG de exemplo).

## Estado

- PKG original (defeituoso) preservado em `dist/t8/` com aviso; **não** é monitorado nem publicado.
- PKG corrigido `pkgs/PS4StoreBRTest_CUSA95417_v1.00.pkg`: **aprovado no console** (T8b Parte 1). Os suspeitos listados abaixo ficam descartados para este caso.
- Se o app ainda não abrir, os próximos suspeitos são o corpo do `eboot.bin`/dependência de módulo do sistema (`-lSceVideoOut`) ou o tratamento de ID `CUSA` como jogo comercial; não afirmo que a causa seja só a libc.
