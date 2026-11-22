# Resolvedor de links (Etapa 4, 1ª entrega)

Módulo independente (`src/ps4store/resolver.py`): recebe URLs e devolve o arquivo final **sem baixar nada além de 64 KiB** por URL. Não executa nada, não grava arquivos e não altera robô, catálogo, site, workflow ou SSPI.

```
ps4store resolve URL [URL ...] [--arquivo lista.txt] [--permitir host] [--json]
python -m ps4store.resolver ...        # equivalente
```

## O que faz
- Segue redirects HTTP comuns com as regras de segurança do robô (HTTPS, ≤ 5 redirects, sem IP privado) e registra a cadeia de hosts.
- Informa: URL final (informativa, pode ser assinada), **URL estável para colar no SSPI** (ele refaz o redirect por ela), host final, nome do arquivo (`Content-Disposition` ou URL), tamanho informado, Range, e formato **PKG/RAR confirmado pela assinatura dos bytes** (o nome só vale se os bytes não contradisserem).
- Volumes `.partNN.rar`: agrupa, **ordena** (mesmo embaralhados), aponta volume faltando, repetido ou conjunto que não começa em 1; devolve `sspiOrder`.
- **Fontes permitidas:** só o host da URL de entrada precisa estar em `config/resolver-hosts.json` (ou `--permitir`). Redirects para outros hosts HTTPS públicos são seguidos e ficam na cadeia.
- Estados: `OK`, `INTERACAO_NECESSARIA` (CAPTCHA, JavaScript, anti-robô, login, espera, ou página sem link direto: **não contorna**), `PAGINA_SEM_ARQUIVO` (HTML com links estáticos a PKG/RAR, listados e **não seguidos**), `NAO_E_ARQUIVO` (200 com JSON/HTML de erro), `FORMATO_NAO_SUPORTADO` (zip/7z), `INACESSIVEL` (404, 403…), `HOST_NAO_PERMITIDO`.
- "Enviável ao SSPI" = PKG ou RAR com link utilizável pelo baixador (hipótese pelo código do SSPI; só o console prova).

## Resultados reais (22/11/2026)
- PKG próprio (raw.githubusercontent.com): OK, 6,6 MB, direto, enviável.
- 11 volumes RAR próprios, entrada embaralhada (03, 01, 02, 04…): todos OK; grupo **completo, 11 volumes, 6,6 MB**.
- OpenTyrian (`pkg-zone.com/download/ps4/OPEN00001/1.01`): OK, `PS4_OPEN00001_v1.01.pkg`, 19,8 MB, redirect → `api.pkg-zone.com` (URL assinada ≈ 6 h).
- `https://pkg-zone.com/` (página): `INTERACAO_NECESSARIA` (HTML sem link direto).
- pacote inexistente no pkg-zone: o servidor responde **200 com `{"error":"Package not found."}`** → `NAO_E_ARQUIVO` com a mensagem (achado do teste real; sem isso viraria "formato desconhecido").
- host fora da lista (`example.com`): `HOST_NAO_PERMITIDO`.

Testes: `tests/test_resolver.py` (14, servidor HTTP local com arquivos próprios) e a suíte inteira (171) passam.

## Limites desta entrega
Não lê HTML além de links `<a href>` estáticos; não segue esses links; não resolve páginas de hosters com JavaScript; RAR de estilo antigo (`.rar` + `.r00`) é ordenado, mas a contagem não é verificável; não lê o conteúdo do RAR (só a assinatura).
