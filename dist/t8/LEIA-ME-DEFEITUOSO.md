# T8 original: PKG DEFEITUOSO, preservado só para diagnóstico

`IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg` instala, mas o app **não abre** ("dados corrompidos", teste real do usuário em 22/11/2026).
Causa mais provável (a confirmar no console): o PKG foi empacotado **sem `sce_module/libc.prx` e `sce_module/libSceFios2.prx`**.
**Não use nem publique este arquivo.** O PKG corrigido está em `pkgs/` (ver `docs/DIAGNOSTICO_T8.md`).
