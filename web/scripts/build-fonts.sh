#!/usr/bin/env bash
# Пересборка самохостовых шрифтов.
#
# Зачем скрипт, а не ссылка на Google Fonts CDN: деплой может стоять в закрытом
# контуре — по той же причине, по которой в образ вендорится корневой сертификат.
#
# Зачем свой сабсеттинг, а не готовые подмножества Google: знак рубля U+20BD
# лежит у них в подмножестве latin-ext, и без него ₽ на каждом экране рисуется
# подставным системным шрифтом. Здесь он входит в основной набор.
#
# Требует: python3, curl. fonttools ставится во временное окружение.
# Запуск:  bash scripts/build-fonts.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/public/fonts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Кириллица + базовая латиница + пунктуация + № ₽ — всё, что встречается в UI.
UNICODES='U+0000-00FF,U+0131,U+0152-0153,U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2000-206F,U+20BD,U+2116,U+2122,U+2190-2193,U+2212,U+2215,U+2260,U+2264-2265'

python3 -m venv "$TMP/venv"
"$TMP/venv/bin/pip" install -q fonttools brotli

# Старый User-Agent — Google отдаёт ttf вместо уже нарезанных woff2.
curl -s -A "Mozilla/4.0" \
  "https://fonts.googleapis.com/css2?family=Golos+Text:wght@400..700&family=JetBrains+Mono:wght@400..500&display=swap" \
  > "$TMP/ttf.css"

node -e '
const fs = require("fs");
const css = fs.readFileSync(process.argv[1], "utf8");
const re = /font-family: .([^;\x27]+).;[\s\S]*?font-weight: (\d+);[\s\S]*?url\((https:[^)]+)\)/g;
let m, out = [];
while ((m = re.exec(css))) {
  out.push([m[1].trim().toLowerCase().replace(/\s+/g, "-") + "-" + m[2], m[3]]);
}
fs.writeFileSync(process.argv[2], out.map((o) => o.join(" ") + "\n").join(""));
' "$TMP/ttf.css" "$TMP/jobs.txt"

mkdir -p "$OUT"
rm -f "$OUT"/*.woff2

while read -r name url; do
  curl -s "$url" -o "$TMP/$name.ttf"
  "$TMP/venv/bin/pyftsubset" "$TMP/$name.ttf" \
    --unicodes="$UNICODES" \
    --layout-features='kern,liga,ss01,tnum' \
    --flavor=woff2 \
    --output-file="$OUT/$name.woff2"
  echo "  $name.woff2  $(du -h "$OUT/$name.woff2" | cut -f1)"
done < "$TMP/jobs.txt"

echo "Готово. Объявления @font-face — в src/app/fonts.css (правятся руками)."
