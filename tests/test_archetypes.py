"""Tests for archetype detection and configuration loader."""

import pytest
from pathlib import Path
from unittest.mock import patch

from src.matching.archetypes import detect_archetype, load_archetypes


# ── Sample archetypes for unit tests (independent of profile.yaml) ──

SAMPLE_ARCHETYPES = {
    "automation_engineer": {
        "label": "Automation / Workflow Engineer",
        "keywords": ["automation", "n8n", "workflow", "zapier", "make", "process", "integration"],
        "proof_priorities": ["n8n workflows built", "processes automated", "time saved"],
        "cv_emphasis": ["automation tools", "integration experience", "process optimization"],
        "interview_themes": ["scaling automation", "cross-team collaboration", "technical debt in workflows"],
    },
    "revops_consultant": {
        "label": "RevOps / Revenue Operations Consultant",
        "keywords": ["revops", "revenue operations", "crm", "salesforce", "hubspot", "go-to-market"],
        "proof_priorities": ["revenue impact", "CRM implementations", "GTM alignment"],
        "cv_emphasis": ["revenue metrics", "CRM expertise", "cross-functional impact"],
        "interview_themes": ["GTM strategy", "sales-marketing alignment", "data-driven decisions"],
    },
    "ai_engineer": {
        "label": "AI / LLM Engineer",
        "keywords": ["ai engineer", "llm", "langchain", "rag", "agents", "ml", "deep learning", "openai", "claude"],
        "proof_priorities": ["AI systems deployed", "model performance metrics", "RAG implementations"],
        "cv_emphasis": ["AI/ML projects", "LLM integration", "production AI systems"],
        "interview_themes": ["AI architecture", "eval methodology", "responsible AI"],
    },
    "platform_engineer": {
        "label": "Platform / DevOps Engineer",
        "keywords": ["platform", "devops", "infrastructure", "cloud", "kubernetes", "terraform", "ci/cd"],
        "proof_priorities": ["infrastructure scaled", "deployment frequency", "reliability metrics"],
        "cv_emphasis": ["cloud infrastructure", "CI/CD pipelines", "system reliability"],
        "interview_themes": ["scaling challenges", "incident management", "developer experience"],
    },
    "solutions_architect": {
        "label": "Solutions Architect",
        "keywords": ["solutions architect", "technical architecture", "system design", "enterprise"],
        "proof_priorities": ["architectures designed", "enterprise integrations", "technical leadership"],
        "cv_emphasis": ["system design", "stakeholder communication", "technical strategy"],
        "interview_themes": ["architecture decisions", "trade-offs", "cross-team influence"],
    },
    "ai_transformation": {
        "label": "AI Transformation / Enablement Lead",
        "keywords": ["transformation", "enablement", "adoption", "change management", "ai strategy"],
        "proof_priorities": ["adoption rates", "team enablement", "change management"],
        "cv_emphasis": ["organizational change", "training programs", "AI adoption metrics"],
        "interview_themes": ["change resistance", "measuring adoption", "executive buy-in"],
    },
}


class TestDetectArchetype:
    """Tests for detect_archetype()."""

    def test_detect_automation_archetype(self):
        """n8n workflow automation engineer → automation_engineer."""
        result = detect_archetype(
            job_title="n8n workflow automation engineer",
            job_description="We need someone to build automation workflows using n8n and integrate with our existing systems.",
            archetypes=SAMPLE_ARCHETYPES,
        )
        assert result == "automation_engineer"

    def test_detect_ai_archetype(self):
        """Senior LLM Engineer, RAG systems → ai_engineer."""
        result = detect_archetype(
            job_title="Senior LLM Engineer, RAG systems",
            job_description="Build production RAG pipelines with LangChain and deploy AI agents.",
            archetypes=SAMPLE_ARCHETYPES,
        )
        assert result == "ai_engineer"

    def test_detect_revops_archetype(self):
        """RevOps consultant with CRM experience → revops_consultant."""
        result = detect_archetype(
            job_title="RevOps Consultant",
            job_description="Implement and optimize HubSpot CRM, align go-to-market strategy with revenue operations.",
            archetypes=SAMPLE_ARCHETYPES,
        )
        assert result == "revops_consultant"

    def test_detect_platform_archetype(self):
        """DevOps / platform role → platform_engineer."""
        result = detect_archetype(
            job_title="Platform Engineer",
            job_description="Build and maintain cloud infrastructure with Kubernetes and Terraform. Improve CI/CD pipelines.",
            archetypes=SAMPLE_ARCHETYPES,
        )
        assert result == "platform_engineer"

    def test_detect_solutions_architect_archetype(self):
        """Solutions architect role → solutions_architect."""
        result = detect_archetype(
            job_title="Solutions Architect",
            job_description="Design enterprise technical architecture and system design.",
            archetypes=SAMPLE_ARCHETYPES,
        )
        assert result == "solutions_architect"

    def test_no_match_returns_generic(self):
        """Office Manager has no matching keywords → generic."""
        result = detect_archetype(
            job_title="Office Manager",
            job_description="Manage office supplies, organize team events, handle correspondence.",
            archetypes=SAMPLE_ARCHETYPES,
        )
        assert result == "generic"

    def test_case_insensitive_matching(self):
        """Keywords should match regardless of case."""
        result = detect_archetype(
            job_title="AUTOMATION ENGINEER",
            job_description="Build N8N workflows for PROCESS automation.",
            archetypes=SAMPLE_ARCHETYPES,
        )
        assert result == "automation_engineer"

    def test_best_match_wins_on_count(self):
        """When multiple archetypes match, the one with the most keyword hits wins."""
        result = detect_archetype(
            job_title="AI Automation Engineer",
            job_description="Build automation workflows using n8n, zapier, and make. Integrate with process tools.",
            archetypes=SAMPLE_ARCHETYPES,
        )
        # automation has: automation, n8n, workflow(no), zapier, make, process, integration → 6 hits
        # ai_engineer has: ai engineer(no—split), agents(no) → fewer hits
        assert result == "automation_engineer"

    def test_empty_description(self):
        """Should still work with an empty description."""
        result = detect_archetype(
            job_title="LLM Engineer",
            job_description="",
            archetypes=SAMPLE_ARCHETYPES,
        )
        assert result == "ai_engineer"

    def test_empty_archetypes_returns_generic(self):
        """If no archetypes are defined, return generic."""
        result = detect_archetype(
            job_title="Anything",
            job_description="Some description",
            archetypes={},
        )
        assert result == "generic"


class TestLoadArchetypes:
    """Tests for load_archetypes() — loading from profile.yaml."""

    def test_load_archetypes_from_profile(self):
        """Verify that archetypes are loaded from profile.yaml and contain expected keys."""
        archetypes = load_archetypes()
        assert isinstance(archetypes, dict)
        assert len(archetypes) >= 1, "At least one archetype should be defined"

        # Each archetype must have the required keys
        for key, config in archetypes.items():
            assert "label" in config, f"Archetype '{key}' missing 'label'"
            assert "keywords" in config, f"Archetype '{key}' missing 'keywords'"
            assert "proof_priorities" in config, f"Archetype '{key}' missing 'proof_priorities'"
            assert "cv_emphasis" in config, f"Archetype '{key}' missing 'cv_emphasis'"
            assert "interview_themes" in config, f"Archetype '{key}' missing 'interview_themes'"
            assert isinstance(config["keywords"], list), f"Archetype '{key}' keywords must be a list"

    def test_load_archetypes_contains_expected_archetypes(self):
        """Verify that the 6 defined archetypes are present."""
        archetypes = load_archetypes()
        expected = {
            "automation_engineer",
            "revops_consultant",
            "ai_engineer",
            "platform_engineer",
            "solutions_architect",
            "ai_transformation",
        }
        assert expected.issubset(set(archetypes.keys())), (
            f"Missing archetypes: {expected - set(archetypes.keys())}"
        )

    def test_load_archetypes_with_custom_path(self, tmp_path):
        """Should load from a custom YAML file path."""
        custom_yaml = tmp_path / "custom_profile.yaml"
        custom_yaml.write_text(
            "archetypes:\n"
            "  test_role:\n"
            "    label: Test Role\n"
            "    keywords: [test, example]\n"
            "    proof_priorities: [testing]\n"
            "    cv_emphasis: [test coverage]\n"
            "    interview_themes: [testing strategies]\n"
        )
        archetypes = load_archetypes(profile_path=custom_yaml)
        assert "test_role" in archetypes
        assert archetypes["test_role"]["label"] == "Test Role"

    def test_load_archetypes_missing_section_returns_empty(self, tmp_path):
        """If profile.yaml has no archetypes section, return empty dict."""
        custom_yaml = tmp_path / "no_archetypes.yaml"
        custom_yaml.write_text("candidate:\n  name: Test\n")
        archetypes = load_archetypes(profile_path=custom_yaml)
        assert archetypes == {}
