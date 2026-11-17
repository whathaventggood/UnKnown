from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


class SourceError(Exception):
    """A safe error code; never include request URLs containing API credentials."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class CachedHTTP:
    """One reusable asynchronous client; conservative rate and retry limits per worker.

    Cache key excludes credentials; cache stores only successful public response bodies.
    A process lock serializes requests made by this instance. CLI uses one instance.
    """

    def __init__(self, *, client: httpx.AsyncClient | None = None, user_agent: str = "UnKnown/0.1 (self-hosted educational explorer)", cache_dir: Path | None = None, timeout: float = 15, retries: int = 2, min_interval: float = 1.05, ttl: int = 86400, trust_env: bool = False):
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout), headers={"User-Agent": user_agent}, follow_redirects=False, trust_env=trust_env)
        self.owned_client = client is None
        self.cache_dir, self.ttl = cache_dir, ttl
        self.retries, self.min_interval = min(3, max(0, retries)), max(0, min_interval)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def close(self):
        if self.owned_client:
            await self.client.aclose()

    async def get(self, url: str, params: dict[str, Any] | None = None) -> dict:
        public_params = {k: v for k, v in (params or {}).items() if k not in {"api_key", "access_token"}}
        key = hashlib.sha256((url + json.dumps(public_params, sort_keys=True)).encode()).hexdigest()
        cache = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if cache and cache.exists() and time.time() - cache.stat().st_mtime < self.ttl:
            try:
                return json.loads(cache.read_text())
            except (ValueError, OSError):
                pass
        async with self._lock:
            for attempt in range(self.retries + 1):
                await asyncio.sleep(max(0, self.min_interval - (time.monotonic() - self._last)))
                self._last = time.monotonic()
                try:
                    response = await self.client.get(url, params=params)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt < self.retries:
                        await asyncio.sleep(min(8, 2 ** attempt))
                        continue
                    raise SourceError("timeout" if isinstance(exc, httpx.TimeoutException) else "network", "来源暂时无法连接，已达到有限重试上限。") from None
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.retries:
                        retry_after = response.headers.get("Retry-After", "")
                        delay = min(30.0, float(retry_after)) if re.fullmatch(r"\d+(\.\d+)?", retry_after) else min(8, 2 ** attempt)
                        await asyncio.sleep(max(0, delay))
                        continue
                    raise SourceError("rate_limited" if response.status_code == 429 else "upstream", "来源限流或暂时不可用，任务可稍后恢复。")
                if response.status_code in {401, 403}:
                    raise SourceError("authentication", "来源拒绝访问，请核对服务端认证与访问政策。")
                if response.status_code != 200:
                    raise SourceError("http_error", f"来源返回 HTTP {response.status_code}。")
                try:
                    result = response.json()
                except ValueError:
                    raise SourceError("invalid_response", "来源没有返回合法 JSON。") from None
                if not isinstance(result, dict):
                    raise SourceError("invalid_response", "来源 JSON 顶层结构不正确。")
                if result.get("error"):
                    if isinstance(result["error"], dict) and result["error"].get("code") == "maxlag" and attempt < self.retries:
                        await asyncio.sleep(min(8, 2 ** attempt))
                        continue
                    raise SourceError("upstream_error", "来源报告 API 错误。")
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    temp = cache.with_suffix(".tmp")
                    temp.write_text(json.dumps(result, ensure_ascii=False))
                    temp.replace(cache)
                return result
        raise SourceError("upstream", "来源不可用。")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class MediaWikiAdapter:
    """Action API: public read-only metadata, categories and cross-language identity."""

    def __init__(self, http: CachedHTTP, language: str = "zh"):
        if language not in {"zh", "en"}:
            raise ValueError("Only zh/en Wikipedia are configured.")
        self.http, self.language = http, language
        self.endpoint = f"https://{language}.wikipedia.org/w/api.php"

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        data = await self.http.get(self.endpoint, {"action": "query", "list": "search", "srsearch": query[:250], "srlimit": min(50, max(1, limit)), "format": "json", "formatversion": 2, "maxlag": 5})
        query_data = data.get("query")
        result = query_data.get("search") if isinstance(query_data, dict) else None
        if not isinstance(result, list):
            raise SourceError("invalid_response", "Wikipedia 搜索结果结构不正确。")
        return [{"id": str(x["pageid"]), "title": x["title"]} for x in result if isinstance(x, dict) and "pageid" in x and "title" in x]

    async def detail(self, title_or_id: str) -> dict:
        locator = {"pageids": title_or_id} if title_or_id.isdigit() else {"titles": title_or_id}
        data = await self.http.get(self.endpoint, {"action": "query", "prop": "extracts|info|pageprops|categories|langlinks|revisions", "exintro": 1, "explaintext": 1, "inprop": "url", "cllimit": 30, "lllimit": 50, "rvprop": "ids|timestamp", "redirects": 1, "format": "json", "formatversion": 2, "maxlag": 5, **locator})
        query_data = data.get("query")
        pages = query_data.get("pages", []) if isinstance(query_data, dict) else []
        if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict) or pages[0].get("missing") or not isinstance(pages[0].get("extract"), str) or not pages[0].get("pageid") or not pages[0].get("title"):
            raise SourceError("missing_content", "Wikipedia 条目不存在或没有可解析的入门摘要。")
        p = pages[0]
        revision = (p.get("revisions") or [{}])[0]
        text = p["extract"][:10000]
        return {"platform": "wikipedia", "external_id": f"{self.language}:{p['pageid']}", "entity_id": p.get("pageprops", {}).get("wikibase_item"), "title": p["title"], "summary": text, "url": p.get("fullurl") or f"https://{self.language}.wikipedia.org/wiki/{quote(p['title'].replace(' ', '_'))}", "language": self.language, "categories": [x["title"] for x in p.get("categories", [])], "langlinks": p.get("langlinks", []), "version": str(revision["revid"]) if revision.get("revid") else None, "updated_at": revision.get("timestamp"), "fetched_at": _now(), "content_hash": _hash(text), "license": "CC BY-SA 4.0; Wikipedia contributors; verify page-specific exceptions"}


# Preserve direction and property semantics. A relation is not automatically a teaching bridge.
WIKIDATA_PROPERTIES = {"P31": "instance of", "P279": "subclass of", "P361": "part of", "P527": "has part", "P1269": "facet of", "P921": "main subject", "P101": "field of work"}


class WikidataAdapter:
    def __init__(self, http: CachedHTTP):
        self.http = http
        self.endpoint = "https://www.wikidata.org/w/api.php"

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        data = await self.http.get(self.endpoint, {"action": "wbsearchentities", "search": query[:250], "language": "zh", "uselang": "zh", "limit": min(50, max(1, limit)), "format": "json"})
        if not isinstance(data.get("search"), list):
            raise SourceError("invalid_response", "Wikidata 搜索结果结构不正确。")
        return [{"id": x["id"], "title": x.get("label", x["id"])} for x in data["search"] if isinstance(x, dict) and re.fullmatch(r"Q\d+", x.get("id", ""))]

    async def detail(self, entity_id: str) -> dict:
        if not re.fullmatch(r"Q\d+", entity_id):
            raise ValueError("Invalid Wikidata entity ID")
        data = await self.http.get(self.endpoint, {"action": "wbgetentities", "ids": entity_id, "props": "labels|descriptions|claims|sitelinks", "languages": "zh|en", "format": "json"})
        entities = data.get("entities")
        entity = entities.get(entity_id, {}) if isinstance(entities, dict) else {}
        if not isinstance(entity, dict) or entity.get("missing") is not None or not entity:
            raise SourceError("missing_content", "Wikidata 实体不存在。")
        labels, descriptions = entity.get("labels", {}), entity.get("descriptions", {})
        lang = "zh" if "zh" in labels else "en"
        title = labels.get(lang, {}).get("value", entity_id)
        summary = descriptions.get(lang, {}).get("value", "")
        relations = []
        for prop, label in WIKIDATA_PROPERTIES.items():
            for claim in entity.get("claims", {}).get(prop, []):
                if claim.get("rank") == "deprecated":
                    continue
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(value, dict) and re.fullmatch(r"Q\d+", value.get("id", "")):
                    relations.append({"source_external_id": entity_id, "target_external_id": value["id"], "property_id": prop, "label": label, "direction": "forward", "type": "fact", "statement_id": claim.get("id"), "references": claim.get("references", []), "source_url": f"https://www.wikidata.org/wiki/{entity_id}#{prop}"})
        return {"platform": "wikidata", "external_id": entity_id, "entity_id": entity_id, "title": title, "summary": summary, "url": f"https://www.wikidata.org/wiki/{entity_id}", "language": lang, "version": str(entity["lastrevid"]) if entity.get("lastrevid") else None, "updated_at": entity.get("modified"), "fetched_at": _now(), "content_hash": _hash(json.dumps({"labels": labels, "descriptions": descriptions, "relations": relations}, sort_keys=True)), "license": "CC0 1.0", "relations": relations, "sitelinks": entity.get("sitelinks", {})}


class OpenAlexAdapter:
    """Only topics and work metadata; never downloads manuscript full text."""

    def __init__(self, http: CachedHTTP, api_key: str | None = None):
        self.http, self.api_key = http, api_key
        self._records = {}
        self.last_meta = {}
        self.endpoint = "https://api.openalex.org"

    def _params(self, values: dict) -> dict:
        return {**values, **({"api_key": self.api_key} if self.api_key else {})}

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        data = await self.http.get(f"{self.endpoint}/topics", self._params({"search": query[:250], "per_page": min(100, max(1, limit))}))
        if not isinstance(data.get("results"), list):
            raise SourceError("invalid_response", "OpenAlex 搜索结果结构不正确。")
        self.last_meta = data.get("meta", {})
        valid = [x for x in data["results"] if isinstance(x, dict) and re.fullmatch(r"https://openalex.org/T\d+", x.get("id", "")) and x.get("display_name")]
        self._records.update({x["id"].rsplit("/", 1)[-1]: x for x in valid})
        return [{"id": x["id"].rsplit("/", 1)[-1], "title": x["display_name"]} for x in valid]

    async def detail(self, entity_id: str) -> dict:
        if not re.fullmatch(r"[TW]\d+", entity_id):
            raise ValueError("Invalid OpenAlex topic/work ID")
        kind = "topics" if entity_id.startswith("T") else "works"
        data = self._records.get(entity_id) or await self.http.get(f"{self.endpoint}/{kind}/{entity_id}", self._params({}))
        if not data.get("id") or not data.get("display_name"):
            raise SourceError("invalid_response", "OpenAlex 元数据缺少标识或名称。")
        text = data.get("description", "")
        if kind == "works" and isinstance(data.get("abstract_inverted_index"), dict):
            words = sorted((pos, word) for word, positions in data["abstract_inverted_index"].items() for pos in positions)
            text = " ".join(word for _, word in words)[:10000]
        location = data.get("primary_location") or {}
        return {"platform": "openalex", "external_id": entity_id, "entity_id": None, "title": data["display_name"], "summary": text, "url": data["id"], "original_url": data.get("doi") or location.get("landing_page_url"), "language": data.get("language") or "en", "updated_at": data.get("updated_date"), "fetched_at": _now(), "version": None, "content_hash": _hash(text + data["display_name"]), "license": "CC0 1.0 (bibliographic metadata only); abstract and full text may have independent rights", "domain": data.get("domain"), "field": data.get("field"), "subfield": data.get("subfield"), "primary_topic": data.get("primary_topic"), "authors": [x.get("author", {}).get("display_name") for x in data.get("authorships", [])][:30], "publication_year": data.get("publication_year"), "doi": data.get("doi"), "content_type": "research_metadata"}
