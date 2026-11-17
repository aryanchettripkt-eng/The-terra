# SETU-DRR (The Dead Zone)
### Hazard Red Zone Identification, Utility Carrying Capacity Assessment & Relocation Decision Support Platform

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16.3-black.svg?style=flat&logo=next.js&logoColor=white)](https://nextjs.org/)
[![React 19](https://img.shields.io/badge/React-19.2-61DAFB.svg?style=flat&logo=react&logoColor=black)](https://react.dev/)
[![Tailwind CSS v4](https://img.shields.io/badge/Tailwind-v4-38B2AC.svg?style=flat&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![PostgreSQL 16 + PostGIS](https://img.shields.io/badge/PostgreSQL-16%20%2B%20PostGIS-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://postgis.net/)
[![H3 Spatial Index](https://img.shields.io/badge/Uber%20H3-Res%206--9-black.svg?style=flat)](https://h3geo.org/)
[![Google OR-Tools](https://img.shields.io/badge/Google%20OR--Tools-Min--Cost%20Flow-4285F4.svg?style=flat&logo=google&logoColor=white)](https://developers.google.com/optimization)
[![Tests Passing](https://img.shields.io/badge/Tests-650%2B%20Passing-brightgreen.svg?style=flat)]()
[![Offline Demo Ready](https://img.shields.io/badge/Demo%20Mode-100%25%20Offline%20Ready-blueviolet.svg?style=flat)]()

---

## 📌 Executive Summary

**SETU-DRR** (*Strategic Evacuation & Terrestrial Relocation Utility for Disaster Risk Reduction*, codenamed **The Dead Zone**) is an autonomous, evidence-backed decision support system developed for the **Ministry of Home Affairs — National Disaster Response Force (NDRF)**, the **Disaster Management Division (NDMD)**, State Disaster Management Authorities (SDMAs), and District Collectors/Administrators.

In India's climate-vulnerable geographies—from the fragile slopes of the Western Ghats (Wayanad, Kodagu) to the alluvial floodplains of the Brahmaputra (Barpeta) and Chambal basins (Dholpur, Morena)—recurring landslides, cloudbursts, and flash floods displace thousands of families every monsoon.

Traditional disaster management has suffered from **three systemic failures**:
1. **No standing inventory of unsafe habitations:** Relocation is reactive, negotiated in the aftermath of mass casualties, rather than prioritized through continuous multi-hazard exposure and social vulnerability modeling.
2. **No utility carrying capacity checks at relocation destinations:** Resettlement sites are selected purely on land availability. Displaced families are placed in areas lacking water, schools, or primary health access, triggering secondary socio-economic collapse.
3. **Conflation of temporary evacuation with permanent relocation:** Transient weather events trigger rushed, costly, and legally fraught permanent relocations, while chronic structural ground deformations are neglected until fatal disaster strikes.

**SETU-DRR** replaces guesswork with a rigorous, end-to-end mathematical decision pipeline:
* Computes multi-hazard susceptibility (**Landslide, Flash Flood, Riverine Flood, Storm Surge, Coastal Erosion**) via probabilistic union over a discrete hexagonal spatial grid (Uber H3, Resolutions 6–9).
* Audits destination sites against four independent infrastructure constraints (**Land, Water, Education, Healthcare**), isolates the binding bottleneck, and projects capital augmentation costs.
* Solves optimal household-to-site matching using **Google OR-Tools constrained min-cost flow optimization**, minimizing displacement distance while guarding against community fragmentation (village group splits).
* Integrates dynamic meteorological forecast cycles (**Open-Meteo ECMWF / IMD 72-hour forecasts**) to power real-time emergency evacuation alerts without compromising permanent resettlement baselines.

---

## 🏛️ System Architecture

SETU-DRR is engineered as a decoupled monorepo combining high-performance scientific Python computing with a state-of-the-art Next.js frontend:

```
                          ┌─────────────────────────────────────────────────────────┐
                          │                SETU-DRR WEB WORKSPACE                   │
                          │   Next.js 16 (App Router) + React 19 + Tailwind CSS v4  │
                          │   GSAP Microinteractions + Three.js 3D Visualizations   │
                          │       MapLibre GL + Deck.gl Hexagonal Vector Tiles      │
                          └────────────────────────────┬────────────────────────────┘
                                                       │ HTTP / JSON API
                                                       │ Dual Auth (Cookies + Bearer)
                                                       ▼
                          ┌─────────────────────────────────────────────────────────┐
                          │                  FASTAPI SERVING LAYER                  │
                          │    Pydantic Schemas • Argon2id Identity • RBAC & LGD    │
                          │    Stateless Scenario Engine • Audit Request Logging    │
                          └────────────────────────────┬────────────────────────────┘
                                                       │
                     ┌─────────────────────────────────┴─────────────────────────────────┐
                     ▼                                                                   ▼
       ┌───────────────────────────────┐                                   ┌───────────────────────────────┐
       │      CORE DOMAIN ENGINES      │                                   │     PIPELINE & ETL JOBS       │
       │  • Multi-Hazard Index (MHI)   │                                   │  • Sentinel-1 SAR Water Mask  │
       │  • SoVI PCA Vulnerability     │                                   │  • HAND Terrain Topography    │
       │  • Time-Decayed Loss History  │                                   │  • WorldPop Peak Segmentation │
       │  • 4-Tier Triage Engine       │                                   │  • Site Eligibility Masking   │
       │  • Carrying Capacity Lifelines│                                   │  • Open-Meteo 72h Weather ETL │
       │  • OR-Tools Min-Cost Flow     │                                   │  • Offline Fixture Importers  │
       └───────────────┬───────────────┘                                   └───────────────┬───────────────┘
                       │                                                                   │
                       └─────────────────────────────────┬─────────────────────────────────┘
                                                         │ SQL / Asyncpg / Psycopg3
                                                         ▼
                          ┌─────────────────────────────────────────────────────────┐
                          │             POSTGRESQL 16 + POSTGIS + H3                │
                          │   15 Idempotent Migrations • GiST Spatial Indexes       │
                          │   BRIN Temporal Partitions • Cryptographic Provenance   │
                          └─────────────────────────────────────────────────────────┘
```

---

## 🔬 Core Mathematical & Algorithmic Models

### 1. Multi-Hazard Index (MHI) Probabilistic Union
Static susceptibility layers ($S_h \in [0, 1]$) and live meteorological trigger values ($T_h \ge 0$) are merged per hazard $h$:
$$H_h(c, t) = \operatorname{clamp}\big(S_h(c) \cdot (1 + \beta \cdot T_h(c, t)),\, 0,\, 1\big) \quad (\text{with } \beta = 1.0)$$

*Invariant:* If static susceptibility $S_h(c) = 0$, $H_h(c, t) \equiv 0.0$ regardless of trigger intensity.

The composite Multi-Hazard Index is computed via probabilistic independent union across all active hazards:
$$\text{MHI}(c, t) = 1 - \prod_{h} \big(1 - w_h \cdot H_h(c, t)\big)$$
*Default Baseline Weights:* Landslide ($1.0$), Flash Flood ($1.0$), Storm Surge ($0.9$), Riverine Flood ($0.8$), Coastal Erosion ($0.7$).

### 2. Four Spatial Hazard Zones
Each H3 hexagonal grid cell is categorized into one of four mutually exclusive zones:
1. **Permanent Red Zone (PRZ):** $\text{MHI}_{\text{static}} \ge 0.75$ OR any single $S_h \ge 0.85$ OR ($\text{MHI}_{\text{static}} \ge 0.60$ with fatal disaster recorded within 25 years).
2. **Caution Zone:** $0.45 \le \text{MHI}_{\text{static}} < 0.75$.
3. **Active Alert Zone (AAZ):** Live trigger causes $\text{MHI}_{\text{live}} \ge 0.75$ on land where $\text{MHI}_{\text{static}} < 0.75$. (*Triggers emergency evacuation, never permanent resettlement*).
4. **Forecast Alert Zone (FAZ):** 72-hour forecast predicts $\text{MHI}_{\text{fcst}} \ge 0.75$.

### 3. Time-Decayed Disaster Loss History
Disaster memory fades over time; recent casualties and damages carry heavier decision weight according to an exponential half-life decay model ($\lambda = \ln(2) / 10\text{ years}$):
$$\hat{L}_j = \sum_{i} e^{-\lambda (t_{\text{now}} - t_i)} \cdot \text{severity}_i$$

### 4. Habitation Priority Scoring & Triage
For habitation $j$ with population-weighted hazard intensity $\hat{h}_j$, PRZ population fraction $\hat{f}_j$, Social Vulnerability Index $\hat{V}_j \in [0, 1]$ (PCA across demographic, structural, access, and economic dimensions), and loss history $\hat{L}_j$:
$$\text{PS}_j = (\hat{h}_j \cdot \hat{f}_j \cdot \hat{V}_j) \cdot (1 + \gamma \cdot \hat{L}_j) \quad (\text{with } \gamma = 0.5)$$
$$\text{Caseload}_j = \text{PS}_j \times \text{Population}_j$$

#### Four-Tier Triage Precedence:
* **Tier 1 (Immediate Relocation, 0–6 months):** Habitation overlaps PRZ AND (active ground deformation detected OR fatal event in last 3 monsoons OR $\hat{f}_j > 0.60 \land \hat{h}_j > 0.85$).
* **Tier 4 (Mitigate In-Situ):** Small PRZ fraction ($\hat{f}_j < 0.30$) where civil engineering (slope stabilization, embankments, drainage) is proven more cost-effective than physical relocation ($\text{Cost}_{\text{mitigation}} < \text{Cost}_{\text{relocation}}$).
* **Tier 2 (Short-Term Relocation, 6–24 months):** Significant PRZ overlap ($\ge 30\%$) or high priority score ($\text{PS}_j \ge 0.30$).
* **Tier 3 (Medium-Term Relocation, 2–5 years):** Caution Zone with adverse trend (accelerated loss frequency or urban expansion) or moderate exposure.

### 5. Multi-Resource Carrying Capacity Assessment
A candidate destination parcel is never evaluated on raw acreage alone. Physical capacity is constrained by the most restrictive utility lifeline:
$$\text{CC}(s) = \min\big(\text{CC}_{\text{land}},\, \text{CC}_{\text{water}},\, \text{CC}_{\text{school}},\, \text{CC}_{\text{health}}\big) \times \mu_{\text{livelihood}}$$

* **Land Capacity:** Based on national town-planning norms of $90\text{ m}^2$ plot area $+ 40\%$ infrastructure overhead ($126\text{ m}^2/\text{household}$):
  $$\text{CC}_{\text{land}} = \left\lfloor \frac{\text{Area}_{\text{developable}}\text{ (m}^2\text{)}}{126.0} \right\rfloor$$
* **Potable Water Capacity:** Evaluated against CPHEEO standards ($55\text{ LPCD}$ rural, $135\text{ LPCD}$ urban) and sustainable aquifer yield.
* **Education Capacity:** Spare seating headroom from local UDISE+ school clusters.
* **Healthcare Capacity:** Indian Public Health Standards (1 PHC per $20,000$ in hilly/tribal terrain, $30,000$ in plains).
* **Binding Constraint & Augmentation:** The engine flags the specific bottleneck limiting capacity and models intervention ROI (e.g., drilling deep tubewells or expanding PHC sub-centers to unlock additional resettlement capacity).

### 6. Relocation Optimization (Google OR-Tools Min-Cost Flow)
Household resettlement matching is modeled as an exact integer min-cost flow network:
$$\text{Maximize} \sum_{j \in \mathcal{H}} \sum_{s \in \mathcal{S}} x_{js} \cdot (\text{PS}_j \cdot \text{Suitability}_s) - \sum_{j, s} c_{js} \cdot x_{js}$$
$$\text{subject to} \quad \sum_{s} x_{js} \le \text{Demand}_j, \quad \sum_{j} x_{js} \le \text{CC}(s), \quad x_{js} \in \mathbb{Z}^+$$
where $c_{js} = \text{distance}_{js} \times \text{weight}$. The solver flags any **village group splits** (allocating a single village across multiple non-contiguous sites) so administrators can conduct mandatory social impact and gram sabha reviews.

---

## 🗺️ Earth Observation & Pipeline Workflows

### 1. Flood Susceptibility Pipeline (Steps 1–10 / Milestones A–E)
* **Milestone A (STAC Discovery):** Discovers Sentinel-1 RTC GRD SAR scenes over target districts.
* **Milestone B (SAR Water Masking):** Applies Lee adaptive filtering and Otsu dynamic backscatter thresholding (VV/VH polarizations).
* **Milestone C (Permanent Water Removal):** Masks out permanent water bodies using JRC Global Surface Water to isolate ephemeral flood inundation.
* **Milestone D (HAND & Cropland Modeling):** Derives Height Above Nearest Drainage (HAND) from MERIT DEM/Hydro. Applies ESA WorldCover masks. Enforces structural hard-zero exclusions ($\text{HAND} > 30\text{ m}$ or $\text{slope} > 15^\circ$).
* **Milestone E (H3 Zonal Aggregation):** Zonal reduction of multi-temporal inundation frequencies to H3 Resolution 8 cells, computing max susceptibility, valid pixel coverage, and observation confidence ceilings.

### 2. Settlement Derivation (Step 11)
Standard connected-component clustering collapses dense floodplains into a single giant component (e.g., 99.6% of Barpeta in one component). SETU implements a **population-peak watershed segmentation** over WorldPop's settlement-constrained raster. Local population density maxima seed discrete settlement agglomerations, preventing artificial urban aggregation.

### 3. Candidate Relocation Site Derivation (Steps 12–13)
Screens contiguous parcels against slope ($\le 15^\circ$), flood susceptibility ($\le 0.25$), forest conservation areas, and water bodies. Polygonizes valid zones, calculates developable acreage, and computes screening-grade land capacity.

### 4. Dynamic Weather Forecast Pipeline (Phases B1–B8)
Ingests 72-hour numerical weather predictions from Open-Meteo (ECMWF IFS / IMD GFS). Spatially regrids forecast rainfall to 3,601 Wayanad H3 cells, calculates Antecedent Rainfall Indices (ARI, 15-day window, decay $k = 0.9$), and computes forecast MHI snapshots. Production runs are managed via a singleton cron scheduler with PostgreSQL session advisory locking and bounded historical retention.

---

## 🛡️ Critical Design Invariants & Honest Data Semantics

SETU-DRR adheres strictly to civil-service and legal governance principles:

1. **Evacuation $\ne$ Relocation:** Dynamic forecast alerts trigger emergency warning and civil defense evacuation. They **NEVER** modify a habitation's permanent triage tier. Permanent relocation is determined strictly by chronic risk, active ground deformation, and past fatal recurrence.
2. **Honest NULL Gaps (Missing Data Is Not Safe):** When water yield, school capacity, or healthcare data has not been surveyed, the database stores strict `NULL` values. The system **NEVER** silently casts missing lifelines to zero (which would falsely mark a safe parcel as uninhabitable) or assumes unmeasured utilities are plentiful.
3. **Screening Grade vs. Order Grade:** All algorithmically generated candidate sites carry an immutable `SCREENING_GRADE_NOTICE`. Geotechnical soil investigations, hydraulic modeling, and community consultations are legally mandatory before issuing formal relocation orders.
4. **Decoupled External Evidence:** External offline GIS recommendations (e.g., partner NGO or district proposals) are ingested into `external_relocation_recommendation` linked to cryptographically hashed `data_import_run` audit records. They are benchmarked side-by-side against SETU's optimization engine (`GET /plan/benchmark`), preserving total provenance.
5. **Zero External Network Dependency (`DEMO_MODE=true`):** The system operates 100% offline out-of-the-box using pre-recorded spatial snapshots and deterministic seeds. It cannot fail due to API quotas, network dropouts, or external provider downtime.

---

## 📂 Codebase Directory Layout

```text
the-dead-zone/
├── api/                             # FastAPI Serving Layer (L5)
│   └── src/api/
│       ├── main.py                  # Entrypoint, middleware & error sanitization
│       ├── config.py                # API runtime settings
│       ├── dependencies.py          # Session auth, RBAC, DB connection injectors
│       ├── middleware.py            # Request ID tracing & audit logging
│       ├── routes/                  # Modular endpoint routers
│       │   ├── auth.py              # Argon2id login, session management & logout
│       │   ├── habitations.py       # Triage queue & habitation risk dossiers
│       │   ├── hazard.py            # Static hazard layer & cell driver queries
│       │   ├── zones.py             # MHI composite zones & cell inspections
│       │   ├── sites.py             # Candidate relocation site queries & overrides
│       │   ├── alerts.py            # Active evacuation & 72h forecast alerts
│       │   ├── plan.py              # OR-Tools relocation allocation solver
│       │   ├── recommendations.py   # External GIS benchmarking & audit comparisons
│       │   ├── scenario.py          # Stateless policy sensitivity simulations
│       │   └── health.py            # Liveness, readiness & DB diagnostic probes
│       ├── services/                # Business logic orchestration
│       └── repositories/            # Direct PostgreSQL query execution
│
├── core/                            # Pure Mathematical & Domain Engines (L4)
│   └── src/core/
│       ├── config.py                # Global settings & database connection normalization
│       ├── constants.py             # Single source of truth for all mathematical constants
│       ├── enums.py                 # Domain enums (Hazard, Tier, ZoneClass, BindingConstraint)
│       ├── errors.py                # Standardized error codes & application exceptions
│       ├── governance.py            # Separation of scientific laws vs. policy parameters
│       ├── h3_utils.py              # H3 index validation, resolution conversion & geometry
│       ├── db_models.py             # SQLAlchemy ORM definitions & spatial mappings
│       ├── domain/                  # Pure functional algorithms (zero database coupling)
│       │   ├── hazard.py            # MHI union, trigger amplification & zone classification
│       │   ├── vulnerability.py     # SoVI PCA weights & district downscaling validation
│       │   ├── priority.py          # Time-decayed loss, priority scoring & 4-tier triage
│       │   ├── capacity.py          # 4-lifeline carrying capacity, bottlenecks & augmentation
│       │   ├── allocation.py        # Google OR-Tools min-cost flow relocation solver
│       │   ├── scenario.py          # Stateless sensitivity evaluation & rank deltas
│       │   ├── auth.py              # Password hashing & session token generation
│       │   ├── authorization.py     # Role-Based Access Control (RBAC) permissions
│       │   └── rate_limit.py        # Sliding-window login rate limiting
│       ├── ml/                      # Machine learning protocol seams & fallback providers
│       │   ├── protocols.py         # Structural subtyping protocols (PEP 544)
│       │   ├── registry.py          # Baseline heuristic providers & dependency injection
│       │   └── types.py             # Feature vector definitions & prediction containers
│       └── schemas/                 # Pydantic v2 validation contracts
│
├── pipeline/                        # Earth Observation ETL & Ingestion Jobs (L1–L3)
│   └── src/pipeline/
│       ├── hazard/flood/            # Steps 1–10 flood susceptibility pipeline
│       │   ├── run_milestone_a.py   # Sentinel-1 STAC discovery
│       │   ├── run_milestone_b.py   # SAR Otsu water mask
│       │   ├── run_milestone_c.py   # Permanent water removal & frequency stack
│       │   ├── run_milestone_d.py   # HAND topography & cropland exclusion
│       │   ├── run_milestone_e.py   # H3 zonal aggregation & GeoParquet generation
│       │   ├── districts.py         # Pilot district configurations (Barpeta, Dholpur, Morena)
│       │   └── run_district_flood.py# Unified multi-district pipeline runner
│       ├── exposure/                # Settlement derivation
│       │   ├── population.py        # WorldPop constrained raster ingestion
│       │   └── settlements.py       # Population-peak watershed segmentation
│       ├── relocation/              # Relocation parcel derivation
│       │   ├── eligibility_mask.py  # Habitable land mask & polygonization
│       │   ├── barpeta_validator.py # Offline artifact validation & integrity check
│       │   └── landcover.py         # Land cover classification on grid
│       ├── ingestion/               # Dynamic weather feeds
│       │   ├── open_meteo_client.py # ECMWF/IMD 72h forecast retrieval
│       │   ├── open_meteo_regrid.py # Spatial mapping to Wayanad H3 cells
│       │   ├── open_meteo_trigger.py# Antecedent rainfall index trigger calculation
│       │   └── open_meteo_validate.py# Contract & completeness validation
│       └── jobs/                    # High-level pipeline execution runners
│           ├── seed_pilot_data.py   # Deterministic database seeding for Wayanad & Kodagu
│           ├── derive_habitations.py# Derive settlements from WorldPop population peaks
│           ├── derive_candidate_sites.py # Derive relocation parcels from eligibility masks
│           ├── run_open_meteo_wayanad.py # Wayanad live forecast snapshot pipeline
│           └── scheduler.py         # Production forecast cron scheduler with advisory locking
│
├── web/                             # Next.js 16 Responsive Frontend (L6)
│   ├── app/                         # App Router Pages
│   │   ├── page.tsx                 # Public Landing: 3D Earth Globe, scrollytelling & mist
│   │   ├── workspace/page.tsx       # T.E.R.R.A. Operational Hazard Workspace (3-panel)
│   │   ├── gov/page.tsx             # Government Command Portal: 3D Extruded Columns & GIS
│   │   ├── relocation/page.tsx      # Relocation Workspace: Demand Queue, Safe Havens & Solver
│   │   ├── stories/page.tsx         # Public Research & Field Evidence Stories
│   │   ├── about/page.tsx           # Technical Methodology & Architecture Documentation
│   │   └── login/page.tsx           # Role-Based Officer & Civilian Authentication
│   ├── components/
│   │   ├── ui/                      # Foundational atomic components (Buttons, Badges, Sliders)
│   │   ├── common/                  # Shared widgets (ScreeningGradeNotice, MetricCards, Toasts)
│   │   ├── layout/                  # ThreePanelLayout, LeftPanel, CenterPanel, RightPanel, Header
│   │   ├── providers/               # ThemeProvider (Dark/Light mode) & AuthProvider
│   │   └── features/                # Domain-specific feature modules
│   │       ├── globe/               # Three.js Interactive 3D Earth Globe & Hotspots
│   │       ├── map/                 # MapLibre GL + Deck.gl H3 Hexagon Map & Controls
│   │       ├── map-3d/              # Three.js 3D Extruded Hex Columns (India3DCanvas)
│   │       ├── triage/              # Prioritized Habitation Triage Queue & Rows
│   │       ├── dossier/             # Cell Dossier, Physical Drivers & SoVI Breakdown
│   │       ├── relocation/          # Candidate site cards, Allocation panel & Capacity overrides
│   │       ├── forecast/            # 72-hour forecast alert timeline & weather cycles
│   │       └── auth/                # Biometric & credential verification modals
│   └── lib/                         # Client API library, custom React hooks & motion helpers
│
├── infra/                           # Database & Infrastructure
│   ├── migrations/                  # 15 Sequential SQL migrations (001_ to 015_)
│   ├── Dockerfile.postgres          # Custom PostgreSQL 16 + PostGIS + H3 container
│   ├── docker-compose.yml           # Local dev stack (Postgres + Martin Vector Tile Server)
│   ├── martin.yaml                  # Martin Tile Server configuration
│   ├── apply_migrations.py          # Deterministic migration runner using psycopg3
│   └── verify_db.py                 # PostGIS and H3 extension diagnostic validator
│
├── scripts/                         # Verification & Audit Utilities
│   ├── verify_demo_story.py         # End-to-end 10-step verification of Barpeta & Wayanad
│   ├── export_openapi.py            # OpenAPI JSON exporter for frontend type generation
│   ├── audit_database_reality.py    # Direct PostgreSQL audit script
│   └── verify_b8_full_certification.py # Dynamic forecast pipeline verification
│
└── tests/                           # Complete Test Suite (650+ Automated Tests)
    ├── unit/                        # Unit tests for domain algorithms, auth & pipelines
    ├── integration/                 # API endpoint integration tests
    ├── contract/                    # OpenAPI contract compliance tests
    └── fixtures/                    # Deterministic test fixtures and sample data
```

---

## ⚡ Getting Started & Local Development

### Prerequisites
* **Python 3.11+**
* **Node.js 20+** and **pnpm 10+**
* **Docker & Docker Compose** (for local PostgreSQL + PostGIS + H3 and Martin tile server)
* **uv** (recommended for ultrafast Python package management): `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

### Step 1: Clone Repository & Configure Environment

```bash
git clone https://github.com/aryanchettripkt-eng/the-dead-zone.git
cd the-dead-zone

# Copy environment template
cp .env.example .env
```

Review `.env`. For local development, defaults work out of the box:
```env
DATABASE_URL=postgresql://setu:setu@localhost:5432/setu
DIRECT_DATABASE_URL=postgresql://setu:setu@localhost:5432/setu
DEMO_MODE=true
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_TILE_BASE_URL=http://localhost:3001
```

---

### Step 2: Start Infrastructure (PostgreSQL + PostGIS + H3 + Martin)

```bash
# Start PostGIS and Martin tile server containers
docker compose -f infra/docker-compose.yml up -d

# Verify database extensions (PostGIS 3.4, H3 4.2)
uv run python infra/verify_db.py
```

---

### Step 3: Run Database Migrations & Seed Baseline Data

```bash
# Apply all 15 sequential SQL migrations
uv run python infra/apply_migrations.py

# Seed deterministic pilot datasets (Wayanad, Kodagu, demo user accounts)
uv run python pipeline/src/pipeline/jobs/seed_pilot_data.py

# (Optional) Seed Barpeta offline relocation artifacts
uv run python pipeline/scripts/load_barpeta_relocation.py
```

---

### Step 4: Install Dependencies & Launch Services

Open two terminal sessions:

#### Terminal 1 — Backend API (FastAPI)
```bash
# Install Python packages across all workspace members (core, api, pipeline)
uv sync

# Run FastAPI serving layer on port 8000
pnpm dev:api
# Or directly: uv run uvicorn api.main:app --reload --port 8000
```
Interactive API documentation will be available at:
* Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
* ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

#### Terminal 2 — Frontend Application (Next.js 16)
```bash
# Install frontend dependencies
pnpm install

# Start Next.js development server on port 3000
pnpm dev
```
Open your browser at: [http://localhost:3000](http://localhost:3000)

---

## 🔁 Running Pipelines by District

Every pipeline writes to whatever `DATABASE_URL` / `DIRECT_DATABASE_URL` in `.env` points at, and the API reads that same database. There is nothing to deploy after a run; the new data is served as soon as the run's `pipeline_run` is `READY` and promoted in `serving_version`. Run all commands from the repo root.

### What exists for each pilot district

| Layer | Wayanad (LGD 555) | Kodagu (LGD 540) | Barpeta (LGD 277) |
|---|---|---|---|
| Boundary, grid, static hazard, habitations, sites | `seed_pilot_data`, then `clip_district_to_boundary` (real polygon, WorldPop population) | `seed_pilot_data` (synthetic baseline, rectangular boundary) | Flood pipeline + `load_barpeta_relocation` |
| Static hazard from real data | Not scripted in this repo (see the note below) | none | Flood milestones A–E |
| Live 72h forecast | `scheduler` / `run_open_meteo_wayanad` | none | none |
| OSM infrastructure | `harvest_osm_infrastructure` | `harvest_osm_infrastructure` | `harvest_osm_infrastructure` |
| Default map layer in the UI | `landslide` | `landslide` | `riverine_flood` |

The default layer per district lives in `web/lib/map/districtHazardDefaults.ts`. Add new districts there.

### Wayanad

```bash
# 1. Baseline: boundary, H3 grid, synthetic hazard/MHI, habitations, candidate sites
uv run python pipeline/src/pipeline/jobs/seed_pilot_data.py

# 2. Live ECMWF forecast: Route 1 sparse peak-envelope across all districts or single district
uv run python -m pipeline.jobs.run_district_forecast --all               # evaluate all 7 registered districts
uv run python -m pipeline.jobs.run_district_forecast --district wayanad # or single district
#    Add --live to make live Open-Meteo HTTP calls; add --dry-run to simulate without writes.

# 3. Or run the scheduler across all districts on FORECAST_SCHEDULE_CRON (default every 6h)
uv run python -m pipeline.jobs.scheduler --all --run-once               # run once across all districts
uv run python -m pipeline.jobs.scheduler --all --daemon                 # keep running on 6h cron


# 4. Real flood susceptibility + measured confidence (Sentinel-1 x HAND), ~4 min, needs network.
#    Replaces only the riverine_flood layer; landslide and flash_flood have no real pipeline.
uv run python -m pipeline.hazard.flood.run_district_flood wayanad --no-db --no-population
TARGET_DB_URL=... uv run python -m pipeline.hazard.flood.sync_flood_to_db wayanad
#    The sync inserts the whole polygon fill and zeroes grid_cell.population. Afterwards delete the
#    border cells that have no landslide row, re-run clip_district_to_boundary (population) and
#    refresh_district_hazard (MHI), as described below.

# 5. Real OSM facilities (schools, health, water) for candidate-site screening
uv run python -m pipeline.jobs.harvest_osm_infrastructure --district Wayanad   # or --lgd 555
```

The forecast run only writes forecast rows. It never touches `hazard_static`, `grid_cell` or `explanation`. If every `trigger_value` in a cycle is 0, the forecast is dry (the trigger needs at least 10 mm/h averaged over 3 h) and `mhi_fcst` will equal `mhi_static`.

> **After replacing a district's static layer, refresh its derived tables.** `mhi_snapshot` (zone classes, MHI, dominant hazard; what `/zones` and the alerts serve) and `explanation` (dossier attributions) are computed from `hazard_static` and nothing regenerates them on ingest.
>
> ```bash
> uv run python -m pipeline.jobs.refresh_district_hazard --lgd 555 --dry-run                          # report only
> uv run python -m pipeline.jobs.refresh_district_hazard --lgd 555 --clear-stale-explanations         # apply
> ```
>
> The job re-scores every snapshot row from the current `hazard_static` plus persisted triggers, and overwrites all derived columns. It first writes CSV backups of the affected rows to `data/backups/district_hazard_refresh/`, so it can be rolled back. `--clear-stale-explanations` deletes explanation rows whose `model_version` no longer matches the cell's `hazard_static`. Nothing regenerates them, so the dossier shows no attributions until the layer's own model provides them. Do not use `seed_pilot_data` for this: it reseeds synthetic pilot data over the real layer.
>
> The real-terrain Wayanad layer (`terrain-copernicus-v1.0`, `copernicus-census2011`) is still not produced by a script committed here.

> **Clip a district's grid to its real boundary.** `seed_pilot_data` builds Wayanad and Kodagu from a hand-typed bounding box, so their stored boundary is a rectangle and about 30% of cells sit outside the district. `clip_district_to_boundary` replaces the boundary with the Census 2011 polygon (`data/raw/boundaries/2011_Dist.shp`), deletes cells whose centroid is outside it (with their hazard and MHI rows), and re-allocates the census total over the remaining cells weighted by a WorldPop constrained raster.
>
> ```bash
> uv run python -m pipeline.jobs.clip_district_to_boundary --lgd 555 --shapefile-name Wayanad \
>     --worldpop /path/to/ind_ppp_2020_constrained.tif --dry-run     # drop --dry-run to apply
> ```
>
> The WorldPop raster is not in this repo (India-wide, about 530 MB). It runs in a single transaction with assertions after CSV backups to `data/backups/district_boundary_clip/`. It does not create the real edge cells the rectangle never covered, because it cannot score them. Applied to Wayanad only so far; Kodagu still has its rectangle. A constrained raster puts people only in settlement pixels, so most cells get 0 population, which also means high-hazard forest cells show 0 exposed people.

### Kodagu

```bash
uv run python pipeline/src/pipeline/jobs/seed_pilot_data.py                       # seeds Wayanad and Kodagu together
uv run python -m pipeline.jobs.harvest_osm_infrastructure --district Kodagu       # or --lgd 540
```

### Barpeta

```bash
# Flood susceptibility (Steps 1-10), run in order. Every milestone takes a
# registered district key (barpeta, dholpur, morena, wayanad, ...)
uv run python -m pipeline.hazard.flood.run_milestone_a barpeta    # Sentinel-1 STAC discovery
uv run python -m pipeline.hazard.flood.run_milestone_b barpeta    # SAR water mask
uv run python -m pipeline.hazard.flood.run_milestone_c barpeta    # permanent water + frequency stack
uv run python -m pipeline.hazard.flood.run_milestone_d barpeta    # HAND + cropland exclusion
uv run python -m pipeline.ingestion.fetch_worldpop --district barpeta   # optional population raster for E
uv run python -m pipeline.hazard.flood.run_milestone_e barpeta    # H3 aggregation + database load
#   B and C take --resolution (must match); E takes --clip-to-boundary

# Relocation artifacts: validate, rehearse, then load
uv run python pipeline/scripts/load_barpeta_relocation.py --check
uv run python pipeline/scripts/load_barpeta_relocation.py --dry-run
uv run python pipeline/scripts/load_barpeta_relocation.py --load

uv run python -m pipeline.jobs.harvest_osm_infrastructure --district Barpeta      # or --lgd 277
```

### Any other district (flood registry: `barpeta`, `dholpur`, `morena`, `wayanad`)

`pipeline/src/pipeline/hazard/flood/districts.py` holds the district registry. Add a `DistrictConfig` there to onboard a new district. After that, both the step-by-step milestone runners above (`run_milestone_a … e <district>`) and the one-shot runner below will accept its key.

```bash
uv run python -m pipeline.hazard.flood.run_district_flood dholpur morena          # Steps 5-10 + local DB load
#   --no-db skips the database load, --no-population skips WorldPop,
#   --s1-decimation N downsamples Sentinel-1 reads (default 4)

# Push already-computed results to another database (e.g. Neon) without recomputing
TARGET_DB_URL=postgresql://... uv run python -m pipeline.hazard.flood.sync_flood_to_db dholpur morena

# Then derive people and sites from the loaded hazard layer
uv run python -m pipeline.jobs.derive_habitations --district Dholpur --dry-run    # drop --dry-run to write
uv run python -m pipeline.jobs.derive_candidate_sites --district dholpur --dry-run
```

`derive_habitations` takes the district name as stored in `admin_boundary`. `derive_candidate_sites` takes the registry slug. Both accept `--dry-run` to report without writing.

### Accounts and generic ingest

```bash
uv run python -m pipeline.jobs.seed_national_account                              # national operations login
uv run python -m pipeline.jobs.ingest_flood_data path/to/sentinel1.csv            # validate + activate a Sentinel-1 artifact
```

### Checking a run

```bash
curl https://the-terra-391294275080.asia-southeast1.run.app/health/ready            # active serving_version run id
uv run python scripts/verify_b8_full_certification.py            # forecast pipeline certification
```

---

## 🔑 Pre-Seeded Demo Accounts

The database is seeded with official role accounts covering all administrative tiers:

| Role | Email | Password | Administrative Jurisdiction | Access Scope |
| :--- | :--- | :--- | :--- | :--- |
| **National Operations** | `gov@setu.gov.in` | `DemoOfficer123!` | All India (National Level) | Cross-district command, full allocation & scenario solver |
| **District Magistrate** | `officer@setu.gov.in` | `DemoOfficer123!` | Wayanad District (LGD 555) | Wayanad triage queue, site approval, local scenario simulation |
| **District Magistrate** | `officer_kodagu@setu.gov.in`| `DemoOfficer123!` | Kodagu District (LGD 540) | Kodagu triage queue, site approval, local scenario simulation |
| **NDRF Commander** | `rescue@setu.gov.in` | `DemoRescue123!` | Wayanad Sector / 4th BN | Real-time evacuation alerts, 72h forecast timelines, SAR telemetry |
| **Public Civilian** | `civilian@setu.gov.in` | `DemoCivilian123!` | Public Domain | Read-only risk dossier, public research stories, community feedback |

---

## 🌐 Application Navigation & Workspaces

The frontend provides dedicated views tailored for different operational users:

* **`/` (Public Landing):** Interactive 3D Earth Globe (`GlobeCanvas`) with atmospheric mist shaders, global disaster hotspots, scrollytelling narratives, and live impact statistics.
* **`/workspace` (Operational Hazard Workspace):** Three-panel triage command center (`HazardWorkspace`).
  * *Left Panel:* Top risk triage queue ranked by urgency or caseload.
  * *Center Panel:* MapLibre GL + Deck.gl H3 hexagonal vector map with layer switcher, confidence hatching, and coverage flags.
  * *Right Panel:* Deep cell dossier, physical terrain drivers (HAND, slope, inundation frequency), and 72-hour forecast alert timeline.
* **`/gov` (Government Command Portal):** Dual-mode interface (`GovWorkspace`) switching between an interactive **3D extruded hexagonal column canvas** over India (`India3DCanvas`) and high-resolution GIS map view, scoped to the officer's administrative jurisdiction.
* **`/relocation` (Relocation Decision Workspace):**
  * *Left Panel:* Vulnerable settlement demand queue filtered by triage tier.
  * *Center Panel:* 3D GIS corridors showing displacement vectors and candidate safe havens.
  * *Right Panel:* Google OR-Tools min-cost flow allocation controls, solved matching plans, and interactive **Capacity Simulation Modal** to test infrastructure investment ROI.
* **`/stories` (Public Research & Evidence):** Community narratives, historical loss timelines, and field evidence archives.
* **`/about` (Methodology & Architecture):** Comprehensive documentation of scientific thresholds, governance principles, and data provenance.
* **`/login` (Access Gateway):** Biometric and credential-based authentication with instant demo role selector.

---

## 📡 API Endpoint Summary

| Route | Method | Description | Auth / RBAC |
| :--- | :--- | :--- | :--- |
| `/auth/login` | `POST` | Authenticate user; returns identity and sets secure HTTP-only cookie + Bearer token | Public (Rate-limited) |
| `/auth/me` | `GET` | Retrieve active authenticated session identity and jurisdiction | Authenticated |
| `/auth/logout` | `POST` | Revoke session and clear cookies | Authenticated |
| `/zones` | `GET` | Query composite MHI cells with quantile breaks for map viewport | Public / Civilian |
| `/hazard/layers` | `GET` | Enumerate published static hazard layers with cell counts and confidence ranges | Public / Civilian |
| `/hazard/cells` | `GET` | Viewport query for specific hazard layer (e.g. `riverine_flood`) with coverage flags | Public / Civilian |
| `/hazard/cells/{h3}` | `GET` | Retrieve complete cell risk dossier and physical terrain drivers | Public / Civilian |
| `/habitations` | `GET` | Paginated triage queue ranked by Urgency ($PS_j$) or Caseload ($PS_j \times \text{Pop}_j$) | Public / Civilian |
| `/habitations/{id}/risk` | `GET` | Full habitation risk dossier: SoVI breakdown, loss history, and triage rationale | Public / Civilian |
| `/habitations/{id}/sites` | `GET` | Ranked candidate safe havens within radius with carrying capacity constraints | Public / Civilian |
| `/sites/{id}` | `GET` | Detailed candidate site audit: 4-lifeline carrying capacities and binding constraint | Public / Civilian |
| `/alerts/active` | `GET` | Active evacuation alerts ($MHI_{\text{live}} \ge 0.75$) requiring immediate civil action | Public / Civilian |
| `/alerts/forecast` | `GET` | 72-hour forecast alerts ($MHI_{\text{fcst}} \ge 0.75$) with issuing model and cycle metadata | Public / Civilian |
| `/plan/allocate` | `POST` | Solve optimal relocation matching via Google OR-Tools min-cost flow solver | Government Official |
| `/plan/benchmark` | `GET` | Side-by-side benchmark comparing external proposals against SETU optimization | Public / Civilian |
| `/scenario` | `POST` | Stateless sensitivity simulation evaluating parameter overrides ($\Delta \text{Rank}$, tier shifts) | Government Official |
| `/health/live` | `GET` | Kubernetes liveness probe | Public |
| `/health/ready` | `GET` | Deep readiness probe verifying PostgreSQL, PostGIS, and H3 extension health | Public |

---

## 🧪 Testing & Verification

The repository includes a comprehensive test suite covering unit math, spatial algorithms, API contracts, and database integrity:

```bash
# Run all unit and mock tests (600+ tests, excluding live database requirement)
uv run pytest -m "not db" -q

# Run complete test suite against local PostGIS database
uv run pytest -v

# Run the 10-Step Barpeta & Wayanad End-to-End Demo Verification Story
uv run python scripts/verify_demo_story.py

# Verify database migrations and schema consistency
uv run python infra/verify_db.py

# Validate OpenAPI contract compliance
uv run pytest tests/contract/test_openapi.py

# Export updated OpenAPI specification and synchronize frontend TypeScript types
pnpm export:openapi
pnpm generate:types
```

---

## 📄 License & Attribution

Developed for the **Smart India Hackathon (SIH)** under problem statement guidance from the **Ministry of Home Affairs (MHA) — National Disaster Response Force (NDRF) / Disaster Management Division**.

* Geospatial boundaries sourced in accordance with Survey of India and Local Government Directory (LGD) standards.
* Remote sensing data courtesy of European Space Agency (Copernicus Sentinel-1), NASA / JAXA (GPM IMERG), JRC (Global Surface Water), and Copernicus (GLO-30 DEM).
* Meteorological predictions powered by ECMWF Open Data and Open-Meteo.
* Demographics downscaled from Census of India 2011 and WorldPop (BSGM constrained).

---
*© 2026 SETU-DRR Platform · Hazard Red Zone & Relocation Decision Support Platform · All Rights Reserved.*
