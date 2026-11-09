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
    ranks, objects = {}, {}
    for ranking in (dense[:width], lexical):
        for rank, point in enumerate(ranking, 1):
            key = str(point.id)
            objects[key] = point
            ranks[key] = ranks.get(key, 0) + 1 / (60 + rank)
    ordered = sorted(ranks, key=lambda key: (-ranks[key], key))[:top_k]
    return [SimpleNamespace(payload=objects[k].payload, score=ranks[k]) for k in ordered], {
        "method": "dense-bm25-rrf",
        "collections": reports,
        "lexical_scanned": sum(r["lexical_scanned"] for r in reports),
        "lexical_scan_limit": SCAN_LIMIT * len(collections),
        "lexical_scan_truncated": any(r["lexical_scan_truncated"] for r in reports),
        "claim_support_verified": False,
    }
