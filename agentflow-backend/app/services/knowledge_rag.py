"""知识库切分与检索（R5）：切块 + BM25 + 可选 MMR 去冗余。

检索算法选择：
- 中文没有空格，用字符 bigram 建索引（`知识库` → `知识`, `识库`），比按字切更准，
  也不需要引入分词词典；
- 英文/数字按词切；
- BM25 的 idf 用标准公式，k1=1.2 / b=0.75，小语料里足够区分「专有名词」和「的/是」；
- rerank 不做模型重排，而是 MMR：先按 BM25 取 3 倍候选，再挑「与已选片段重复度低」的，
  目的就是把同一段话的多份重复块去掉，零成本、结果可复现。
"""
import math
import re
import time
from collections import Counter

_LATIN = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def chunk_text(text: str, size: int = 400, overlap: int = 50) -> list[str]:
    """按句切、按字数打包；超长句硬切并带 overlap。

    不做「固定字符窗口」：那样会把一句话劈开，检索出来的片段读不懂。
    """
    normalized = re.sub(r"\r\n", "\n", text).strip()
    if not normalized:
        return []
    size = max(50, int(size))
    overlap = max(0, min(int(overlap), size // 2))

    segments = [seg.strip() for seg in _SENTENCE_SPLIT.split(normalized) if seg.strip()]
    chunks: list[str] = []
    current = ""

    def flush(value: str) -> None:
        if value.strip():
            chunks.append(value.strip())

    for segment in segments:
        while len(segment) > size:
            # 超长句子：先切一段，余下部分带上 overlap 继续
            head = segment[:size]
            flush(current + head if current else head)
            tail_start = max(0, len(head) - overlap)
            segment = segment[tail_start:]
            current = ""
        if len(current) + len(segment) <= size:
            current += segment
        else:
            flush(current)
            current = (current[-overlap:] if overlap and current else "") + segment
    flush(current)
    return chunks


def tokenize(text: str) -> list[str]:
    lower = (text or "").lower()
    tokens = _LATIN.findall(lower)
    for run in _CJK_RUN.findall(lower):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _bm25_scores(query: str, docs: list[list[str]]) -> list[float]:
    query_terms = list(dict.fromkeys(tokenize(query)))
    if not docs or not query_terms:
        return [0.0] * len(docs)

    lengths = [max(1, len(doc)) for doc in docs]
    avg_len = sum(lengths) / len(lengths)
    doc_freq: Counter[str] = Counter()
    for doc in docs:
        seen = {term for term in query_terms if term in doc}
        doc_freq.update(seen)

    total = len(docs)
    k1, b = 1.2, 0.75
    scores: list[float] = []
    for doc, doc_len in zip(docs, lengths):
        tf = Counter(doc)
        score = 0.0
        for term in query_terms:
            freq = tf.get(term, 0)
            if not freq:
                continue
            df = doc_freq.get(term, 0) or 1
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * doc_len / avg_len))
        scores.append(score)
    return scores


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def search_chunks(query: str, chunks: list[dict], top_k: int = 4, rerank: bool = False) -> tuple[list[dict], int]:
    """chunks 形如 [{doc_id,title,seq,text}]，返回 (带 score 的结果, took_ms)。"""
    started = time.perf_counter()
    if not chunks:
        return [], int((time.perf_counter() - started) * 1000)

    texts = [item["text"] for item in chunks]
    docs = [tokenize(text) for text in texts]
    scores = _bm25_scores(query, docs)

    ranked = sorted(range(len(chunks)), key=lambda index: (-scores[index], index))
    candidate_count = min(len(ranked), max(top_k * 3, top_k))
    candidates = ranked[:candidate_count]

    if rerank and len(candidates) > 1:
        selected: list[int] = []
        remaining = list(candidates)
        while remaining and len(selected) < top_k:
            best_index = remaining[0]
            best_value = -1.0
            selected_tokens = set().union(
                *(set(docs[index]) for index in selected)
            ) if selected else set()
            for index in remaining:
                # MMR：0.7 保留相关性，0.3 惩罚与已选内容重复
                value = 0.7 * scores[index] - 0.3 * _jaccard(set(docs[index]), selected_tokens)
                if value > best_value:
                    best_value, best_index = value, index
            selected.append(best_index)
            remaining.remove(best_index)
        ordered = selected
    else:
        ordered = candidates[:top_k]

    results = [
        {**chunks[index], "score": round(float(scores[index]), 4)}
        for index in ordered
        if scores[index] > 0
    ]
    # 全零时（查询词都没命中）不要硬凑结果，交给上层给「没命中」的提示
    return results, int((time.perf_counter() - started) * 1000)
