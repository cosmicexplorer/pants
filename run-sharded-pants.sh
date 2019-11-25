#!/bin/bash

set -euxo pipefail

dir_checksum="${1:-}"
dir_size_bytes="${2:-}"

./build-support/bin/native/cargo \
  build \
  --manifest-path ./src/rust/engine/Cargo.toml \
  -p fs_util -p process_executor

if [[ -z "${dir_checksum:-}" ]]; then
  export PANTS_PEX_BIN_LOCATION_URL=''
  cp -v ./pex-1.6.12+dehydration.pex ./pex
  chmod +x ./pex
  output="$(./src/rust/engine/target/debug/fs_util directory save --root=. ./pex | tr ' ' '\n')"
  dir_checksum="$(echo "$output" | head -n1)"
  export PANTS_PEX_BIN_LOCATION_CHECKSUM="$dir_checksum"
  dir_size_bytes="$(echo "$output" | tail -n1)"
  export PANTS_PEX_BIN_LOCATION_SIZE_BYTES="$dir_size_bytes"
fi

rm -rfv dist/

./pants \
  --v2 --no-v1 \
  -ldebug \
  binary \
  src/python/pants/bin:pants_local_binary

cp -v dist/pants_local_binary.pex HACKED-PANTS-DEHYDRATED.pex
unzip -p dist/pants_local_binary.pex PEX-INFO \
  | jq 'setpath(["dehydrated_requirements"]; [])' \
       > HACKED-PEX-INFO
cp -v HACKED-PEX-INFO PEX-INFO
zip -f ./HACKED-PANTS-DEHYDRATED.pex PEX-INFO

rm -rfv wowowow
mkdir -v wowowow
unzip -p dist/pants_local_binary.pex PEX-INFO \
  | jq -r '.dehydrated_requirements[]' \
  | parallel -L1 "(echo :{} && ./src/rust/engine/target/debug/process_executor --input-digest ${dir_checksum} --input-digest-length ${dir_size_bytes} --target-platform none --env PATH="$PATH" --output-file-path {}.pex -- './pex' --platform=current --python=python3.6 -o {}.pex {} 2>&1) | sed -E -n -e 's#^:(.*)\$#\1#gp' -e 's#^output digest: Digest.Fingerprint<(.*?)>, ([0-9]+).*\$#\1=\2#gp' | tr '\n' ',' | sed -E -e 's#,\$#\n#g'" \
  | sed -E -e 's#^[^,]+,##g' \
  | parallel -t -L1 \
             ./src/rust/engine/target/debug/fs_util directory materialize \
             '{=' '$_=s/=.*//r' '=}' \
             '{=' '$_=s/.*=//r' '=}' \
             ./wowowow

export PEX_IGNORE_RCFILES=true
export PEX_PATH="$(find "$(pwd)/wowowow" -name '*.pex' | tr '\n' ':' | sed -E -e 's#:$#\n#g')"
./HACKED-PANTS-DEHYDRATED.pex -ldebug list ::
