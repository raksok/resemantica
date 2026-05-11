from __future__ import annotations

import json
from typing import Any

import numpy as np
from loguru import logger

from resemantica.glossary.models import AliasCluster, GlossaryCandidate, LockedGlossaryEntry

_cached_model: Any = None


def _get_model(model_name: str) -> Any:
    global _cached_model
    if _cached_model is not None:
        return _cached_model
    logger.info("Loading sentence-transformers model '{}' for alias clustering...", model_name)
    from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    _cached_model = SentenceTransformer(model_name)
    _cached_model.encode("x")  # warm up
    logger.info("Embedding model loaded successfully.")
    return _cached_model


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, i: int) -> int:
        if self.parent[i] != i:
            self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: int, j: int) -> None:
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            if self.rank[root_i] < self.rank[root_j]:
                self.parent[root_i] = root_j
            elif self.rank[root_i] > self.rank[root_j]:
                self.parent[root_j] = root_i
            else:
                self.parent[root_j] = root_i
                self.rank[root_i] += 1


def deduplicate_and_cluster(
    candidates: list[GlossaryCandidate],
    *,
    model_name: str,
    existing_entries: list[LockedGlossaryEntry] | None = None,
    similarity_threshold: float = 0.85,
) -> tuple[list[GlossaryCandidate], list[AliasCluster]]:
    """
    1. Embed each candidate as "{surface} [{category}] {context_snippet}"
    2. Compute pairwise cosine similarity
    3. Union-Find clustering: merge pairs above similarity_threshold
    4. For each cluster: pick highest-scored candidate as canonical,
       mark others as aliases (candidate_status = "alias_merged")
    5. Compare canonical terms against existing_entries embeddings
       to flag re-discoveries of already-locked terms
    6. Return (deduplicated_candidates, alias_clusters)
    """
    try:
        model = _get_model(model_name)
    except ImportError:
        logger.warning("sentence-transformers not installed, skipping alias clustering")
        return candidates, []

    to_cluster = [c for c in candidates if c.candidate_status == "discovered" or c.candidate_status == "translated"]
    if not to_cluster:
        logger.debug("No candidates eligible for clustering")
        return candidates, []

    # 1. Embed candidates
    texts = []
    for c in to_cluster:
        snippet = ""
        if c.context_snippets:
            try:
                snips = json.loads(c.context_snippets)
                if snips:
                    snippet = snips[0]
            except Exception:
                pass
        category = c.category if c.category else "unknown"
        texts.append(f"{c.source_term} [{category}] {snippet}")

    embeddings = model.encode(texts, normalize_embeddings=True)
    logger.debug("Embedded {} candidates for clustering (threshold={:.2f})", len(to_cluster), similarity_threshold)

    # 2 & 3. Compute pairwise similarity and Union-Find
    n = len(to_cluster)
    uf = UnionFind(n)

    # Optional: can optimize by not doing full N^2 if N is large,
    # but usually candidates per chapter/batch are small (~100-1000)
    # Using matrix multiplication for cosine similarity (since embeddings are normalized)
    sim_matrix = np.dot(embeddings, embeddings.T)

    # To keep track of pairwise similarities that caused merges
    # we'll store the max similarity to any other member for each item
    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i, j] >= similarity_threshold:
                uf.union(i, j)

    # 4. Extract clusters and pick canonical
    clusters_map: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        if root not in clusters_map:
            clusters_map[root] = []
        clusters_map[root].append(i)

    alias_clusters: list[AliasCluster] = []

    # Embed existing entries if any
    existing_embeddings = None
    if existing_entries:
        ex_texts = [f"{e.source_term} [{e.category}]" for e in existing_entries]
        existing_embeddings = model.encode(ex_texts, normalize_embeddings=True)

    for root, members in clusters_map.items():
        if len(members) == 1:
            # Single item cluster, no aliases
            c_idx = members[0]
            canonical = to_cluster[c_idx]

            # Still check against existing entries
            match_id = None
            if existing_embeddings is not None and existing_entries is not None:
                sims = np.dot(existing_embeddings, embeddings[c_idx])
                best_idx = int(np.argmax(sims))
                if sims[best_idx] >= similarity_threshold:
                    match_id = existing_entries[best_idx].glossary_entry_id

            if match_id:
                canonical.candidate_status = "pruned"
                canonical.validation_status = "pending"
                canonical.conflict_reason = f"already_exists:{match_id}"

            continue

        # Multi-item cluster
        # Find canonical: highest corpus_score (or appearance count if missing)
        members_sorted = sorted(
            members,
            key=lambda i: (to_cluster[i].corpus_score or 0.0, to_cluster[i].appearance_count or 0),
            reverse=True
        )

        canon_idx = members_sorted[0]
        canonical = to_cluster[canon_idx]

        alias_texts = []
        member_ids = []

        # Calculate cluster similarity score (average of similarities to canonical)
        total_sim = 0.0
        for idx in members_sorted[1:]:
            sim = sim_matrix[canon_idx, idx]
            total_sim += sim
            alias = to_cluster[idx]
            alias.candidate_status = "alias_merged"
            alias.validation_status = "pending"
            alias.conflict_reason = f"merged_into:{canonical.candidate_id}"

            if alias.source_term not in alias_texts and alias.source_term != canonical.source_term:
                alias_texts.append(alias.source_term)
            member_ids.append(alias.candidate_id)

        member_ids.insert(0, canonical.candidate_id) # canonical is also a member
        avg_sim = total_sim / (len(members) - 1)

        match_id = None
        if existing_embeddings is not None and existing_entries is not None:
            sims = np.dot(existing_embeddings, embeddings[canon_idx])
            best_idx = int(np.argmax(sims))
            if sims[best_idx] >= similarity_threshold:
                match_id = existing_entries[best_idx].glossary_entry_id

        if match_id:
            canonical.candidate_status = "pruned"
            canonical.validation_status = "pending"
            canonical.conflict_reason = f"already_exists:{match_id}"

        alias_clusters.append(
            AliasCluster(
                canonical_id=canonical.candidate_id,
                canonical_term=canonical.source_term,
                aliases=alias_texts,
                member_ids=member_ids,
                similarity_score=avg_sim,
                existing_glossary_match=match_id
            )
        )

    alias_merged_count = sum(1 for c in candidates if c.candidate_status == "alias_merged")
    pruned_count = sum(1 for c in candidates if c.candidate_status == "pruned")
    logger.info(
        "Clustering complete: {} clusters, {} aliases merged, {} pruned (existing match)",
        len(alias_clusters),
        alias_merged_count,
        pruned_count,
    )

    return candidates, alias_clusters
