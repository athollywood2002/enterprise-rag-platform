"""Bounded lexical candidate retrieval over managed, committed revisions only.

No extra index/service. RRF combines dense ranks with BM25 passage ranks. The
scan ceiling is explicit evidence, not a claim of exhaustive corpus coverage.
"""

import math
import re
from collections import Counter
from types import SimpleNamespace

SCAN_LIMIT = 5000


def tokens(text):
    return re.findall(r"\w+", text.casefold())


def lexical_rank(question, points):
    query = set(tokens(question))
    bags = [Counter(tokens(p.payload.get("text", ""))) for p in points]
    lengths = [sum(b.values()) for b in bags]
    average = sum(lengths) / max(len(lengths), 1) or 1
    frequencies = Counter(t for bag in bags for t in query if t in bag)
    scored = []
    for p, bag, length in zip(points, bags, lengths, strict=True):
        score = sum(
            math.log(1 + (len(bags) - frequencies[t] + 0.5) / (frequencies[t] + 0.5))
            * bag[t]
            * 2.2
            / (bag[t] + 1.2 * (0.25 + 0.75 * length / average))
            for t in query
            if bag[t]
        )
        if score:
            scored.append((score, p))
    return [p for _, p in sorted(scored, key=lambda x: (-x[0], str(x[1].id)))]


def row_rank(question, points):
    """An extra RRF lane for exact named rows AND requested column labels.

    No corpus-specific names or query rewriting. Multiword cell values/identifiers
    must occur verbatim (token boundaries); short generic values are not entities.
    This lane uses the same bounded, committed candidate pool as BM25.
    """

    def terms(text):
        return [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens(text)]

    query = terms(question)
    query_set = set(query)
    ranked = []
    for point in points:
        data = point.payload
        if data.get("row_kind") != "data" or data.get("continuation"):
            continue
        fields = set(terms(" ".join(data.get("column_labels", [])))) & query_set
        fields = {t for t in fields if len(t) > 2}
        if not fields:
            continue
        matches = []
        for value in data.get("row_entities", []):
            words = terms(value)
            if len(words) < 2 and not re.search(r"[A-Za-z]+[-_]\d", value):
                continue
            if words and any(query[i : i + len(words)] == words for i in range(len(query))):
                matches.append(len(words))
        if matches:
            ranked.append((len(fields), max(matches), point))
    return [p for _, _, p in sorted(ranked, key=lambda v: (-v[0], -v[1], str(v[2].id)))]


def managed_candidates(db, collection, question, dense, query_filter, top_k):
    # A managed point ID identifies a revision/chunk globally, independent of its
    # parser collection. Never compare fusion scores calculated in separate pools.
    collections = [collection] if isinstance(collection, str) else sorted(set(collection))
    candidates, reports = {}, []
    for name in collections:
        scanned, offset = 0, None
        while scanned < SCAN_LIMIT:
            page, offset = db.scroll(
                collection_name=name,
                scroll_filter=query_filter,
                limit=min(256, SCAN_LIMIT - scanned),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            scanned += len(page)
            candidates.update((str(p.id), p) for p in page)
            if offset is None:
                break
        reports.append(
            {
                "collection": name,
                "lexical_scanned": scanned,
                "lexical_scan_limit": SCAN_LIMIT,
                "lexical_scan_truncated": offset is not None,
            }
        )
    width = max(20, top_k * 4)
    # Scores are comparable here because managed collections share the same
    # embedding identity and distance configuration. Rank once after pooling.
    dense = sorted(dense, key=lambda p: (-getattr(p, "score", 0), str(p.id)))
    dense = list({str(p.id): p for p in reversed(dense)}.values())
    dense.sort(key=lambda p: (-getattr(p, "score", 0), str(p.id)))
    lexical = lexical_rank(question, list(candidates.values()))[:width]
    structured = row_rank(question, list(candidates.values()))[:width]
    ranks, objects = {}, {}
    for ranking in (dense[:width], lexical, structured):
        for rank, point in enumerate(ranking, 1):
            key = str(point.id)
            objects[key] = point
            ranks[key] = ranks.get(key, 0) + 1 / (60 + rank)
    ordered = sorted(ranks, key=lambda key: (-ranks[key], key))[:top_k]
    return [SimpleNamespace(payload=objects[k].payload, score=ranks[k]) for k in ordered], {
        "method": "dense-bm25-rrf",
        "structured_row_candidates": len(structured),
        "ranking_lanes": ["dense", "bm25", "named-row-fields"],
        "collections": reports,
        "lexical_scanned": sum(r["lexical_scanned"] for r in reports),
        "lexical_scan_limit": SCAN_LIMIT * len(collections),
        "lexical_scan_truncated": any(r["lexical_scan_truncated"] for r in reports),
        "claim_support_verified": False,
    }
