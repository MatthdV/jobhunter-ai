"""Tests for the interview story bank — TDD-first."""

import copy
from pathlib import Path

import pytest
import yaml

from src.interview.story_bank import Story, StoryBank


@pytest.fixture()
def stories_path(tmp_path: Path) -> Path:
    """Create a temporary stories.yaml with test data."""
    data = {
        "stories": [
            {
                "id": "story_n8n_migration",
                "title": "Migration of 200+ workflows from Zapier to n8n",
                "archetypes": ["automation_engineer", "platform_engineer"],
                "tags": ["scaling", "migration", "automation", "cost-reduction"],
                "star": {
                    "situation": "Company spending 50k€/month on Zapier",
                    "task": "Lead migration to n8n within 3 months",
                    "action": "Mapped workflows, built tooling, trained 20 users",
                    "result": "Saved 40k€/month, 3x speed improvement",
                    "reflection": "Change management was hardest part",
                },
            },
            {
                "id": "story_revops_alignment",
                "title": "Unified sales-marketing pipeline with HubSpot",
                "archetypes": ["revops_consultant", "ai_transformation"],
                "tags": ["crm", "alignment", "revenue", "go-to-market"],
                "star": {
                    "situation": "Sales and marketing using separate tools",
                    "task": "Implement unified RevOps stack on HubSpot",
                    "action": "Mapped GTM process, automated lead scoring",
                    "result": "30% increase in SQL-to-close rate",
                    "reflection": "Data quality was the real bottleneck",
                },
            },
            {
                "id": "story_ai_rag",
                "title": "Built RAG system for internal knowledge base",
                "archetypes": ["ai_engineer"],
                "tags": ["ai", "rag", "llm", "knowledge-base"],
                "star": {
                    "situation": "Support team spending 2h/day searching docs",
                    "task": "Build an AI-powered search system",
                    "action": "Designed RAG pipeline with embeddings + Claude",
                    "result": "Reduced search time by 80%",
                    "reflection": "Chunking strategy matters more than model choice",
                },
            },
        ]
    }
    path = tmp_path / "stories.yaml"
    path.write_text(yaml.dump(data, default_flow_style=False))
    return path


@pytest.fixture()
def bank(stories_path: Path) -> StoryBank:
    return StoryBank(stories_path=stories_path)


class TestLoadStories:
    def test_load_stories_from_yaml(self, bank: StoryBank) -> None:
        """All stories are loaded from the YAML file."""
        stories = bank.all_stories
        assert len(stories) == 3
        assert all(isinstance(s, Story) for s in stories)

    def test_story_fields_populated(self, bank: StoryBank) -> None:
        """Each Story dataclass has all STAR+R fields."""
        story = bank.all_stories[0]
        assert story.id == "story_n8n_migration"
        assert story.title == "Migration of 200+ workflows from Zapier to n8n"
        assert "automation_engineer" in story.archetypes
        assert story.situation  # non-empty
        assert story.task
        assert story.action
        assert story.result
        assert story.reflection

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Empty stories file yields zero stories without crashing."""
        path = tmp_path / "empty.yaml"
        path.write_text("stories: []")
        bank = StoryBank(stories_path=path)
        assert bank.all_stories == []

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            StoryBank(stories_path=tmp_path / "nope.yaml")


class TestFilterByArchetype:
    def test_filter_automation_engineer(self, bank: StoryBank) -> None:
        stories = bank.get_stories_for_archetype("automation_engineer")
        assert len(stories) == 1
        assert stories[0].id == "story_n8n_migration"

    def test_filter_revops_consultant(self, bank: StoryBank) -> None:
        stories = bank.get_stories_for_archetype("revops_consultant")
        assert len(stories) == 1
        assert stories[0].id == "story_revops_alignment"

    def test_filter_generic_returns_all(self, bank: StoryBank) -> None:
        """'generic' archetype returns all stories (no filtering)."""
        stories = bank.get_stories_for_archetype("generic")
        assert len(stories) == 3

    def test_filter_unknown_returns_empty(self, bank: StoryBank) -> None:
        """Unknown archetype (non-generic) returns empty list."""
        stories = bank.get_stories_for_archetype("quantum_physicist")
        assert stories == []


class TestMatchStoriesToJob:
    def test_n8n_job_gets_migration_story(self, bank: StoryBank) -> None:
        """Job about n8n → story_n8n_migration ranked first."""
        stories = bank.get_stories_for_job(
            job_title="n8n Automation Engineer",
            job_description="Looking for someone to build and scale n8n workflows",
            archetype="automation_engineer",
        )
        assert len(stories) >= 1
        assert stories[0].id == "story_n8n_migration"

    def test_crm_job_gets_revops_story(self, bank: StoryBank) -> None:
        stories = bank.get_stories_for_job(
            job_title="Revenue Operations Manager",
            job_description="CRM alignment, go-to-market strategy",
            archetype="revops_consultant",
        )
        assert len(stories) >= 1
        assert stories[0].id == "story_revops_alignment"

    def test_max_stories_respected(self, bank: StoryBank) -> None:
        stories = bank.get_stories_for_job(
            job_title="Engineer",
            job_description="automation scaling migration crm ai rag",
            archetype="generic",
            max_stories=2,
        )
        assert len(stories) <= 2

    def test_no_match_returns_empty(self, bank: StoryBank) -> None:
        stories = bank.get_stories_for_job(
            job_title="Office Manager",
            job_description="Handle mail and schedule meetings",
            archetype="quantum_physicist",
        )
        assert stories == []


class TestFormatForEvaluation:
    def test_format_contains_star_fields(self, bank: StoryBank) -> None:
        stories = bank.all_stories[:1]
        text = bank.format_for_evaluation(stories)
        assert "story_n8n_migration" in text
        assert "Situation:" in text
        assert "Task:" in text
        assert "Action:" in text
        assert "Result:" in text
        assert "Reflection:" in text

    def test_format_empty_list(self, bank: StoryBank) -> None:
        text = bank.format_for_evaluation([])
        assert text == ""

    def test_format_multiple_stories(self, bank: StoryBank) -> None:
        stories = bank.all_stories[:2]
        text = bank.format_for_evaluation(stories)
        assert "story_n8n_migration" in text
        assert "story_revops_alignment" in text


class TestAddStory:
    def test_add_story_persists(self, bank: StoryBank, stories_path: Path) -> None:
        new_story = {
            "id": "story_new",
            "title": "New test story",
            "archetypes": ["ai_engineer"],
            "tags": ["test"],
            "star": {
                "situation": "Test situation",
                "task": "Test task",
                "action": "Test action",
                "result": "Test result",
                "reflection": "Test reflection",
            },
        }
        bank.add_story(new_story)

        # Verify in-memory
        assert len(bank.all_stories) == 4
        assert bank.all_stories[-1].id == "story_new"

        # Verify on disk
        reloaded = StoryBank(stories_path=stories_path)
        assert len(reloaded.all_stories) == 4
        assert reloaded.all_stories[-1].id == "story_new"

    def test_add_duplicate_id_raises(self, bank: StoryBank) -> None:
        dup = {
            "id": "story_n8n_migration",
            "title": "Duplicate",
            "archetypes": [],
            "tags": [],
            "star": {
                "situation": "x", "task": "x", "action": "x",
                "result": "x", "reflection": "x",
            },
        }
        with pytest.raises(ValueError, match="already exists"):
            bank.add_story(dup)
