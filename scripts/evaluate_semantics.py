#!/usr/bin/env python3
"""Small manually labelled probes, not evidence of general semantic accuracy."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.recommendation.semantic import similarity,VERSION

# Labels mean near-duplicate concept, not entity identity; 'related' is not duplicate.
PROBES=[
 ('群体智能','swarm intelligence','duplicate'),('群体智能','蚁群如何完成集体决策','duplicate'),
 ('分布式系统','distributed systems','duplicate'),('图论','graph theory','duplicate'),
 ('贝叶斯定理','Bayesian inference','related'),('傅里叶分析','Fourier analysis','duplicate'),
 ('共振','resonance','duplicate'),('昼夜节律','circadian rhythm','duplicate'),
 ('表观遗传学','epigenetics','duplicate'),('量子隧穿','quantum tunneling','duplicate'),
 ('负空间','构图中的留白','duplicate'),('平面密铺','tessellation','duplicate'),
 ('计算复杂度','computational complexity','duplicate'),('海水的有向运动','ocean current','duplicate'),
 ('群体智能','分布式系统中的涌现行为','related'),('图论','社会网络','related'),
 ('音乐节奏','傅里叶分析','related'),('贝叶斯定理','图论','unrelated'),
 ('共振','resonance imaging','related'), # a specific application retains separate identity
 ('熵','表观遗传学','unrelated'),('量子隧穿','古代口述史','unrelated'),
 ('社会网络','分布式系统','related'),('负空间','核聚变','unrelated'),
 ('傅里叶分析','拍卖理论','unrelated'),
]


def evaluate():
    rows=[]
    for left,right,label in PROBES:
        a,b={'title':left},{'title':right}
        # A qualified alias such as imaging should not imply conceptual identity.
        rows.append({'left':left,'right':right,'label':label,'lexical':round(similarity(a,b,False),4),'semantic':round(similarity(a,b,True),4)})
    scores={}
    for method in ('lexical','semantic'):
        tp=sum(r[method]>=.82 and r['label']=='duplicate' for r in rows)
        fp=sum(r[method]>=.82 and r['label']!='duplicate' for r in rows)
        fn=sum(r[method]<.82 and r['label']=='duplicate' for r in rows)
        precision=tp/(tp+fp) if tp+fp else 0
        recall=tp/(tp+fn) if tp+fn else 0
        scores[method]={'precision':precision,'recall':recall,'f1':2*precision*recall/(precision+recall) if precision+recall else 0,'true_positive':tp,'false_positive':fp,'false_negative':fn}
    return {'kind':'small_curated_probe_not_held_out_generalization','version':VERSION,'threshold':.82,'scores':scores,'probes':rows,'limits':'Aliases are manually chosen and probes partly overlap their design. No entity merging. Unseen paraphrases and qualified applications may fail; fallback is lexical.'}


if __name__=='__main__':
    result=evaluate();(ROOT/'docs/semantic-evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['scores'],ensure_ascii=False))
