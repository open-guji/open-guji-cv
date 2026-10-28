set -u
UA="open-guji-research/1.0 (lisdpku@gmail.com)"
sudo apt-get update -qq && sudo apt-get install -y -qq djvulibre-bin imagemagick >/dev/null
mkdir -p w out
while IFS= read -r name; do
  [ -z "$name" ] && continue
  id=$(echo "$name" | cut -d' ' -f1)
  enc=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1].replace(" ","_")))' "$name")
  for i in 1 2 3 4 5; do
    curl -sSL -m 600 -A "$UA" -o w/f.djvu "https://commons.wikimedia.org/wiki/Special:FilePath/$enc"
    [ "$(stat -c %s w/f.djvu)" -gt 100000 ] && break; sleep $((i*15))
  done
  n=$(djvused -e n w/f.djvu)
  echo "$name pages=$n" >> out/pages.log
  for p in 1 2 3 4 $n; do
    ddjvu -format=ppm -page=$p -size=400x600 w/f.djvu w/p.ppm 2>/dev/null && convert w/p.ppm -resize 400x600! w/p_$p.png
  done
  montage w/p_1.png w/p_2.png w/p_3.png w/p_4.png w/p_$n.png -tile 5x1 -geometry +4+4 -background gray out/$id.jpg
  rm -f w/*
  sleep 5
done < tmp_qjw/sel.txt
