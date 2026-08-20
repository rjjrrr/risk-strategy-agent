import numpy as np
from . import config

def _score(r):
    grade={"A":0,"B":1,"REVIEW":2,"C":3}.get(r.get("grade"),4)
    oot={"STRONG":0,"WEAK":1,"NOT_AVAILABLE":2,"FAILED":3}.get(r.get("oot_status"),2)
    return (grade, oot, -r.get("lift",0), -r.get("coverage",0), -r.get("hit_count",0), -r.get("bootstrap_positive_ratio",0))

def deduplicate(rules, df=None, same_threshold=None, similar_threshold=None):
    """Group rules by hit-set Jaccard and retain a representative per group."""
    for i, r in enumerate(rules):
        r.setdefault("duplicate_group", f"RG_{r.get('segment','UNK')}_{i+1:03d}")
        r.setdefault("rule_group_id", r["duplicate_group"])
        r.setdefault("is_representative", True)
    parent=list(range(len(rules)))
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def join(a,b):
        ra,rb=find(a),find(b)
        if ra!=rb: parent[rb]=ra
    for i in range(len(rules)):
        for j in range(i):
            if rules[i].get("segment") != rules[j].get("segment"): continue
            ma=rules[i].get("_mask_global", rules[i].get("_mask")); mb=rules[j].get("_mask_global", rules[j].get("_mask"))
            if ma is None or mb is None: continue
            ma=np.asarray(ma,dtype=bool); mb=np.asarray(mb,dtype=bool); union_n=np.logical_or(ma,mb).sum()
            jac=float(np.logical_and(ma,mb).sum()/union_n) if union_n else 0.0
            rules[i].setdefault("similarity_max",0.0); rules[j].setdefault("similarity_max",0.0)
            rules[i]["similarity_max"]=max(rules[i]["similarity_max"],jac); rules[j]["similarity_max"]=max(rules[j]["similarity_max"],jac)
            if jac >= (same_threshold if same_threshold is not None else config.JACCARD_SAME_GROUP): join(i,j)
    groups={}
    for i in range(len(rules)): groups.setdefault(find(i),[]).append(i)
    for members in groups.values():
        gid=f"RG_{rules[members[0]].get('segment','UNK')}_{min(members)+1:03d}"
        rep=min(members,key=lambda x:_score(rules[x]))
        for i in members:
            rules[i]["duplicate_group"]=gid; rules[i]["rule_group_id"]=gid; rules[i]["is_representative"]=i==rep
    return rules
