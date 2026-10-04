"""Query intent detection, explainable result scoring, and re-ranking.

纯逻辑模块，不发起网络请求，便于离线测试。评分基于 title / url / snippet
中完整实体的命中情况，叠加“官方/全文”等显式意图与页面具体性信号；
每条结果保留打分理由，避免不可解释的黑盒排序。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

# 拉丁词（允许连字符/点/下划线，保留 agent-browser、session-name 等完整实体）
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+/-]*")
# 连续 CJK 片段
_CJK_RUN_RE = re.compile(r"[一-鿿぀-ヿ가-힣]+")
_QUOTED_RE = re.compile(r'"([^"]+)"')

_OFFICIAL_HINTS = (
    "官方", "官网", "official", "documentation", "docs", "全文", "manual", "reference",
)

# 可信“官方/文档”身份信号：只看标题写“官方”不算数，需要域名依据
_DOC_HOST_PREFIXES = ("docs.", "developer.", "devdocs.", "learn.", "wiki.", "help.")
_DOC_HOST_KEYWORDS = ("readthedocs", "gitbook", "github.io", "wikipedia", "mozilla")
_GOV_EDU_SUFFIXES = (".gov.cn", ".gov", ".edu.cn", ".edu", ".ac.cn")

# 与“能直接回答问题”匹配的最低分（打分理由可解释，阈值固定）
MIN_TOP_SCORE = 4.0

_COMMON_WORDS = {
    "the", "a", "an", "of", "to", "in", "for", "and", "or", "how", "what", "is",
    "use", "using", "with", "generate", "handling",
}


@dataclass
class ScoredResult:
    item: dict
    score: float
    reasons: list[str] = field(default_factory=list)


def extract_entities(query: str) -> list[str]:
    """提取有辨识度的实体词：引号短语 > 含连字符/点的术语 > 普通词 > CJK 片段。

    短术语（uv、go）也是核心实体，不能按长度丢弃；匹配时用词边界防止
    "uv" 命中 "uvi.today" 这类噪声。CJK 长片段切成 bigram 作为子实体。
    """
    entities: list[str] = []

    quoted = _QUOTED_RE.findall(query)
    entities.extend(q.strip() for q in quoted if q.strip())

    rest = _QUOTED_RE.sub(" ", query)

    latin = _LATIN_TOKEN_RE.findall(rest)
    # 复合术语（含 - . _ /）辨识度最高，整词保留，不拆散
    compound = [t for t in latin if len(t) >= 3 and re.search(r"[-._/]", t)]
    entities.extend(compound)
    plain = [
        t.lower()
        for t in latin
        if t not in compound and len(t) >= 2 and t.lower() not in _COMMON_WORDS
    ]
    entities.extend(plain)

    for run in _CJK_RUN_RE.findall(rest):
        if len(run) <= 4:
            entities.append(run)
        else:
            entities.extend(run[i : i + 2] for i in range(len(run) - 1))

    # 保序去重
    return list(dict.fromkeys(entities))


def detect_intent(query: str) -> set[str]:
    """识别显式意图标记（官方/文档/全文），用于排序加权。"""
    lower = query.lower()
    intents: set[str] = set()
    if any(h in lower for h in _OFFICIAL_HINTS):
        intents.add("official")
    if len(extract_entities(query)) >= 3:
        intents.add("specific")
    return intents


def _host_looks_official(host: str, entities: list[str]) -> bool:
    if host.startswith(_DOC_HOST_PREFIXES):
        return True
    if any(k in host for k in _DOC_HOST_KEYWORDS):
        return True
    if host.endswith(_GOV_EDU_SUFFIXES):
        return True
    # 域名中包含核心实体（如 astral.sh 之于 uv 的官方站需另证，此处只认强匹配）
    for ent in entities:
        ent_clean = re.sub(r"[^a-z0-9]", "", ent.lower())
        if len(ent_clean) >= 4 and ent_clean in host.replace("-", "").replace(".", ""):
            return True
    return False


def _entity_in_text(entity: str, text_lower: str) -> bool:
    """实体命中判断：短拉丁实体用词边界，避免 uv 命中 uvi.today。"""
    ent = entity.lower()
    if len(ent) <= 3 and ent.isascii():
        return (
            re.search(r"(?<![a-z0-9])" + re.escape(ent) + r"(?![a-z0-9])", text_lower)
            is not None
        )
    return ent in text_lower


def _matched_ratio(entities: list[str], text: str) -> float:
    if not entities:
        return 0.0
    lower = text.lower()
    hits = sum(1 for ent in entities if _entity_in_text(ent, lower))
    return hits / len(entities)


def score_result(item: dict, entities: list[str], intents: set[str]) -> ScoredResult:
    """对单条搜索结果打分，理由保存在 reasons 中。"""
    title = str(item.get("title", ""))
    url = str(item.get("url", ""))
    snippet = str(item.get("content", ""))

    parsed = urlparse(url)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    path = parsed.path.rstrip("/")

    score = 0.0
    reasons: list[str] = []

    title_ratio = _matched_ratio(entities, title)
    url_ratio = _matched_ratio(entities, url)
    snippet_ratio = _matched_ratio(entities, snippet)
    score += 3.0 * title_ratio + 2.0 * url_ratio + 1.0 * snippet_ratio
    if title_ratio:
        reasons.append(f"title命中{title_ratio:.0%}实体")
    if url_ratio:
        reasons.append(f"url命中{url_ratio:.0%}实体")

    # 查询实体在结果各字段中全覆盖：很可能能直接回答问题
    all_text = f"{title} {url} {snippet}".lower()
    if entities and all(_entity_in_text(ent, all_text) for ent in entities):
        score += 2.0
        reasons.append("实体全覆盖")

    if "official" in intents and _host_looks_official(host, entities):
        score += 2.0
        reasons.append("官方/文档域名信号")

    # 具体性：查询意图明确时，有路径深度的专题页优于裸首页；
    # 但不无条件贬低首页（有些任务目标就是首页）
    is_homepage = path == ""
    if "specific" in intents or "official" in intents:
        if is_homepage:
            score -= 0.5
            reasons.append("首页降权")
        elif len([p for p in path.split("/") if p]) >= 2:
            score += 0.5
            reasons.append("专题页加权")

    return ScoredResult(item=item, score=score, reasons=reasons)


def rerank_results(
    results: list[dict],
    query: str,
    *,
    max_per_host: int = 2,
) -> list[ScoredResult]:
    """打分、降序排序，并做同站多样性限制（超出名额的结果沉底，不删除）。"""
    entities = extract_entities(query)
    intents = detect_intent(query)
    scored = [score_result(item, entities, intents) for item in results]
    scored.sort(key=lambda s: s.score, reverse=True)

    if max_per_host <= 0:
        return scored

    kept: list[ScoredResult] = []
    overflow: list[ScoredResult] = []
    host_counts: dict[str, int] = {}
    for s in scored:
        host = urlparse(str(s.item.get("url", ""))).netloc.lower()
        count = host_counts.get(host, 0)
        host_counts[host] = count + 1
        if count < max_per_host:
            kept.append(s)
        else:
            overflow.append(s)
    return kept + overflow


def has_sufficient_quality(ranked: list[ScoredResult], limit: int) -> bool:
    """判断首轮结果是否足够：数量达标且最高分达到“直接相关”阈值。"""
    if len(ranked) < limit or not ranked:
        return False
    return ranked[0].score >= MIN_TOP_SCORE


def build_variant_query(query: str) -> str | None:
    """为补搜生成一个保守变体：把高辨识度拉丁实体加引号精确匹配。

    复合术语优先，其后短术语（uv、pip 等产品名比 documentation 这类
    泛词更能定位目标）。意图词（official/docs/全文）不是实体，不参与变体。
    已含引号、实体不足两个、或纯 CJK 查询时不生成变体。
    """
    if _QUOTED_RE.search(query):
        return None
    intent_words = {w.lower() for w in _OFFICIAL_HINTS} | _COMMON_WORDS
    latin = _LATIN_TOKEN_RE.findall(query)
    distinctive = [
        t
        for t in latin
        if len(t) >= 2 and t.lower() not in intent_words
    ]
    # 复合术语优先，其次短术语（产品名通常比泛词短而具体）
    distinctive.sort(key=lambda t: (not re.search(r"[-._/]", t), len(t)))
    picked = list(dict.fromkeys(distinctive))[:3]
    if len(picked) < 2:
        return None
    return " ".join(f'"{t}"' for t in picked)
