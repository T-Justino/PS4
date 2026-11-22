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
mkdir -p sce_sys/about
cp "$TC/samples/graphics/sce_sys/about/right.sprx" sce_sys/about/right.sprx   # módulo "about" padrão do toolchain
make clean >/dev/null 2>&1 || true
make
echo "PKG: $(pwd)/IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg"
