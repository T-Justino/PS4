#!/usr/bin/env bash
# Compila o "PS4 Store BR Test" com o OpenOrbis PS4 Toolchain v0.5.2 (open source, sem SDK da Sony).
# Requer: clang, lld, make, curl, tar. Baixa o release para ~/.cache (não vai para o Git) e confere o SHA-256.
set -euo pipefail
VER=v0.5.2
SHA=92457ea5cb4b5fe80ca45a578f7899458fec5634143c7091a605cde823941334
CACHE="${OO_CACHE:-$HOME/.cache/openorbis}"
TC="$CACHE/OpenOrbis/PS4Toolchain"
mkdir -p "$CACHE"
if [ ! -x "$TC/bin/linux/PkgTool.Core" ]; then
  curl -fL -o "$CACHE/$VER.tar.gz" "https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain/releases/download/$VER/$VER.tar.gz"
  echo "$SHA  $CACHE/$VER.tar.gz" | sha256sum -c -
  tar -xzf "$CACHE/$VER.tar.gz" -C "$CACHE"
fi
export OO_PS4_TOOLCHAIN="$TC"
export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1   # PkgTool.Core (.NET) não precisa de ICU
cd "$(dirname "$0")/ps4storebr-test"
mkdir -p sce_sys/about sce_module
cp "$TC/samples/graphics/sce_sys/about/right.sprx" sce_sys/about/right.sprx   # módulo "about" padrão do toolchain
# OBRIGATÓRIO: apps OpenOrbis carregam a libc destes módulos empacotados. Sem eles o PS4 instala o PKG mas não abre o app
# ("dados corrompidos"). Causa do defeito do T8 original (22/11/2026).
cp "$TC/samples/graphics/sce_module/libc.prx" "$TC/samples/graphics/sce_module/libSceFios2.prx" sce_module/
APP_VERSION="${APP_VERSION:-1.00}"
rm -f sce_sys/param.sfo pkg.gp4 eboot.bin *.pkg   # o make clean do sample não apaga o param.sfo: sem isto a versão fica velha
make clean >/dev/null 2>&1 || true
make VERSION="$APP_VERSION" EXTRAFLAGS="-DAPP_VERSION=\\\"$APP_VERSION\\\""
PKG="$(pwd)/IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg"
# verificação pós-build: o PKG tem que conter os módulos (extrai com a própria ferramenta e confere)
CHK="$(mktemp -d)"; "$TC/bin/linux/PkgTool.Core" pkg_extract "$PKG" "$CHK" >/dev/null
for f in eboot.bin sce_module/libc.prx sce_module/libSceFios2.prx sce_sys/about/right.sprx; do
  [ -f "$CHK/uroot/$f" ] || { echo "ERRO: $f ausente no PKG" >&2; exit 1; }
done
rm -rf "$CHK"
echo "PKG verificado (módulos presentes): $PKG"
