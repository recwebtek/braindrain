"""Heuristic dream consolidation over observer/session/wiki layers."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from braindrain.memory_learning import can_promote_memory
from braindrain.observer import ObserverStore
from braindrain.session import EpisodeRecord, SessionStore
from braindrain.wiki_brain import WikiBrain


@dataclass
class ConsolidationPlan:
    plan_id: str
    created_at: float
    mode: str
    source_handles: list[str]
    policy_version: str
    provider_config: dict[str, Any]
    scoring_weights: dict[str, float]
    fingerprint: str


@dataclass
class DreamCandidate:
    candidate_id: str
    title: str
    content: str
    record_class: str
    category: str
    source: str
    evidence_refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    frequency: float = 1.0
    query_diversity: float = 1.0
    consolidation: float = 0.5
    conceptual_richness: float = 0.25
    recency_anchor: float = 0.0
    confidence: float = 0.5
    importance: float = 0.5
    episode_id: str | None = None


class DreamEngine:
    """Light/REM/Deep consolidation with auditable plans."""

    def __init__(
        self,
        *,
        observer_store: ObserverStore,
        session_store: SessionStore,
        wiki_brain: WikiBrain,
        config: dict[str, Any],
        provider_context: dict[str, Any] | None = None,
    ) -> None:
        self.observer_store = observer_store
        self.session_store = session_store
        self.wiki_brain = wiki_brain
        self.config = config
        self.provider_context = provider_context or {}
        storage_dir = (
            Path(config.get("storage_dir", "~/.braindrain/dreaming")).expanduser()
        )
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.plan_dir = self.storage_dir / "plans"
        self.plan_dir.mkdir(parents=True, exist_ok=True)
        self.daily_dir = self.storage_dir / "daily"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def run(self, *, mode: str = "full", force: bool = False) -> dict[str, Any]:
        quiet_minutes = int(self.config.get("quiet_minutes", 30) or 30)
        if not force and mode == "full" and not self.session_store.should_dream(quiet_minutes=quiet_minutes):
            return {
                "status": "skipped_active_session",
                "quiet_minutes": quiet_minutes,
            }

        episodes = self.session_store.list_episodes(limit=int(self.config.get("max_episode_scan", 50) or 50))
        recent_events = self.observer_store.query_events(
            since=time.time() - int(self.config.get("lookback_hours", 72) or 72) * 3600,
            limit=int(self.config.get("max_event_scan", 250) or 250),
        )
        sessions = self.session_store.list_recent_sessions(limit=int(self.config.get("max_session_scan", 20) or 20))

        plan = self._build_consolidation_plan(mode=mode, episodes=episodes, recent_events=recent_events)

        result: dict[str, Any] = {"plan": asdict(plan)}
        candidates: list[DreamCandidate] = []

        if mode in {"full", "light"}:
            candidates = self._light_phase(episodes=episodes, sessions=sessions, recent_events=recent_events)
            result["light"] = {
                "candidate_count": len(candidates),
                "candidates": [asdict(candidate) for candidate in candidates[:10]],
            }

        if mode in {"full", "rem"}:
            rem = self._rem_phase(candidates)
            result["rem"] = rem

        promoted: list[dict[str, Any]] = []
        if mode in {"full", "deep"}:
            if not candidates:
                candidates = self._light_phase(episodes=episodes, sessions=sessions, recent_events=recent_events)
            deep = self._deep_phase(candidates)
            promoted = deep["promoted"]
            result["deep"] = deep

        self._write_plan(plan)
        self._write_dream_diary(result)
        self._write_status(result)
        return result

    def get_status(self) -> dict[str, Any]:
        status_path = self.storage_dir / "last_status.json"
        if not status_path.exists():
            return {"status": "never_run"}
        return json.loads(status_path.read_text())

    def _build_consolidation_plan(
        self,
        *,
        mode: str,
        episodes: list[EpisodeRecord],
        recent_events: list[Any],
    ) -> ConsolidationPlan:
        source_handles = [f"episode:{episode.episode_id}" for episode in episodes]
        source_handles.extend(
            f"event:{event.session_id}:{event.event_type}:{int(event.timestamp)}"
            for event in recent_events[:25]
        )
        scoring_weights = {
            "frequency": float(self.config.get("weights.frequency", 0.24) or 0.24),
            "relevance": float(self.config.get("weights.relevance", 0.30) or 0.30),
            "query_diversity": float(self.config.get("weights.query_diversity", 0.15) or 0.15),
            "recency": float(self.config.get("weights.recency", 0.15) or 0.15),
            "consolidation": float(self.config.get("weights.consolidation", 0.10) or 0.10),
            "conceptual_richness": float(self.config.get("weights.conceptual_richness", 0.06) or 0.06),
        }
        base = {
            "mode": mode,
            "source_handles": source_handles,
            "policy_version": str(self.config.get("policy_version", "memory-lessons-v1")),
            "provider_config": self.provider_context,
            "scoring_weights": scoring_weights,
        }
        fingerprint = hashlib.sha256(
            json.dumps(base, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return ConsolidationPlan(
            plan_id=str(uuid.uuid4()),
            created_at=time.time(),
            mode=mode,
            source_handles=source_handles,
            policy_version=base["policy_version"],
            provider_config=self.provider_context,
            scoring_weights=scoring_weights,
            fingerprint=fingerprint,
        )

    def _light_phase(
        self,
        *,
        episodes: list[EpisodeRecord],
        sessions: list[Any],
        recent_events: list[Any],
    ) -> list[DreamCandidate]:
        candidates: list[DreamCandidate] = []
        for episode in episodes:
            record_class = "lesson" if episode.local_critique or episode.global_reflection else "procedural"
            title = episode.problem[:90]
            content = "\n".join(
                part
                for part in [
                    f"Problem: {episode.problem}",
                    f"Action: {episode.action}",
                    f"Outcome: {episode.outcome}",
                    f"Local critique: {episode.local_critique}" if episode.local_critique else "",
                    f"Global reflection: {episode.global_reflection}" if episode.global_reflection else "",
                ]
                if part
            )
            candidates.append(
                DreamCandidate(
                    candidate_id=episode.episode_id,
                    title=title,
                    content=content,
                    record_class=record_class,
                    category="playbook" if record_class == "lesson" else "procedure",
                    source=f"episode:{episode.episode_id}",
                    evidence_refs=episode.evidence_refs,
                    tags=episode.tags,
                    recency_anchor=episode.created_at,
                    confidence=episode.confidence,
                    importance=0.7 if record_class == "lesson" else 0.55,
                    conceptual_richness=min(1.0, 0.2 + 0.15 * len(episode.tags)),
                    query_diversity=max(1.0, float(len(set(episode.evidence_refs or [])))),
                    consolidation=0.7 if episode.global_reflection else 0.45,
                    episode_id=episode.episode_id,
                )
            )

        if not candidates:
            for session in sessions:
                if not session.key_decisions and not session.errors:
                    continue
                content_parts = [
                    f"Session {session.session_id} summary.",
                    f"Key decisions: {'; '.join(session.key_decisions)}" if session.key_decisions else "",
                    f"Errors: {'; '.join(session.errors)}" if session.errors else "",
                ]
                candidates.append(
                    DreamCandidate(
                        candidate_id=session.session_id,
                        title=f"Session {session.session_id[:8]}",
                        content=" ".join(part for part in content_parts if part),
                        record_class="semantic",
                        category="pattern",
                        source=f"session:{session.session_id}",
                        evidence_refs=[f"session:{session.session_id}"],
                        tags=["session-summary"],
                        recency_anchor=session.updated_at,
                        confidence=0.4,
                        importance=0.45,
                        conceptual_richness=0.3,
                    )
                )

        if recent_events:
            event_types = {event.event_type for event in recent_events}
            for candidate in candidates:
                candidate.frequency += sum(1 for event in recent_events if event.session_id in candidate.source)
                candidate.consolidation += 0.1 * len(event_types.intersection(set(candidate.tags)))

        return candidates

    def _rem_phase(self, candidates: list[DreamCandidate]) -> dict[str, Any]:
        grouped: dict[str, int] = {}
        for candidate in candidates:
            grouped[candidate.record_class] = grouped.get(candidate.record_class, 0) + 1
        reflections = [
            f"{record_class}: {count} grounded candidate(s) surfaced"
            for record_class, count in sorted(grouped.items())
        ]
        return {
            "reflection_count": len(reflections),
            "reflections": reflections,
            "note": "REM reflections are diary-only and never promote durable memory directly.",
        }

    def _deep_phase(self, candidates: list[DreamCandidate]) -> dict[str, Any]:
        weights = {
            "frequency": float(self.config.get("weights.frequency", 0.24) or 0.24),
            "relevance": float(self.config.get("weights.relevance", 0.30) or 0.30),
            "query_diversity": float(self.config.get("weights.query_diversity", 0.15) or 0.15),
            "recency": float(self.config.get("weights.recency", 0.15) or 0.15),
            "consolidation": float(self.config.get("weights.consolidation", 0.10) or 0.10),
            "conceptual_richness": float(self.config.get("weights.conceptual_richness", 0.06) or 0.06),
        }
        min_score = float(self.config.get("deep.min_score", 0.4) or 0.4)
        min_recall = int(self.config.get("deep.min_recall_count", 2) or 2)
        min_queries = int(self.config.get("deep.min_unique_queries", 2) or 2)
        promoted: list[dict[str, Any]] = []
        scored: list[dict[str, Any]] = []
        now = time.time()

        for candidate in candidates:
            recency = max(0.0, min(1.0, 1.0 - ((now - candidate.recency_anchor) / 86400.0 / 30.0)))
            relevance = min(1.0, 0.4 + 0.15 * len(candidate.evidence_refs))
            frequency = min(1.0, candidate.frequency / max(min_recall, 1))
            query_diversity = min(1.0, candidate.query_diversity / max(min_queries, 1))
            score = (
                weights["frequency"] * frequency
                + weights["relevance"] * relevance
                + weights["query_diversity"] * query_diversity
                + weights["recency"] * recency
                + weights["consolidation"] * min(1.0, candidate.consolidation)
                + weights["conceptual_richness"] * min(1.0, candidate.conceptual_richness)
            )
            grounded = bool(candidate.evidence_refs)
            verdict = can_promote_memory(
                candidate.content,
                {
                    "reject_secrets": True,
                    "reject_transient_state": True,
                    "require_grounded_evidence": True,
                    "evidence_refs": candidate.evidence_refs,
                    "min_confidence": 0.35,
                    "confidence": candidate.confidence,
                },
            )
            scored.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "title": candidate.title,
                    "record_class": candidate.record_class,
                    "score": round(score, 6),
                    "grounded": grounded,
                    "verdict": verdict,
                }
            )
            if score < min_score or not grounded or not verdict.get("ok"):
                continue

            stored = self.wiki_brain.store_fact(
                title=candidate.title,
                content=candidate.content,
                record_class=candidate.record_class,
                category=candidate.category,
                source=candidate.source,
                importance=candidate.importance,
                confidence=candidate.confidence,
                tags=candidate.tags,
                evidence_refs=candidate.evidence_refs,
                metadata={
                    "candidate_id": candidate.candidate_id,
                    "dream_score": round(score, 6),
                },
            )
            promoted.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "record_id": stored["record_id"],
                    "record_class": candidate.record_class,
                    "title": candidate.title,
                    "score": round(score, 6),
                }
            )
            if candidate.episode_id:
                self.session_store.mark_episode_promoted(candidate.episode_id, stored["record_id"])

        return {
            "candidate_count": len(candidates),
            "scored": scored,
            "promoted": promoted,
            "promotion_count": len(promoted),
        }

    def _write_plan(self, plan: ConsolidationPlan) -> None:
        plan_path = self.plan_dir / f"{int(plan.created_at)}-{plan.plan_id}.json"
        plan_path.write_text(json.dumps(asdict(plan), indent=2, ensure_ascii=False))

    def _write_status(self, result: dict[str, Any]) -> None:
        status_path = self.storage_dir / "last_status.json"
        status_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    def _write_dream_diary(self, result: dict[str, Any]) -> None:
        diary_path = self.storage_dir / "DREAMS.md"
        lines = [
            "# DREAMS",
            "",
            f"- Last run: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}",
            f"- Mode: {result['plan']['mode']}",
            f"- Fingerprint: `{result['plan']['fingerprint']}`",
            "",
        ]
        if "rem" in result:
            lines.append("## REM")
            lines.extend(f"- {reflection}" for reflection in result["rem"].get("reflections", []))
            lines.append("")
        if "deep" in result:
            lines.append("## Promotions")
            for item in result["deep"].get("promoted", []):
                lines.append(f"- `{item['record_class']}`: {item['title']} ({item['score']})")
            if not result["deep"].get("promoted"):
                lines.append("- No grounded promotions this run.")
            lines.append("")
        diary_path.write_text("\n".join(lines))

        daily_path = self.daily_dir / f"{time.strftime('%Y-%m-%d')}.md"
        daily_path.write_text("\n".join(lines))
