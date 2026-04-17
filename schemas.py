from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Literal

from json_repair import loads as json_repair_loads
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

import rubric
import voc_taxonomy


KBComplianceStatus = Literal["conforme", "partiel", "non_conforme"]
AlertLevel = Literal["critical", "warning", "info"]
VoCSentiment = Literal["très_négatif", "négatif", "neutre", "positif", "très_positif"]
VoCEmotion = Literal["frustration", "colère", "résignation", "soulagement", "satisfaction", "confusion", "inquiétude"]
SatisfactionSignal = Literal["positif", "neutre", "négatif", "mixte"]
ChurnRiskSignal = Literal["aucun", "faible", "modéré", "élevé"]
ResolutionStatus = Literal["resolved", "escalated", "pending", "unresolved", "callback_scheduled"]
_CLIP_EVENTS = 0


def _clip(value, limit: int):
    global _CLIP_EVENTS
    if value is None:
        return None
    s = str(value).strip()
    if len(s) <= limit:
        return s
    _CLIP_EVENTS += 1
    return s[: limit - 1].rstrip() + "…"


def reset_clip_stats() -> None:
    global _CLIP_EVENTS
    _CLIP_EVENTS = 0


def clip_stats_snapshot() -> int:
    return _CLIP_EVENTS


def strip_json_fences(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = "\n".join(lines[1:]).strip()
    return text


def parse_json_strict(raw: str) -> dict:
    text = strip_json_fences(raw)
    if not text:
        raise ValueError("réponse vide")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = json_repair_loads(text)
    if not isinstance(payload, dict):
        raise ValueError("le JSON doit être un objet")
    return payload


def normalize_text(value: str) -> str:
    compact = re.sub(r"\s+", " ", str(value or "").strip().lower())
    compact = re.sub(r"[^\w\s]", "", compact)
    return compact


def citation_matches_transcript(citation: str, transcript: str, minimum_similarity: float = 0.8) -> bool:
    norm_citation = normalize_text(citation)
    norm_transcript = normalize_text(transcript)
    if not norm_citation or not norm_transcript:
        return False
    if norm_citation in norm_transcript:
        return True
    if len(norm_citation) < 12:
        return False

    step = max(24, len(norm_citation) // 2)
    window = max(len(norm_citation) + 40, 80)
    for start in range(0, max(1, len(norm_transcript) - len(norm_citation) + 1), step):
        chunk = norm_transcript[start:start + window]
        if not chunk:
            continue
        if SequenceMatcher(None, norm_citation, chunk).ratio() >= minimum_similarity:
            return True
    return False


class EvidenceItem(BaseModel):
    text: str = Field(min_length=4, max_length=240)
    citation: str = Field(min_length=4, max_length=160)
    kb_reference: str | None = Field(default=None, max_length=240)

    @field_validator("text", mode="before")
    @classmethod
    def _clip_text(cls, value):
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            raise ValueError("texte vide")
        return _clip(cleaned, 240)

    @field_validator("citation", mode="before")
    @classmethod
    def _clip_citation(cls, value):
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            raise ValueError("texte vide")
        return _clip(cleaned, 160)

    @field_validator("kb_reference", mode="before")
    @classmethod
    def _clip_kb_reference(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value).strip())
        return _clip(cleaned, 240) or None


class VoCStructuredItem(BaseModel):
    quote: str = Field(min_length=4, max_length=240)

    @field_validator("quote", mode="before")
    @classmethod
    def _clean_quote(cls, value):
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            raise ValueError("quote vide")
        return _clip(cleaned, 240)


class TopicMention(VoCStructuredItem):
    topic_code: str = Field(min_length=2, max_length=80)
    product_area: str = Field(default="other", max_length=40)
    sentiment: VoCSentiment
    severity: int = Field(ge=1, le=5)
    needs_taxonomy_review: bool = False

    @field_validator("topic_code", mode="before")
    @classmethod
    def _normalize_topic_code(cls, value):
        code, _ = voc_taxonomy.normalize_taxonomy_code("topics", value)
        return _clip(code, 80)

    @model_validator(mode="after")
    def _set_topic_review(self):
        code, review = voc_taxonomy.normalize_taxonomy_code("topics", self.topic_code)
        self.topic_code = code
        self.product_area = _clip(voc_taxonomy.product_area_for_topic(code), 40) or "other"
        self.needs_taxonomy_review = bool(self.needs_taxonomy_review or review)
        return self


class EntityPerception(VoCStructuredItem):
    entity_code: str = Field(min_length=2, max_length=80)
    aspect_code: str = Field(min_length=2, max_length=80)
    sentiment: VoCSentiment
    needs_taxonomy_review: bool = False

    @model_validator(mode="after")
    def _normalize_codes(self):
        entity_code, entity_review = voc_taxonomy.normalize_taxonomy_code("entities", self.entity_code)
        aspect_code, aspect_review = voc_taxonomy.normalize_taxonomy_code("aspects", self.aspect_code)
        self.entity_code = _clip(entity_code, 80)
        self.aspect_code = _clip(aspect_code, 80)
        self.needs_taxonomy_review = bool(self.needs_taxonomy_review or entity_review or aspect_review)
        return self


class Quote(BaseModel):
    quote: str = Field(min_length=4, max_length=240)
    timestamp_s: int | None = Field(default=None, ge=0)
    speaker: str | None = Field(default=None, max_length=40)
    topic_code: str | None = Field(default=None, max_length=80)
    sentiment: VoCSentiment | None = None

    @field_validator("quote", "speaker", "topic_code", mode="before")
    @classmethod
    def _clean_quote_text(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            return None
        return cleaned

    @field_validator("quote", mode="before")
    @classmethod
    def _clip_quote(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        return _clip(cleaned, 240)

    @field_validator("speaker", mode="before")
    @classmethod
    def _clip_speaker(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        return _clip(cleaned, 40) or None

    @field_validator("topic_code", mode="before")
    @classmethod
    def _clip_topic_code(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        return _clip(cleaned, 80) or None

    @model_validator(mode="after")
    def _normalize_topic_code(self):
        if self.topic_code:
            code, _ = voc_taxonomy.normalize_taxonomy_code("topics", self.topic_code)
            self.topic_code = _clip(code, 80)
        return self


class CompetitorMention(BaseModel):
    competitor_name: str = Field(min_length=2, max_length=120)
    context_quote: str = Field(min_length=4, max_length=240)
    sentiment: VoCSentiment = "neutre"

    @field_validator("competitor_name", mode="before")
    @classmethod
    def _clip_competitor_name(cls, value):
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            raise ValueError("texte vide")
        return _clip(cleaned, 120)

    @field_validator("context_quote", mode="before")
    @classmethod
    def _clip_context_quote(cls, value):
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            raise ValueError("texte vide")
        return _clip(cleaned, 240)


class VoCExtract(BaseModel):
    topics: list[TopicMention] = Field(default_factory=list)
    entity_perceptions: list[EntityPerception] = Field(default_factory=list)
    customer_emotions: list[VoCEmotion] = Field(default_factory=list)
    effort_score: Literal[1, 2, 3, 4, 5]
    satisfaction_signal: SatisfactionSignal
    churn_risk_signal: ChurnRiskSignal
    expansion_signal: bool = False
    resolution_status: ResolutionStatus = "pending"
    competitor_mentions: list[CompetitorMention] = Field(default_factory=list)
    verbatim_quotes: list[Quote] = Field(default_factory=list, max_length=5)
    best_practice_moments: list[Quote] = Field(default_factory=list, max_length=3)
    unmet_needs: list[str] = Field(default_factory=list)
    product_ideas: list[str] = Field(default_factory=list)
    taxonomy_version: str = Field(default_factory=voc_taxonomy.taxonomy_version)
    needs_taxonomy_review: bool = False
    validation_warnings: list[str] = Field(default_factory=list)

    @field_validator("unmet_needs", "product_ideas", "validation_warnings", mode="before")
    @classmethod
    def _clean_text_list(cls, value):
        if value is None:
            return []
        out = []
        for item in value:
            cleaned = re.sub(r"\s+", " ", str(item or "").strip())
            if cleaned:
                out.append(cleaned)
        return out

    @model_validator(mode="after")
    def _validate_version(self):
        if self.taxonomy_version != voc_taxonomy.taxonomy_version():
            raise ValueError("taxonomy_version incohérente")
        review = any(item.needs_taxonomy_review for item in self.topics + self.entity_perceptions)
        self.needs_taxonomy_review = bool(self.needs_taxonomy_review or review)
        return self


class AlertItem(BaseModel):
    level: AlertLevel
    message: str = Field(min_length=4, max_length=240)
    call_ids: list[str] = Field(default_factory=list)

    @field_validator("message", mode="before")
    @classmethod
    def _clean_message(cls, value):
        return _clip(re.sub(r"\s+", " ", str(value or "").strip()), 240)


class KBCompliance(BaseModel):
    status: KBComplianceStatus
    article: str | None = Field(default=None, max_length=240)
    rationale: str | None = Field(default=None, max_length=240)

    @field_validator("article", "rationale", mode="before")
    @classmethod
    def _clean_optional(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value).strip())
        limit = 240
        return _clip(cleaned, limit) or None


class FactualExtract(BaseModel):
    call_id: str = Field(min_length=1)
    classified_type: str = Field(min_length=1)
    customer_call_reason: str | None = Field(default=None, max_length=120)
    transcript_usable: bool = True
    kb_compliance: KBCompliance
    positives: list[EvidenceItem] = Field(default_factory=list)
    improvement_points: list[EvidenceItem] = Field(default_factory=list)
    alerts: list[AlertItem] = Field(default_factory=list)
    procedural_steps_followed: list[str] = Field(default_factory=list)
    emotional_signals: list[str] = Field(default_factory=list)
    resolution_status: ResolutionStatus = "pending"

    @field_validator("call_id", "classified_type", mode="before")
    @classmethod
    def _clean_textish(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value).strip())
        if not cleaned:
            return None
        return cleaned

    @field_validator("customer_call_reason", mode="before")
    @classmethod
    def _clip_customer_call_reason(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value).strip())
        if not cleaned:
            return None
        return _clip(cleaned, 120)

    @field_validator("procedural_steps_followed", "emotional_signals", mode="before")
    @classmethod
    def _clean_string_list(cls, value):
        if value is None:
            return []
        out = []
        for item in value:
            cleaned = re.sub(r"\s+", " ", str(item or "").strip())
            if cleaned:
                out.append(cleaned)
        return out


class CriterionScorecard(BaseModel):
    accueil: float | None = Field(default=None, ge=0, le=10)
    ecoute_active: float | None = Field(default=None, ge=0, le=10)
    empathie: float | None = Field(default=None, ge=0, le=10)
    gestion_tension: float | None = Field(default=None, ge=0, le=10)
    professionnalisme: float | None = Field(default=None, ge=0, le=10)
    clarte_communication: float | None = Field(default=None, ge=0, le=10)
    orientation_solution: float | None = Field(default=None, ge=0, le=10)
    cloture: float | None = Field(default=None, ge=0, le=10)
    qualification_investigation: float | None = Field(default=None, ge=0, le=10)
    kb_application: float | None = Field(default=None, ge=0, le=10)
    observations: str = Field(default="", max_length=320)

    @field_validator("observations", mode="before")
    @classmethod
    def _clean_observations(cls, value):
        return _clip(re.sub(r"\s+", " ", str(value or "").strip()), 320)

    def score_map(self) -> dict[str, float | None]:
        return {
            "accueil": self.accueil,
            "ecoute_active": self.ecoute_active,
            "empathie": self.empathie,
            "gestion_tension": self.gestion_tension,
            "professionnalisme": self.professionnalisme,
            "clarte_communication": self.clarte_communication,
            "orientation_solution": self.orientation_solution,
            "cloture": self.cloture,
            "qualification_investigation": self.qualification_investigation,
            "kb_application": self.kb_application,
        }


class SoftSkillScore(BaseModel):
    accueil: float | None = Field(default=None, ge=0, le=10)
    ecoute_active: float | None = Field(default=None, ge=0, le=10)
    empathie: float | None = Field(default=None, ge=0, le=10)
    gestion_tension: float | None = Field(default=None, ge=0, le=10)
    professionnalisme: float | None = Field(default=None, ge=0, le=10)
    clarte_communication: float | None = Field(default=None, ge=0, le=10)
    orientation_solution: float | None = Field(default=None, ge=0, le=10)
    cloture: float | None = Field(default=None, ge=0, le=10)
    note_globale: float | None = Field(default=None, ge=0, le=10)
    observations: str = Field(default="", max_length=320)

    @field_validator("observations", mode="before")
    @classmethod
    def _clip_observations(cls, value):
        return _clip(re.sub(r"\s+", " ", str(value or "").strip()), 320)


class CallEvaluation(BaseModel):
    call_id: str = Field(min_length=1)
    classified_type: str = Field(min_length=1)
    duration_seconds: int = Field(ge=0)
    kb_article_applicable: str | None = Field(default=None, max_length=240)
    customer_call_reason: str | None = Field(default=None, max_length=120)
    resolution_status: ResolutionStatus = "pending"
    kb_compliance: KBComplianceStatus
    positives: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    alerts: list[AlertItem] = Field(default_factory=list)
    soft_skills: SoftSkillScore
    score_global: float | None = Field(default=None, ge=0, le=10)
    criteria_scores: CriterionScorecard
    positive_items: list[EvidenceItem] = Field(default_factory=list)
    improvement_items: list[EvidenceItem] = Field(default_factory=list)
    voc_extract: VoCExtract | None = None
    voc_taxonomy_version: str | None = Field(default=None, max_length=120)
    rubric_version: str = Field(default_factory=rubric.rubric_version)
    validation_warnings: list[str] = Field(default_factory=list)

    @field_validator("call_id", "classified_type", mode="before")
    @classmethod
    def _clean_optional_text(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value).strip())
        if not cleaned:
            return None
        return cleaned

    @field_validator("kb_article_applicable", mode="before")
    @classmethod
    def _clip_kb_article_applicable(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value).strip())
        return _clip(cleaned, 240) or None

    @field_validator("customer_call_reason", "voc_taxonomy_version", mode="before")
    @classmethod
    def _clip_call_eval_short_text(cls, value):
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value).strip())
        if not cleaned:
            return None
        limit = 120
        return _clip(cleaned, limit)

    @field_validator("positives", "errors", "validation_warnings", mode="before")
    @classmethod
    def _clean_strings(cls, value):
        if value is None:
            return []
        out = []
        for item in value:
            cleaned = re.sub(r"\s+", " ", str(item or "").strip())
            if cleaned:
                out.append(cleaned)
        return out

    @model_validator(mode="after")
    def _ensure_rubric_version(self):
        if self.rubric_version != rubric.rubric_version():
            raise ValueError("rubric_version incohérente")
        if self.voc_extract and self.voc_taxonomy_version != voc_taxonomy.taxonomy_version():
            raise ValueError("voc_taxonomy_version incohérente")
        return self


def validation_error_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return error.json()
    return str(error)


def validation_error_fields(error: Exception) -> list[str]:
    if not isinstance(error, ValidationError):
        return []
    fields = []
    for item in error.errors():
        loc = item.get("loc") or []
        if isinstance(loc, tuple):
            loc = list(loc)
        field = ".".join(str(part) for part in loc if part not in {"__root__"})
        if field:
            fields.append(field)
    return fields


def build_call_evaluation(
    call: dict,
    factual_extract: FactualExtract,
    scorecard: CriterionScorecard,
    model_name: str,
    voc_extract: VoCExtract | None = None,
) -> CallEvaluation:
    transcript = str(call.get("transcript") or "")

    valid_positives = [item for item in factual_extract.positives if citation_matches_transcript(item.citation, transcript)]
    valid_improvements = [
        item for item in factual_extract.improvement_points if citation_matches_transcript(item.citation, transcript)
    ]
    dropped_improvements = len(factual_extract.improvement_points) - len(valid_improvements)

    warnings = []
    if dropped_improvements:
        warnings.append(f"{dropped_improvements} point(s) d'amélioration rejeté(s) faute de citation valide")

    validated_voc = None
    if voc_extract is not None:
        validated_voc = validate_voc_extract(voc_extract, transcript)
        warnings.extend(validated_voc.validation_warnings)

    score_global = rubric.compute_weighted_score(scorecard.score_map())
    if score_global is not None and dropped_improvements:
        score_global = max(0.0, round(score_global - (0.2 * dropped_improvements), 1))
    if validated_voc is not None and score_global is not None and score_global < 8:
        if validated_voc.best_practice_moments:
            warnings.append("best_practice_moments ignorés car score global < 8")
        validated_voc = VoCExtract.model_validate(
            {
                **validated_voc.model_dump(),
                "best_practice_moments": [],
                "validation_warnings": list(validated_voc.validation_warnings) + warnings,
            }
        )

    soft_skills = SoftSkillScore(
        accueil=scorecard.accueil,
        ecoute_active=scorecard.ecoute_active,
        empathie=scorecard.empathie,
        gestion_tension=scorecard.gestion_tension,
        professionnalisme=scorecard.professionnalisme,
        clarte_communication=scorecard.clarte_communication,
        orientation_solution=scorecard.orientation_solution,
        cloture=scorecard.cloture,
        note_globale=score_global,
        observations=scorecard.observations,
    )

    evaluation = CallEvaluation(
        call_id=str(call.get("call_id_internal") or call.get("call_id") or factual_extract.call_id),
        classified_type=str(call.get("classified_type") or factual_extract.classified_type),
        duration_seconds=int(call.get("duration_in_call") or call.get("duration_seconds") or 0),
        kb_article_applicable=factual_extract.kb_compliance.article,
        customer_call_reason=factual_extract.customer_call_reason,
        resolution_status=factual_extract.resolution_status,
        kb_compliance=factual_extract.kb_compliance.status,
        positives=[item.text for item in valid_positives],
        errors=[item.text for item in valid_improvements],
        alerts=factual_extract.alerts,
        soft_skills=soft_skills,
        score_global=score_global,
        criteria_scores=scorecard,
        positive_items=valid_positives,
        improvement_items=valid_improvements,
        voc_extract=validated_voc,
        voc_taxonomy_version=validated_voc.taxonomy_version if validated_voc else None,
        validation_warnings=warnings,
    )
    legacy = evaluation.model_dump()
    legacy["_model"] = model_name
    return CallEvaluation.model_validate(legacy)


def validate_voc_extract(voc_extract: VoCExtract, transcript: str) -> VoCExtract:
    warnings: list[str] = []
    valid_topics = [item for item in voc_extract.topics if citation_matches_transcript(item.quote, transcript)]
    if len(valid_topics) != len(voc_extract.topics):
        warnings.append(f"{len(voc_extract.topics) - len(valid_topics)} topic(s) rejeté(s) faute de citation valide")

    valid_entities = [item for item in voc_extract.entity_perceptions if citation_matches_transcript(item.quote, transcript)]
    if len(valid_entities) != len(voc_extract.entity_perceptions):
        warnings.append(
            f"{len(voc_extract.entity_perceptions) - len(valid_entities)} perception(s) entité rejetée(s) faute de citation valide"
        )

    valid_verbatims = [item for item in voc_extract.verbatim_quotes if citation_matches_transcript(item.quote, transcript)]
    if len(valid_verbatims) != len(voc_extract.verbatim_quotes):
        warnings.append(
            f"{len(voc_extract.verbatim_quotes) - len(valid_verbatims)} verbatim(s) rejeté(s) faute de citation valide"
        )

    valid_competitors = [
        item for item in voc_extract.competitor_mentions if citation_matches_transcript(item.context_quote, transcript)
    ]
    if len(valid_competitors) != len(voc_extract.competitor_mentions):
        warnings.append(
            f"{len(voc_extract.competitor_mentions) - len(valid_competitors)} mention(s) concurrent rejetée(s) faute de citation valide"
        )

    valid_best_practices = [item for item in voc_extract.best_practice_moments if citation_matches_transcript(item.quote, transcript)]
    if len(valid_best_practices) != len(voc_extract.best_practice_moments):
        warnings.append(
            f"{len(voc_extract.best_practice_moments) - len(valid_best_practices)} best practice(s) rejetée(s) faute de citation valide"
        )

    return VoCExtract.model_validate(
        {
            **voc_extract.model_dump(),
            "topics": [item.model_dump() for item in valid_topics],
            "entity_perceptions": [item.model_dump() for item in valid_entities],
            "verbatim_quotes": [item.model_dump() for item in valid_verbatims[:5]],
            "best_practice_moments": [item.model_dump() for item in valid_best_practices[:3]],
            "competitor_mentions": [item.model_dump() for item in valid_competitors],
            "validation_warnings": list(voc_extract.validation_warnings) + warnings,
        }
    )
