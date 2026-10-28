set -u
UA="open-guji-research/1.0 (lisdpku@gmail.com)"
mkdir -p out
while IFS= read -r name; do
  [ -z "$name" ] && continue
  id=$(echo "$name" | cut -d' ' -f1)
  enc=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1].replace(" ","_")))' "$name")
  for i in 1 2 3 4 5 6; do
    curl -sSL -m 900 -A "$UA" -o out/$id.djvu "https://commons.wikimedia.org/wiki/Special:FilePath/$enc"
    [ "$(stat -c %s out/$id.djvu)" -gt 100000 ] && break; sleep $((i*20))
  done
  echo "$name $(stat -c %s out/$id.djvu) $(sha1sum out/$id.djvu | cut -d' ' -f1)" >> out/got.log
  sleep 3
done < tmp_qjw/batch.txt
