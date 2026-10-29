#!/bin/sh
# Copy the showcase and style loops plus the OFL fonts from the package into
# the site's public folder (not tracked; run before `wrangler deploy`).
set -e
cd "$(dirname "$0")"
P=../src/aipg_cinema
mkdir -p public/media public/fonts
cp $P/showcase/*.mp4 $P/showcase/*.jpg public/media/
for s in ink-wash golden-hour watercolor bioluminescent neon-future anime; do
  cp $P/styles/$s.mp4 $P/styles/$s.jpg public/media/
done
cp $P/fonts/Michroma-Regular.ttf $P/fonts/Montserrat-VF.ttf $P/fonts/OFL-Michroma.txt $P/fonts/OFL-Montserrat.txt public/fonts/
echo "site assets ready: $(ls public/media | wc -l | tr -d ' ') media files"
