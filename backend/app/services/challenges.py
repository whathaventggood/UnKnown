"""Voluntary source-based reference comparison, available without LLM/key/network.

Keyword hints are shown as lexical cues, never correctness or mastery scores.
Reference answers retain their editorial origin and source passage provenance.
"""
import hashlib
import json
from sqlalchemy import select
from app.models import TopicSource
from app.services.content import source_fingerprint

VERSION='reference-check-1'
CURATED={
    'graph-theory':('地铁站点之间什么时候应该画一条边？请说明图中的节点、边以及边的具体含义。',['节点表示对象，边表示关系。','边的含义取决于建模的问题。'],[['节点','顶点'],['边','连接','关系'],['含义','建模','问题']]),
    'bayes':('检测阳性为什么不等于患病概率很高？用条件概率的方向解释。',['需要区分“患病时阳性”与“阳性时患病”。','需要考虑先验发生率和新证据。'],[['条件','方向'],['先验','基础','发生率'],['证据','更新']]),
    'epigenetics':('基因表达改变，是否就能断定 DNA 序列发生了变化？请解释。',['表观遗传关注不改变 DNA 序列的表达变化。'],[['表达'],['序列','DNA','dna'],['不','未']]),
    'opportunity':('选择一件事时，机会成本为什么不是所有放弃选项的简单总和？',['机会成本关注被放弃的最佳替代方案的价值。'],[['最佳','最好','最优'],['替代','放弃']]),
    'dark-matter':('观测到引力效应，是否就已经确定了暗物质的粒子组成？',['暗物质仍是有开放问题的推断，观测不直接确定具体粒子组成。'],[['观测','引力'],['未','不','假设','推断','开放']]),
}


def challenge_for(db,topic,*,reveal=False):
    sources=list(db.scalars(select(TopicSource).where(TopicSource.topic_id==topic.id).order_by(TopicSource.id)))
    usable=[s for s in sources if len(s.excerpt.strip())>=8]
    if topic.content_status!='PUBLISHED' or not usable:
        return {'status':'unavailable','message':'现有入门材料或来源片段不足，暂不生成挑战。','challenge':None}
    if topic.id in CURATED:
        prompt,points,keywords=CURATED[topic.id]
    else:
        prompt=f'请用自己的话回答：{topic.question or "这个概念是什么？"} 再指出一个现有资料没有回答的问题。'
        points=[topic.content_intro.get('one_sentence') or topic.summary]
        keywords=[]
    version=source_fingerprint(topic,sources)
    cid=hashlib.sha256((topic.id+'|'+version+'|'+VERSION).encode()).hexdigest()
    challenge={'id':cid,'topic_id':topic.id,'prompt':prompt,'kind':'reference_comparison',
        'reference_answer':topic.content_intro.get('explanation') or topic.summary if reveal else None,
        'key_points':points if reveal else [],'keywords':keywords if reveal else [],
        'reference_origin':'existing_editorial_not_expert_verified','source_fingerprint':version,
        'evidence_refs':[{'source_id':s.id,'quote':s.excerpt[:1500],'evidence_type':'external_excerpt'} for s in usable] if reveal else [],
        'sources':[{'id':s.id,'url':s.url,'title':s.title,'license':s.license} for s in usable],
        'limits':'参考答案是入门整理材料。字词匹配和自述均不能证明推理正确或长期掌握；可自行核对原始来源。'}
    return {'status':'ready','message':'自愿自测，无需 AI。提交后对照参考，不自动判分。','challenge':challenge}


def reference_feedback(challenge,answer):
    cues=[]
    for alternatives in challenge['keywords']:
        cues.append({'terms':alternatives,'mentioned':any(term.casefold() in answer.casefold() for term in alternatives)})
    return {'kind':'reference_comparison','ai_used':False,'score':None,'correctness':'not_automatically_determined',
            'message':'回答已保存。请对照参考要点检查概念和推理；下面只识别出现的词语，不判定回答正确。',
            'reference':challenge,'lexical_cues':cues}


def attempt_json(attempt):
    return {k:getattr(attempt,k) for k in ('id','topic_id','challenge_id','answer','feedback','self_assessment','created_at')}
