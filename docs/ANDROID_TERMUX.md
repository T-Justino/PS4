# Android (Termux) como central de resolução de links (Etapa 4E)

Fluxo: **navegador do Android → Compartilhar → Termux → `resolver.py` → bloco de URLs → colar no painel Phone Companion do SSPI.**
Sem PC, sem VPS, sem Playwright, sem alterar o PS4. O SSPI continua baixando e instalando; o Android só resolve e valida (lê no máximo 64 KiB por URL).

## Instalação (uma vez, no Termux)
Use o Termux do **F-Droid ou do GitHub** (não o da Play Store) e, se quiser copiar automático, o app **Termux:API** da mesma origem.
```sh
pkg update -y && pkg install -y python git
pkg install -y termux-api        # opcional: cópia automática (instale também o app Termux:API)
git clone --branch ccr-8aace08a-bzwy8i --single-branch https://github.com/T-Justino/PS4.git ~/PS4
cd ~/PS4
mkdir -p ~/bin && cp android/termux-url-opener ~/bin/termux-url-opener && chmod +x ~/bin/termux-url-opener
```
Atualizar depois: `cd ~/PS4 && git pull`.

## Teste 1: suíte e arquivos próprios (antes de tocar no SSPI)
```sh
cd ~/PS4
pip install pytest && PYTHONPATH=src python -m pytest -q                  # esperado: 216 passed, 1 skipped (sem Playwright)
B=https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i
PYTHONPATH=src python -m ps4store.colar --sem-copiar $B/pkgs/PS4StoreBRTest_CUSA95417_v1.02.pkg
PYTHONPATH=src python -m ps4store.colar --sem-copiar https://github.com/T-Justino/PS4/tree/ccr-8aace08a-bzwy8i/rartest
PYTHONPATH=src python -m ps4store.colar --sem-copiar https://pkg-zone.com/download/ps4/OPEN00001/1.01
```
Esperado: (1) 1 bloco PRONTO, 6,6 MB; (2) 1 bloco PRONTO "RAR … 11 volume(s)", URLs `part01 … part11` em ordem; (3) 1 bloco PRONTO, 19,8 MB. Sem `--sem-copiar`, o bloco 1 vai para a área de transferência (se o Termux:API estiver instalado) ou aparece entre `----- copie daqui -----` e `----- até aqui -----` para copiar à mão.
Para testar o bloqueio: acrescente `--max-paginas 5` ao comando (2): o conjunto vira **NÃO ENVIAR** (busca truncada).

### Listas de URLs (`--arquivo`)
Uma URL por linha; linhas vazias e `#` são ignoradas; **sem o limite de 10** (o limite de 10 vale só para URLs passadas como argumento/texto compartilhado, e agora avisa quando corta). As URLs da lista são resolvidas uma a uma e os volumes RAR são agrupados em **um único bloco**, na ordem.
```sh
cd ~/PS4
PYTHONPATH=src python -m ps4store.colar --arquivo rartest/links-ordem.txt            # esperado: 1 bloco PRONTO, 11 volumes, 6,6 MB
PYTHONPATH=src python -m ps4store.colar --arquivo rartest/links-embaralhado.txt      # esperado: igual (ordem 01 → 11)
PYTHONPATH=src python -m ps4store.colar --arquivo rartest/links-sem-part11.txt       # esperado: NÃO ENVIAR (falta o último volume)
```
Faltando o **último** volume não há como notar pela contagem; por isso o formatador lê só os 64 bytes finais do último volume RAR5 e confere o cabeçalho de fim: se ele declara "há mais volumes", o conjunto é bloqueado. Se o cabeçalho não puder ser lido (RAR4, servidor sem Range), o bloco sai com o aviso "fim do conjunto não confirmado".

## Teste 2: pelo botão Compartilhar
1. No Chrome do Android, abra uma página (ex.: `https://pkg-zone.com/download/ps4/OPEN00001/1.01`), toque em **Compartilhar → Termux**.
2. O Termux abre, resolve e mostra o bloco; com Termux:API, o bloco já está copiado. **Enter** fecha.

## Teste 3: enviar ao SSPI (só depois de validar o resultado acima)
No PS4, abra o SSPI → mostre o **QR do Phone Companion** → escaneie → aba **Downloads** → campo *Paste a download link* → **cole** → enviar. Um link (OpenTyrian) entra na fila; o bloco dos 11 volumes é reconhecido como um RAR (nomes `.partNN.rar`). Anote o resultado.

## Regras do que é "PRONTO"
- Só arquivo `OK` e enviável ao SSPI. Link assinado/temporário (`exp=`, `sig=`, `token=`…) **não entra** (use `--aceitar-temporarias` por sua conta).
- Conjunto RAR só é pronto se `.partNN.rar`, **completo, em ordem, sem busca truncada e com ≤ 50 volumes**. Estilo antigo (`.rar` + `.r00`) fica bloqueado (a contagem não é verificável).
- O painel aceita **no máximo 50 links por envio** (acima disso nada é enfileirado): listas avulsas maiores viram lotes de 50, com aviso; use `--bloco N` para copiar outro lote.
- Páginas com CAPTCHA, login, JavaScript ou botões: `INTERACAO_NECESSARIA` em "NÃO ENVIAR"; nada é contornado.

## Hosts e segurança
- Só hosts de `config/resolver-hosts.json` são acessados (github, raw.githubusercontent, pkg-zone, jsDelivr, archive.org). Outro host: `export PS4STORE_PERMITIR=host1,host2` (ponha no início de `~/bin/termux-url-opener`, depois de `#!`) ou `--permitir host`.
- O texto compartilhado **nunca é interpretado pelo shell**: vai entre aspas, depois de `--`, para o Python, que só extrai URLs `http(s)` por regex (sem espaços, controle ou credenciais). Testado com `$(…)`, crases, `;`, `-h`, quebras de linha.
- Nada é gravado: sem histórico, sem logs de URL. Não use este fluxo para publicar links privados ou temporários.
