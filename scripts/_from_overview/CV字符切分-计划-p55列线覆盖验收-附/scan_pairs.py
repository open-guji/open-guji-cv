import json,glob,os,statistics as st,collections
R="/tmp/claude-0/sbx/scan"
tot=0; narrow=[]; pairs=[]
for f in sorted(glob.glob(f"{R}/vol0*/border_detect/p*.json")):
    b=f.split("/")[-3]; p=int(os.path.basename(f)[1:5])
    d=json.load(open(f)); li=d["line_index"]["lines"]
    w=[l["width"] for l in li if l["kind"]=="body"]
    if len(w)<3: continue
    tot+=1; med=st.median(w)
    if min(w)<0.7*med: narrow.append((b,p,[round(x) for x in w],round(med)))
    for i in range(len(w)-1):
        a,c=w[i],w[i+1]
        if a<0.7*med and c<0.7*med and 0.85<=(a+c)/med<=1.15:
            rest=[x for j,x in enumerate(w) if j not in (i,i+1)]
            clean=all(0.8*med<=x<=1.2*med for x in rest)
            pairs.append((b,p,i+1,round(a),round(c),round((a+c)/med,2),"rest_clean" if clean else "rest_dirty"))
print("pages",tot)
print("pages with a column <0.7*median:",len(narrow))
for x in narrow: print("  ",x)
print("pair-signature hits:",len(pairs))
for x in pairs: print("  ",x)
