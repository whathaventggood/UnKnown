"""Optional small bilingual concept normalizer; NOT a general embedding model.

Only curated aliases imply near-duplicates. Shared mechanisms indicate related
topics, never entity identity. Outside glossary coverage fall back to lexical
similarity. No model downloads, external calls or vector database.
"""
import re
from functools import lru_cache

VERSION='bilingual-concepts-1'
ALIASES={
    'swarm_intelligence':('群体智能','群集智能','swarm intelligence','蚁群集体决策','蚁群如何完成集体决策'),
    'emergence':('涌现','emergence','emergent behavior','emergent behaviour'),
    'distributed_system':('分布式系统','distributed system','distributed computing'),
    'graph_theory':('图论','graph theory','graphs and edges'),
    'bayes':('贝叶斯','bayes','bayesian','条件概率的反向推断'),
    'fourier':('傅里叶','fourier','频域分解'),
    'resonance':('共振','resonance','受迫振动的振幅放大'),
    'entropy':('熵','entropy'),
    'game_theory':('博弈论','game theory','strategic interaction'),
    'social_network':('社会网络','social network'),
    'circadian':('昼夜节律','circadian rhythm','生物钟'),
    'epigenetics':('表观遗传','epigenetic'),
    'tessellation':('镶嵌','tessellation','平面密铺'),
    'negative_space':('负空间','negative space','构图中的留白'),
    'quantum_tunnelling':('量子隧穿','quantum tunnelling','quantum tunneling'),
    'complex_network':('复杂网络','complex network'),
}
MECHANISMS={
    'decentralized_coordination':('群体智能','蚁群','swarm','分布式','distributed','涌现','emergence'),
    'periodic_signal':('傅里叶','fourier','节奏','rhythm','周期','periodic'),
    'network_structure':('图论','graph theory','复杂网络','complex network','社会网络','social network'),
}


@lru_cache(maxsize=32768)
def lexical_tokens(text):
    lowered=str(text).casefold()
    words=set(re.findall(r'[a-z0-9]{2,}',lowered))
    for han in re.findall(r'[\u3400-\u9fff]+',lowered):
        words.update(han[i:i+2] for i in range(max(1,len(han)-1)))
    return frozenset(words)


@lru_cache(maxsize=16384)
def _concepts(text):
    text=text.casefold()
    def matches(alias):
        return bool(re.search(r'(?<![a-z])'+re.escape(alias)+r'(?![a-z])',text)) if alias.isascii() else alias in text
    return tuple(k for k,aliases in ALIASES.items() if any(matches(a) for a in aliases)),tuple(k for k,aliases in MECHANISMS.items() if any(matches(a) for a in aliases))


def describe(title,original_title=''):
    concepts,mechanisms=_concepts(title+' '+original_title)
    return {'version':VERSION,'concepts':list(concepts),'mechanisms':list(mechanisms)}


def similarity(first,second,enabled=True):
    left=lexical_tokens(first.get('title','')+' '+first.get('subfield',''))
    right=lexical_tokens(second.get('title','')+' '+second.get('subfield',''))
    lexical=len(left&right)/len(left|right) if left|right else 0.0
    if not enabled: return lexical
    def features(item):
        saved=item.get('semantic_features') or {}
        return saved if saved.get('version')==VERSION else describe(item.get('title',''),item.get('original_title',''))
    a,b=features(first),features(second)
    ac,bc=set(a['concepts']),set(b['concepts'])
    if ac and bc and ac==bc: return max(lexical,0.92)
    if ac&bc: return max(lexical,0.65)
    if set(a['mechanisms'])&set(b['mechanisms']): return max(lexical,0.50)
    return lexical
