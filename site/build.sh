#!/bin/sh
# Copy the showcase and style loops plus the OFL fonts from the package into
# the site's public folder (not tracked; run before `wrangler deploy`).
set -e
cd "$(dirname "$0")"
P=../src/aipg_cinema
mkdir -p public/media public/fonts public/brand
cp $P/icons/brand/wordmark-white.svg $P/icons/brand/wordmark-black.svg $P/icons/brand/symbol-white.svg $P/icons/brand/symbol-white-256.png $P/icons/brand/og.jpg public/brand/
cp $P/showcase/*.mp4 $P/showcase/*.jpg public/media/
for s in ink-wash golden-hour watercolor bioluminescent neon-future anime; do
  cp $P/styles/$s.mp4 $P/styles/$s.jpg public/media/
done
cp $P/fonts/Michroma-Regular.ttf $P/fonts/Montserrat-VF.ttf $P/fonts/OFL-Michroma.txt $P/fonts/OFL-Montserrat.txt public/fonts/
[ -f demo/openfield-demo.mp4 ] && cp demo/openfield-demo.mp4 public/media/openfield-demo.mp4
echo "site assets ready: $(ls public/media | wc -l | tr -d ' ') media files"
