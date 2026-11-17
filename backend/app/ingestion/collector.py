from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Awaitable

from .adapters import CachedHTTP, MediaWikiAdapter, WikidataAdapter, OpenAlexAdapter, SourceError

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / 'data/seeds/topics.json'


def taxonomy() -> list[dict]:
    return json.loads(SEED.read_text())['disciplines']


def canonical_id(raw: dict) -> str:
    """Cross-language IDs first; curated URL title mappings only for known seed entries.

    No fuzzy-title merging: similarly named independent entities remain separate.
    """
    titles = []
    if raw['platform'] == 'wikipedia':
        if raw['language'] == 'en':
            titles.append(raw['title'])
        titles.extend(x.get('title') or x.get('*') for x in raw.get('langlinks', []) if x.get('lang') == 'en')
    if raw['platform'] == 'wikidata':
        title = raw.get('sitelinks', {}).get('enwiki', {}).get('title')
        if title:
            titles.append(title)
    seeds = json.loads(SEED.read_text())['topics']
    for item in seeds:
        if item['original_title'] in titles:
            return item['id']
    if raw.get('entity_id'):
        return 'wd-' + raw['entity_id']
    return raw['platform'] + '-' + hashlib.sha256(raw['external_id'].encode()).hexdigest()[:20]


def normalize(raw: dict, discipline_id: str, *, mapping_basis: str = '用户提供的批次学科映射；非外部分类树') -> dict:
    allowed = {d['id'] for d in taxonomy()}
    if discipline_id not in allowed:
        raise ValueError('Unknown internal discipline')
    if not raw.get('url', '').startswith(('https://', 'http://')) or not raw.get('title'):
        raise SourceError('missing_metadata', '缺少可追溯链接或标题。')
    summary = raw.get('summary', '').strip()
    if not summary:
        raise SourceError('missing_content', '来源未提供摘要，不把标题扩写为事实。')
    tid = canonical_id(raw)
    zh = raw.get('language') == 'zh'
    safe_metadata = {k: v for k, v in raw.items() if k not in {'summary', 'api_key'}}
    safe_metadata['mapping_basis'] = mapping_basis
    if raw['platform'] == 'openalex' and raw['external_id'].startswith('T'):
        safe_metadata['upstream_ai_note'] = 'OpenAlex topic names/descriptions are upstream machine-generated cluster labels per official documentation.'
    return {'id': tid, 'title': raw['title'], 'original_title': raw['title'], 'summary': summary if zh else '英文原始资料（未自动翻译）：' + summary[:2000], 'original_summary': summary[:6000], 'language': raw['language'], 'primary_discipline_id': discipline_id, 'related_discipline_ids': [], 'subfield': (raw.get('subfield') or {}).get('display_name', '') if isinstance(raw.get('subfield'), dict) else '', 'question': '', 'value': '', 'quality_score': 0.6 if len(summary) < 100 else 0.7, 'quality_features': {'traceable_source': True, 'has_intro': len(summary) >= 100, 'has_example': False, 'metadata_complete': 0.7, 'prerequisite_load': 0.55, 'content_type': raw.get('content_type', 'reference'), 'summary_kind': 'source_original' if zh else 'english_source_original', 'summary_label': '来源原文；未自动补写教学内容', 'quality_basis': '可追溯元数据与摘要长度代理；未进行事实正确性判定。'}, 'mapping_basis': mapping_basis, 'sources': [{'platform': raw['platform'], 'external_id': raw['external_id'], 'url': raw['url'], 'title': raw['title'], 'language': raw['language'], 'license': raw['license'], 'fetched_at': raw['fetched_at'], 'updated_at': raw.get('updated_at'), 'version': raw.get('version'), 'content_hash': raw['content_hash'], 'excerpt': summary[:6000], 'metadata_json': safe_metadata}]}


async def collect(source: str, queries: list[str], limit: int = 20, *, discipline_id: str, language: str = 'zh', http: CachedHTTP | None = None, api_key: str | None = None, checkpoint: dict | None = None, on_progress: Callable[[dict, dict | None, dict | None], Awaitable[None]] | None = None) -> dict:
    """Bounded finite collection, checkpointed after each candidate and search.

    A failed candidate is saved and retried on resume. This function does not run an
    unbounded crawler, fetch arbitrary URLs, or call an LLM. A 300-item target needs
    sufficiently varied queries and authorized source access; it is not guaranteed.
    """
    if source not in {'wikipedia', 'wikidata', 'openalex'}:
        raise ValueError('Unknown source')
    if not 1 <= limit <= 300:
        raise ValueError('limit must be 1..300')
    if not queries or len(queries) > 30 or any(not x.strip() or len(x) > 250 for x in queries):
        raise ValueError('Supply 1..30 non-empty bounded queries')
    owned = http is None
    http = http or CachedHTTP(cache_dir=ROOT / 'data/cache/ingestion')
    adapter = MediaWikiAdapter(http, language) if source == 'wikipedia' else WikidataAdapter(http) if source == 'wikidata' else OpenAlexAdapter(http, api_key)
    state = {'queries': [], 'done': [], 'pending': [], **(checkpoint or {})}
    topics, errors, raw_relations, identity_map = {}, [], [], {}
    async def progress(topic=None, error=None):
        if on_progress:
            await on_progress(json.loads(json.dumps(state)), topic, error)
    try:
        # Interrupted searches or failed detail fetches are resumed from pending IDs.
        for query in queries:
            if query in state['queries']:
                continue
            try:
                hits = await adapter.search(query, min(100, limit))
                for hit in hits:
                    if hit['id'] not in state['done'] and hit['id'] not in state['pending']:
                        state['pending'].append(hit['id'])
                state['queries'].append(query)
                await progress()
            except SourceError as exc:
                err = {'phase': 'search', 'query': query, 'code': exc.code, 'message': exc.message}
                errors.append(err)
                await progress(error=err)
        for external_id in list(state['pending']):
            if len(state['done']) >= limit:
                break
            try:
                raw = await adapter.detail(external_id)
                topic = normalize(raw, discipline_id)
                # Within payload use exact canonical IDs. Cross-source alignment uses QIDs
                # and known cross-language sitelinks, never fuzzy title similarity.
                if topic['id'] in topics:
                    topics[topic['id']]['sources'].extend(topic['sources'])
                else:
                    topics[topic['id']] = topic
                raw_relations.extend(raw.get('relations', []))
                if raw.get('entity_id'):
                    identity_map[raw['entity_id']] = topic['id']
                state['done'].append(external_id)
                state['pending'].remove(external_id)
                await progress(topic=topic)
            except SourceError as exc:
                err = {'phase': 'detail', 'external_id': external_id, 'code': exc.code, 'message': exc.message}
                errors.append(err)
                await progress(error=err)
        return {'version': '1', 'data_kind': 'online', 'disciplines': taxonomy(), 'topics': list(topics.values()), 'relations': resolve_raw_relations(raw_relations, identity_map), 'raw_relations': raw_relations, 'errors': errors, 'checkpoint': state, 'status': 'partial' if errors else 'complete'}
    finally:
        if owned:
            await http.close()


def resolve_raw_relations(raw_relations: list[dict], identity_map: dict[str, str]) -> list[dict]:
    result = {}
    for r in raw_relations:
        a = identity_map.get(r['source_external_id'])
        b = identity_map.get(r['target_external_id'])
        if not a or not b or a == b:
            continue
        rid = hashlib.sha256(f"{a}|{r['property_id']}|{b}".encode()).hexdigest()[:32]
        result[rid] = {'id': rid, 'source_id': a, 'target_id': b, 'type': 'fact', 'property_id': r['property_id'], 'label': r['label'], 'direction': r['direction'], 'source_url': r['source_url'], 'explanation': f"Wikidata {r['property_id']} ({r['label']})，从主体指向客体；实体声明不自动保证适合作为教学桥梁。"}
    return list(result.values())
