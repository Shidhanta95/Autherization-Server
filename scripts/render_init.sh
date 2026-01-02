#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONFIG="$ROOT/platforms.yaml"
TEMPLATE="$ROOT/init.sql.tpl"
OUT="$ROOT/generated/init.sql"

echo "Rendering init.sql from platforms.yaml"

# Generate SQL to a temp file
TEMP_SQL=$(mktemp)
yq -o=json -I=0 '.platforms[]' "$CONFIG" | while IFS= read -r item; do
  name=$(echo "$item" | yq -r '.name')
  prefix=$(echo "$item" | yq -r '.prefix // ""')
  if [ -z "$prefix" ]; then
    echo "SELECT create_platform('$name', NULL);"
  else
    echo "SELECT create_platform('$name', '$prefix');"
  fi
done > "$TEMP_SQL"

mkdir -p "$(dirname "$OUT")"

# Use awk instead of sed for multi-line replacement
awk -v sql="$(cat "$TEMP_SQL")" '{gsub(/\{\{CREATE_PLATFORMS\}\}/, sql); print}' "$TEMPLATE" > "$OUT"

rm -f "$TEMP_SQL"

echo "init.sql generated at $OUT"