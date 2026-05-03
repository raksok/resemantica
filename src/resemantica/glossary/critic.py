from __future__ import annotations

from typing import Any

import numpy as np

from resemantica.glossary.models import GlossaryCandidate

# Reference vocabulary of common Chinese words that should never be glossary terms.
# These are frequently misidentified by LLMs during discovery.
_REFERENCE_VOCABULARY: list[str] = [
    # Dates and time expressions
    "一月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "十一月", "十二月",
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "今天", "明天", "昨天", "早上", "中午", "晚上",
    "今年", "明年", "去年",
    "春天", "夏天", "秋天", "冬天",
    "上午", "下午", "现在", "以前", "以后",
    # Common nouns
    "学校", "教室", "医院", "家里", "地方",
    "时候", "时间", "小时", "分钟",
    "面前", "身后", "眼前", "心中", "手上", "脚下", "身上",
    "门口", "窗外", "路边", "空中", "地上",
    # Discourse and function words
    "这时", "那时", "此时", "此刻",
    "突然", "忽然", "虽然", "但是", "因为", "所以", "如果",
    "已经", "还是", "就是", "这个", "那个", "什么", "怎么",
    "我们", "你们", "他们", "自己", "别人",
    "知道", "发现", "觉得", "想到", "看到", "听到", "说道",
    "起来", "出来", "过来", "回来",
    "没有", "不是", "可以", "能够", "应该",
    # Numerals and quantifiers
    "一个", "一些", "一点", "很多", "很少", "几个",
    "第一", "第二", "最后", "每次", "每个",
    "所有", "全部", "部分",
    # Generic actions
    "说道", "笑道", "问道", "回答", "点头", "摇头",
    "离开", "来到", "走向", "进入", "回到",
    "看到", "听到", "感到", "想到",
]

_cached_model: Any = None
_cached_ref_embeddings: Any = None


def _get_model_and_embeddings(model_name: str):
    global _cached_model, _cached_ref_embeddings
    if _cached_model is not None and _cached_ref_embeddings is not None:
        return _cached_model, _cached_ref_embeddings
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
    _cached_model = SentenceTransformer(model_name)
    _cached_model.encode("x")  # warm up
    ref_texts = [f"{term} [common]" for term in _REFERENCE_VOCABULARY]
    _cached_ref_embeddings = _cached_model.encode(ref_texts, normalize_embeddings=True)
    return _cached_model, _cached_ref_embeddings


def compute_critic_scores(
    candidates: list[GlossaryCandidate],
    *,
    model_name: str = "BAAI/bge-m3",
    pruning_threshold: float = 0.3,
) -> list[GlossaryCandidate]:
    try:
        model, ref_embeddings = _get_model_and_embeddings(model_name)
    except ImportError:
        return candidates

    to_score = [(i, c) for i, c in enumerate(candidates) if c.candidate_status == "discovered"]
    if not to_score:
        return candidates

    indices, scored_candidates = zip(*to_score)
    texts = [f"{c.source_term} [{c.category}]" for c in scored_candidates]
    embeddings = model.encode(texts, normalize_embeddings=True)

    for idx, candidate, emb in zip(indices, scored_candidates, embeddings):
        sims = np.dot(ref_embeddings, emb)
        max_sim = float(sims.max())
        score = 1.0 - max_sim
        candidate.critic_score = round(score, 4)
        if pruning_threshold > 0 and score < pruning_threshold:
            candidate.candidate_status = "pruned"
            candidate.validation_status = "pending"
            candidate.conflict_reason = f"critic_pruned: score={score:.4f}"

    return candidates
