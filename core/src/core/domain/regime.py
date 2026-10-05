"""Hazard-regime policy for priority scoring, triage and relocation (flood model v0.2, Phase 2e).

Stratifying the flood layer into floodplain / char belt / channel only matters if the regimes lead
to different decisions. This module holds those decisions as pure, configurable functions so the
triage job, the priority engine and the allocation service apply one policy:

- Char belt: erosion is progressive and irreversible, so priority is uplifted, the planning
  horizon is shortened, in-situ mitigation is not offered (an embankment cannot hold a sandbar),
  and the only viable pathway is resettlement onto the mainland.
- Floodplain: standard priority; in-situ mitigation or a nearby elevated site remain valid.
- Channel: active river, not land. No uplift or tier change, and never a destination.

The uplift multiplier and tier shifts are policy parameters, not model outputs. Char-belt hazard
scores are unvalidated against ground truth (NDEM does not map riverbed dynamics), so these
values are a stated policy choice for officers to review, not an empirical calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.enums import HazardRegime, RelocationPathway, Tier


@dataclass(frozen=True)
class RegimePolicyConfig:
    """Configurable regime rules. Defaults encode the Phase 2e plan."""

    #: Multiplier on a char-belt habitation's priority score (progressive, irreversible land loss).
    char_belt_urgency_multiplier: float = 1.25
    #: Shortens the planning horizon: a char-belt habitation due in 2-5 years is due in 6-24 months.
    char_belt_escalate_medium_term: bool = True
    #: False: in-situ mitigation is not viable on a char, so such habitations move to short-term.
    char_belt_in_situ_viable: bool = False
    #: A relocation destination may not sit in these regimes (a destination must not become
    #: tomorrow's source). Cells with no regime are not blocked: districts without a JRC layer
    #: have no regime data, and rejecting all of their sites would report nothing.
    blocked_destination_regimes: tuple[str, ...] = (
        HazardRegime.CHAR_BELT.value,
        HazardRegime.CHANNEL.value,
    )
    policy_version: str = "regime-policy-v1.0"


DEFAULT_REGIME_POLICY = RegimePolicyConfig()


@dataclass(frozen=True)
class RegimeTierAdjustment:
    """Outcome of applying the regime's planning-horizon rules to a computed tier."""

    tier: Optional[Tier]
    changed: bool = False
    note: str = ""


def normalize_regime(value: object) -> Optional[HazardRegime]:
    """Parses a regime label; unknown or missing values are None, never defaulted to floodplain."""
    if isinstance(value, HazardRegime):
        return value
    try:
        return HazardRegime(str(value)) if value else None
    except ValueError:
        return None


def apply_regime_urgency(
    score: float,
    regime: object,
    policy: RegimePolicyConfig = DEFAULT_REGIME_POLICY,
) -> float:
    """Applies the regime's priority uplift to an already-computed priority score."""
    if normalize_regime(regime) == HazardRegime.CHAR_BELT:
        return round(float(score) * policy.char_belt_urgency_multiplier, 4)
    return round(float(score), 4)


def adjust_tier_for_regime(
    tier: Optional[Tier],
    regime: object,
    policy: RegimePolicyConfig = DEFAULT_REGIME_POLICY,
) -> RegimeTierAdjustment:
    """Shortens the planning horizon for char-belt habitations; every other regime is unchanged.

    Immediate stays reserved for the PRD's explicit evidence criteria (deformation, a recent fatal
    event, critical exposure); regime alone never promotes a habitation to Immediate.
    """
    if normalize_regime(regime) != HazardRegime.CHAR_BELT or tier is None:
        return RegimeTierAdjustment(tier=tier)

    if tier == Tier.MITIGATE_IN_SITU and not policy.char_belt_in_situ_viable:
        return RegimeTierAdjustment(
            tier=Tier.SHORT_TERM,
            changed=True,
            note=(
                "Char belt: in-situ mitigation is not viable on a river sandbar, so the habitation "
                "moves to short-term mainland resettlement."
            ),
        )
    if tier == Tier.MEDIUM_TERM and policy.char_belt_escalate_medium_term:
        return RegimeTierAdjustment(
            tier=Tier.SHORT_TERM,
            changed=True,
            note=(
                "Char belt: erosion is progressive and irreversible, so the planning horizon is "
                "shortened from 2-5 years to 6-24 months."
            ),
        )
    return RegimeTierAdjustment(tier=tier)


def relocation_pathway_for(regime: object) -> RelocationPathway:
    """The pathway a habitation in this regime is routed through."""
    resolved = normalize_regime(regime)
    if resolved == HazardRegime.CHAR_BELT:
        return RelocationPathway.MAINLAND_RESETTLEMENT
    if resolved == HazardRegime.FLOODPLAIN:
        return RelocationPathway.IN_SITU_OR_NEARBY
    return RelocationPathway.NOT_APPLICABLE


def is_destination_regime_allowed(
    regime: object,
    policy: RegimePolicyConfig = DEFAULT_REGIME_POLICY,
) -> bool:
    """False when a site's regime is one a relocation must never land in."""
    resolved = normalize_regime(regime)
    return resolved is None or resolved.value not in policy.blocked_destination_regimes
