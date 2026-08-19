PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    source_date TEXT,
    content_hash TEXT NOT NULL,
    ingestion_status TEXT NOT NULL DEFAULT 'ready',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS evidence_units (
    evidence_unit_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content TEXT NOT NULL,
    location_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    source_date TEXT,
    content_hash TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(source_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sources_case_id ON sources(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_case_id ON evidence_units(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source_id ON evidence_units(source_id);

CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    enterprise_name TEXT NOT NULL,
    profile_type TEXT NOT NULL CHECK (profile_type IN ('historical', 'current')),
    ontology_version TEXT NOT NULL,
    information_gaps_json TEXT NOT NULL DEFAULT '[]',
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS profile_items (
    profile_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    section_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    value_json TEXT NOT NULL,
    value_type TEXT NOT NULL,
    information_status TEXT NOT NULL,
    content_role TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    subject TEXT,
    value_scope TEXT,
    unit TEXT,
    source_date TEXT,
    reporting_period TEXT,
    event_date TEXT,
    effective_date TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    extraction_method TEXT NOT NULL DEFAULT 'manual',
    ontology_version TEXT NOT NULL DEFAULT '0.8.0',
    PRIMARY KEY (profile_id, item_id),
    FOREIGN KEY (profile_id) REFERENCES profiles(profile_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profile_relations (
    profile_id TEXT NOT NULL,
    relation_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    information_status TEXT NOT NULL,
    content_role TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (profile_id, relation_id),
    FOREIGN KEY (profile_id) REFERENCES profiles(profile_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profile_topic_analyses (
    profile_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    model TEXT,
    api_meta_json TEXT NOT NULL DEFAULT '[]',
    react_trace_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_id, dimension_id),
    FOREIGN KEY (profile_id) REFERENCES profiles(profile_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_profile_topic_analysis_profile
    ON profile_topic_analyses(profile_id);

CREATE TABLE IF NOT EXISTS industry_profiles (
    profile_id TEXT PRIMARY KEY,
    industry_id TEXT NOT NULL,
    industry_name TEXT NOT NULL,
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    insights_json TEXT NOT NULL DEFAULT '[]',
    information_gaps_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected')),
    generation_method TEXT NOT NULL DEFAULT 'llm',
    model TEXT,
    api_meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_industry_profiles_lookup
    ON industry_profiles(industry_id, review_status);

CREATE TABLE IF NOT EXISTS peer_cohorts (
    cohort_id TEXT PRIMARY KEY,
    industry_id TEXT NOT NULL,
    cohort_name TEXT NOT NULL,
    fiscal_period TEXT NOT NULL,
    company_case_ids_json TEXT NOT NULL,
    selection_rule TEXT NOT NULL,
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected'))
);

CREATE TABLE IF NOT EXISTS comparable_metric_definitions (
    metric_id TEXT PRIMARY KEY,
    approval_direction_id TEXT NOT NULL,
    approval_point_id TEXT NOT NULL,
    name TEXT NOT NULL,
    comparison_direction TEXT NOT NULL
        CHECK (comparison_direction IN ('higher_is_better', 'lower_is_better')),
    unit TEXT NOT NULL,
    value_scope TEXT NOT NULL,
    missing_value_rule TEXT NOT NULL DEFAULT 'exclude',
    tie_rule TEXT NOT NULL DEFAULT 'dense_rank',
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected'))
);

CREATE TABLE IF NOT EXISTS comparable_metric_values (
    cohort_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    value REAL NOT NULL,
    reporting_period TEXT NOT NULL,
    unit TEXT NOT NULL,
    source_profile_id TEXT NOT NULL,
    source_item_id TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected')),
    PRIMARY KEY (cohort_id, metric_id, case_id),
    FOREIGN KEY (cohort_id) REFERENCES peer_cohorts(cohort_id) ON DELETE CASCADE,
    FOREIGN KEY (metric_id) REFERENCES comparable_metric_definitions(metric_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_metric_values_lookup
    ON comparable_metric_values(cohort_id, metric_id);

CREATE TABLE IF NOT EXISTS metric_profile_field_bindings (
    metric_id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    FOREIGN KEY (metric_id) REFERENCES comparable_metric_definitions(metric_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS domain_approval_reports (
    report_id TEXT PRIMARY KEY,
    cohort_id TEXT,
    case_id TEXT NOT NULL,
    domain_id TEXT NOT NULL,
    one_sentence_summary TEXT NOT NULL,
    approval_points_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_domain_approval_reports_lookup
    ON domain_approval_reports(cohort_id, case_id, domain_id);

CREATE TABLE IF NOT EXISTS direction_ranking_results (
    cohort_id TEXT NOT NULL,
    section_id TEXT NOT NULL,
    comparable_company_count INTEGER NOT NULL,
    ranking_groups_json TEXT NOT NULL,
    not_comparable_case_ids_json TEXT NOT NULL DEFAULT '[]',
    rank_points_json TEXT NOT NULL,
    source_section_report_ids_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected')),
    PRIMARY KEY (cohort_id, section_id),
    FOREIGN KEY (cohort_id) REFERENCES peer_cohorts(cohort_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_direction_ranking_results_lookup
    ON direction_ranking_results(cohort_id, section_id, review_status);

CREATE TABLE IF NOT EXISTS approval_point_definitions (
    approval_point_id TEXT PRIMARY KEY,
    approval_direction_id TEXT NOT NULL,
    title TEXT NOT NULL,
    enterprise_field_ids_json TEXT NOT NULL DEFAULT '[]',
    metric_ids_json TEXT NOT NULL DEFAULT '[]',
    industry_dimension_ids_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_approval_point_definitions_lookup
    ON approval_point_definitions(approval_direction_id, review_status);

CREATE TABLE IF NOT EXISTS composite_approval_reports (
    report_id TEXT PRIMARY KEY,
    cohort_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    overall_judgment TEXT NOT NULL,
    key_risks_json TEXT NOT NULL DEFAULT '[]',
    mitigating_factors_json TEXT NOT NULL DEFAULT '[]',
    judgment_boundaries_json TEXT NOT NULL DEFAULT '[]',
    verification_priorities_json TEXT NOT NULL DEFAULT '[]',
    source_domain_report_ids_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected')),
    FOREIGN KEY (cohort_id) REFERENCES peer_cohorts(cohort_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_composite_approval_reports_lookup
    ON composite_approval_reports(cohort_id, case_id, review_status);

CREATE TABLE IF NOT EXISTS enterprise_overall_assessments (
    assessment_id TEXT PRIMARY KEY,
    cohort_id TEXT,
    case_id TEXT NOT NULL,
    rating_level TEXT NOT NULL CHECK (rating_level IN ('AAA1', 'AAA2', 'AAA3', 'AA1', 'AA2', 'AA3', 'A1', 'A2', 'A3', 'BBB1', 'BBB2', 'BBB3', 'BB1', 'BB2', 'BB3', 'B1', 'B2', 'CCC1', 'CC1', 'C1', 'D1')),
    overall_judgment TEXT NOT NULL,
    rating_rationale_json TEXT NOT NULL,
    core_risks_json TEXT NOT NULL DEFAULT '[]',
    mitigating_factors_json TEXT NOT NULL DEFAULT '[]',
    rating_boundaries_json TEXT NOT NULL DEFAULT '[]',
    verification_priorities_json TEXT NOT NULL DEFAULT '[]',
    source_direction_report_ids_json TEXT NOT NULL,
    source_direction_ranking_sections_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL,
    recommendation TEXT NOT NULL DEFAULT 'conditional_proceed'
        CHECK (recommendation IN ('proceed_with_caution', 'proceed_with_review', 'conditional_proceed', 'do_not_proceed')),
    strong_constraint_failed_count INTEGER NOT NULL DEFAULT 0,
    weak_constraint_failed_count INTEGER NOT NULL DEFAULT 0,
    direction_results_json TEXT NOT NULL DEFAULT '[]',
    is_experimental INTEGER NOT NULL DEFAULT 0 CHECK (is_experimental IN (0, 1)),
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_overall_assessments_lookup
    ON enterprise_overall_assessments(cohort_id, case_id, review_status);
