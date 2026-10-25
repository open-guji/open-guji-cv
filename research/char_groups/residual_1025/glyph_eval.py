import json,sys,collections
lab={}
for l in open('/home/user/open-guji-dataset/char-groups/labels/unified.jsonl'):
  r=json.loads(l)
  if r['kind'] in ('shape','reading'): lab.setdefault(r['id'],{})[r['kind']]=r['form']
G=set(sys.argv[2].split(','))
st=collections.defaultdict(list)
for l in open(sys.argv[1]):
  r=json.loads(l); n=r['new']
  if not n or n['gid'] not in G or n['mode']!='review': continue
  cur=(r['orig'] or {}).get('char') or n['char']
  L=lab.get(r['id'],{})
  truth=L.get('reading') or L.get('shape')
  src='label' if truth else None
  if not truth and r['ref']==cur and r.get('coord') in (cur,None) and r['ref']:
    truth=cur; src='ref'
  for t in n['trail'] or []:
    if t.get('solver') in ('ids','rr_img') :
      st[(n['gid'],t['solver'])].append((t.get('char'),t.get('margin'),cur,truth,src,r['id']))
for k,v in sorted(st.items()):
  gave=[x for x in v if x[0]]
  dis=[x for x in gave if x[0]!=x[2]]
  wrong=[x for x in dis if x[3] and x[0]!=x[3]]
  right=[x for x in dis if x[3] and x[0]==x[3]]
  print(k,'n',len(v),'gave',len(gave),'dissent',len(dis),'dissent_wrong',len(wrong),'dissent_right',len(right))
  for x in sorted(dis,key=lambda x:-(x[1] or 0)): print('   ',x)
