#!/bin/bash
# k=10 / 20 同库同路径回放 vol05（env 同 run.sh；$S 下要有 prod/products 快照与 env.sh）。overview#493
. ${S:?先 export S=<沙箱目录>}/env.sh
cd /home/user/open-guji-cv
SA='{"patch_missing":"skip","juan_rule":true,"variant_tie":true,"variant_tie_cov":0.97,"variant_tie_extra":"𫎇蒙䝉,㸃點,㕘參,䜟讖識,𨽾隸,慎愼"}'
for K in 10 20; do
  D=$S/kk$K; rm -rf $D; mkdir -p $D; cp -r $S/prod/products/vol05 $D/
  GUJI_PRODUCTS_DIR=$D .venv/bin/python -m open_guji_cv step glyph_match vol05 -w $GUJI_WORKSPACE --pages all --force --jobs 4 --params "{\"glyph_match\":{\"knn_k\":$K}}" > $D.gm.log 2>&1
  GUJI_PRODUCTS_DIR=$D .venv/bin/python -m open_guji_cv step seed_admit vol05 -w $GUJI_WORKSPACE --pages all --force --params "{\"seed_admit\":$SA}" > $D.sa.log 2>&1
done
echo ALLDONE > $S/kk.done
