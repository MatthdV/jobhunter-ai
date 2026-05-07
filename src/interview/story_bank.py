"""Interview story bank — load, match, and format STAR+R stories."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).parent.parent / "config" / "stories.yaml"


@dataclass
class Story:
    """A single STAR+R interview story."""

    id: str
    title: str
    archetypes: list[str]
    tags: list[str]
    situation: str
    task: str
    action: str
    result: str
    reflection: str


class StoryBank:
    """Load, filter, match, and persist STAR+R interview stories."""

    def __init__(self, stories_path: Path | None = None) -> None:
        self._path = stories_path or _DEFAULT_PATH
        if not self._path.exists():
            raise FileNotFoundError(f"Stories file not found: {self._path}")
        self._stories: list[Story] = self._load()

    @property
    def all_stories(self) -> list[Story]:
        return list(self._stories)

    def get_stories_for_archetype(self, archetype: str) -> list[Story]:
        """Return stories matching the given archetype. 'generic' returns all."""
        if archetype == "generic":
            return list(self._stories)
        return [s for s in self._stories if archetype in s.archetypes]

    def get_stories_for_job(
        self,
        job_title: str,
        job_description: str,
        archetype: str,
        max_stories: int = 6,
    ) -> list[Story]:
        """Match stories to a job by archetype + keyword overlap in tags."""
        candidates = self.get_stories_for_archetype(archetype)
        if not candidates:
            return []

        text = f"{job_title} {job_description}".lower()

        def _relevance(story: Story) -> int:
            return sum(1 for tag in story.tags if tag.lower() in text)

        ranked = sorted(candidates, key=_relevance, reverse=True)
        # Only keep stories with at least one tag match
        ranked = [s for s in ranked if _relevance(s) > 0]
        return ranked[:max_stories]

    def format_for_evaluation(self, stories: list[Story]) -> str:
        """Format stories for inclusion in the scorer prompt (Block F)."""
        if not stories:
            return ""

        lines: list[str] = []
        for story in stories:
            lines.append(f"### {story.title} (id: {story.id})")
            lines.append(f"- Tags: {', '.join(story.tags)}")
            lines.append(f"- Situation: {story.situation}")
            lines.append(f"- Task: {story.task}")
            lines.append(f"- Action: {story.action}")
            lines.append(f"- Result: {story.result}")
            lines.append(f"- Reflection: {story.reflection}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def add_story(self, story: dict) -> None:
        """Append a new story to stories.yaml and the in-memory list."""
        story_id = story["id"]
        if any(s.id == story_id for s in self._stories):
            raise ValueError(f"Story '{story_id}' already exists")

        parsed = self._parse_story(story)
        self._stories.append(parsed)

        with self._path.open() as fh:
            data = yaml.safe_load(fh) or {}
        data.setdefault("stories", []).append(story)
        with self._path.open("w") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True)

    def _load(self) -> list[Story]:
        with self._path.open() as fh:
            data = yaml.safe_load(fh) or {}
        raw_stories = data.get("stories", [])
        stories: list[Story] = []
        for raw in raw_stories:
            stories.append(self._parse_story(raw))
        return stories

    @staticmethod
    def _parse_story(raw: dict) -> Story:
        star = raw.get("star", {})
        return Story(
            id=raw["id"],
            title=raw.get("title", ""),
            archetypes=raw.get("archetypes", []),
            tags=raw.get("tags", []),
            situation=star.get("situation", ""),
            task=star.get("task", ""),
            action=star.get("action", ""),
            result=star.get("result", ""),
            reflection=star.get("reflection", ""),
        )
