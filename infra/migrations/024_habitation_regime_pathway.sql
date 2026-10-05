-- Hazard regime and relocation pathway per habitation (flood model v0.2, Phase 2e).
--
-- The regime comes from the habitation's H3 res-8 cell (hazard_static_flood.hazard_regime) and is
-- stamped by the triage job together with the pathway it implies, so the queue, the dossier and the
-- allocation solver read one persisted decision instead of re-deriving it.

ALTER TABLE habitation_risk
    ADD COLUMN IF NOT EXISTS hazard_regime TEXT,
    ADD COLUMN IF NOT EXISTS relocation_pathway TEXT;

ALTER TABLE habitation_risk
    DROP CONSTRAINT IF EXISTS habitation_risk_hazard_regime_check;
ALTER TABLE habitation_risk
    ADD CONSTRAINT habitation_risk_hazard_regime_check
    CHECK (hazard_regime IS NULL OR hazard_regime IN ('floodplain', 'char_belt', 'channel'));

ALTER TABLE habitation_risk
    DROP CONSTRAINT IF EXISTS habitation_risk_relocation_pathway_check;
ALTER TABLE habitation_risk
    ADD CONSTRAINT habitation_risk_relocation_pathway_check
    CHECK (relocation_pathway IS NULL
           OR relocation_pathway IN ('mainland_resettlement', 'in_situ_or_nearby', 'not_applicable'));

COMMENT ON COLUMN habitation_risk.hazard_regime IS
    'floodplain | char_belt | channel of the habitation''s H3 res-8 cell; NULL when the district has no regime layer.';
COMMENT ON COLUMN habitation_risk.relocation_pathway IS
    'mainland_resettlement (char belt) | in_situ_or_nearby (floodplain) | not_applicable (channel / unknown regime).';

CREATE INDEX IF NOT EXISTS idx_habitation_risk_regime ON habitation_risk (hazard_regime);
