"""Human-readable labels for machine-readable column names."""

from __future__ import annotations

# Canonical labels for columns shown to humans in the dashboard,
# "Why this score?" expanders, and the README data dictionary.
# Columns not listed here fall back to _pretty() (title-case, underscores→spaces).
COLUMN_LABELS: dict[str, str] = {
    # Evidence quality decomposition (the two required entries)
    "evidence_quality_hits": (
        "Evidence quality hits (distinct pages + distinct keywords)"
    ),
    "evidence_quality_pages": "Evidence quality: distinct pages",
    # Other hits
    "maritime_relevance_hits": "Maritime relevance hits",
    "theme_fit_hits": "Theme fit hits",
    "maturity_signals_hits": "Maturity signals hits",
    # Matched keywords
    "evidence_quality_matched": "Evidence quality: matched keywords",
    "maritime_relevance_matched": "Maritime relevance: matched keywords",
    "theme_fit_matched": "Theme fit: matched keywords",
    "maturity_signals_matched": "Maturity signals: matched keywords",
    # Reviewer overrides
    "maritime_relevance_override": "Maritime relevance override (0–5)",
    "theme_fit_override": "Theme fit override (0–5)",
    "maturity_signals_override": "Maturity signals override (0–5)",
    "evidence_quality_override": "Evidence quality override (0–5)",
    "theme_override": "Theme override (quadrant key)",
    # Quadrant hits
    "decarbonisation_energy_hits": "Decarbonisation & Energy hits",
    "digitalisation_ai_hits": "Digitalisation & AI hits",
    "logistics_operations_hits": "Logistics & Operations hits",
    "safety_security_hits": "Safety & Security hits",
    # Quadrant matched
    "decarbonisation_energy_matched": "Decarbonisation & Energy: matched keywords",
    "digitalisation_ai_matched": "Digitalisation & AI: matched keywords",
    "logistics_operations_matched": "Logistics & Operations: matched keywords",
    "safety_security_matched": "Safety & Security: matched keywords",
}
