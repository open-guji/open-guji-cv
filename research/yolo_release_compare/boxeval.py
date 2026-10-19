import numpy as np
def iou_mat(A,B):
    A=np.asarray(A,float).reshape(-1,4); B=np.asarray(B,float).reshape(-1,4)
    if not len(A) or not len(B): return np.zeros((len(A),len(B)))
    x0=np.maximum(A[:,None,0],B[None,:,0]); y0=np.maximum(A[:,None,1],B[None,:,1])
    x1=np.minimum(A[:,None,2],B[None,:,2]); y1=np.minimum(A[:,None,3],B[None,:,3])
    inter=np.clip(x1-x0,0,None)*np.clip(y1-y0,0,None)
    aa=(A[:,2]-A[:,0])*(A[:,3]-A[:,1]); bb=(B[:,2]-B[:,0])*(B[:,3]-B[:,1])
    return inter/(aa[:,None]+bb[None,:]-inter+1e-9)
def match(pred,ref,thr=0.5):
    """贪心一对一；返回 (tp, fp_idx, fn_idx, ious_of_tp, pairs)"""
    M=iou_mat(pred,ref); pairs=[]; used_p=set(); used_r=set()
    if M.size:
        order=np.dstack(np.unravel_index(np.argsort(-M,axis=None),M.shape))[0]
        for i,j in order:
            if M[i,j]<thr: break
            if i in used_p or j in used_r: continue
            used_p.add(i); used_r.add(j); pairs.append((int(i),int(j),float(M[i,j])))
    fp=[i for i in range(len(pred)) if i not in used_p]; fn=[j for j in range(len(ref)) if j not in used_r]
    return len(pairs),fp,fn,[p[2] for p in pairs],pairs
