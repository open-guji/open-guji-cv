"""防丢字检查：格位表（整理本）认作有字的格，到 Step4（cell_shrink）不见了或判成空格的，逐格列出。

    python scripts/check_layout_drop.py <产物根> [--out drop.tsv]

<产物根> 下是 `<册>/<册>/row_segment/p*.json` 与同级的 `cell_shrink/`（`guji products pack fetch --to` 取回的样子），
或直接给 `<工作区>/products/<book>` 的上一级。row_segment 里带 `layout_char` 旗（格位表说这格有字）的格，
cell_shrink 里同格号（夹注先找 a/b 半格、找不到再找合成的满宽格）不在或 `cell_type == "empty"` 的算丢。

这类格到 seed_admit 已经没有了，进不了待审，整理本里的字在转写里悄悄少掉（第 16 轮史記夹注 v1.4 把列尾行切满，
cell_shrink 按旧格线判空，6 列 12 字丢了）。墨占比高的多半是真丢字，墨占比低的是格位表说有字、切分却留了空格，
字并进了别的格，也要看。验收每一轮切分都跑一遍，非零就报。
"""

import json,glob,os,sys,collections
import argparse
ap=argparse.ArgumentParser(); ap.add_argument('root'); ap.add_argument('--out')
args=ap.parse_args(); root=args.root; out=[]
for v in sorted(os.listdir(root)):
  for f in sorted(glob.glob(f'{root}/{v}/{v}/row_segment/p*.json')):
    p=int(os.path.basename(f)[1:5]); g=f.replace('row_segment','cell_shrink')
    if not os.path.exists(g): continue
    rs=json.load(open(f,encoding='utf-8'))['cells']['columns']; cs={c['col']:c for c in json.load(open(g,encoding='utf-8'))['char_index']['columns']}
    for col in rs:
      c=cs.get(col['col'])
      if not c or not c.get('chars'): continue
      ids={x['id'].split(':')[3]:x for x in c['chars']}
      for x in col['cells']:
        if x['kind']=='blank' or 'layout_char' not in (x.get('flags') or []): continue
        k=f"{x['slot']}{x.get('sub') or ''}"
        m=ids.get(k)
        if m is None and x.get('sub'):
          m=ids.get(str(x['slot']))
        if m is None or m['cell_type']=='empty':
          out.append((f"{v}:{p}:{col['col']}:{k}",x['kind'],str(x.get('ink_ratio')),','.join((m or {}).get('flags') or ['缺格'])))
cnt=collections.Counter(o[0].rsplit(':',1)[0] for o in out)
print(len(out),'格',len(cnt),'列')
if args.out:
  open(args.out,'w',encoding='utf-8').write('格号\t切分类型\t墨占比\tcell_shrink旗\n'+''.join('\t'.join(o)+'\n' for o in out))
for o in out: print(*o)
sys.exit(1 if out else 0)
