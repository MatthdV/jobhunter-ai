#!/usr/bin/env python3
"""
Profile Analyzer
Analyze portfolio and generate insights for job search
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Skill:
    name: str
    category: str
    level: str = "intermediate"  # beginner, intermediate, expert


@dataclass
class Experience:
    title: str
    company: str
    duration: str
    description: str


class ProfileAnalyzer:
    """Analyze professional profile and generate job search insights.

    TODO (Phase 2): Load tech_keywords, target_roles, and target_companies
    from src/config/profile.yaml instead of hardcoding them here.
    The canonical data lives in profile.yaml — these hardcoded lists are
    a temporary duplicate that will diverge if profile.yaml is updated.
    """

    def __init__(self) -> None:
        # TODO: replace with yaml.safe_load(Path("src/config/profile.yaml").read_text())
        self.tech_keywords: dict[str, list[str]] = {
            'languages': ['Python', 'JavaScript', 'TypeScript', 'Go', 'Java', 'SQL', 'Bash'],
            'frameworks': ['React', 'Next.js', 'Node.js', 'Express', 'Django', 'FastAPI'],
            'cloud': ['AWS', 'GCP', 'Azure', 'Docker', 'Kubernetes', 'Terraform'],
            'automation': ['n8n', 'Zapier', 'Make', 'GitHub Actions', 'CI/CD'],
            'ai': ['OpenAI', 'Claude', 'LLM', 'RAG', 'Agents', 'MCP'],
            'data': ['PostgreSQL', 'MongoDB', 'Redis', 'Prisma', 'BigQuery'],
            'tools': ['Git', 'Linux', 'Vim', 'VS Code', 'Figma', 'Notion'],
        }

        self.target_roles: list[str] = [
            'Automation Engineer',
            'AI Engineer',
            'RevOps Consultant',
            'Platform Engineer',
            'DevOps Engineer',
            'Solutions Architect',
            'Technical Lead',
        ]

        # Compile patterns once for performance
        self._senior_pattern = re.compile(r'\b(senior|lead|architect|principal)\b')
        self._management_pattern = re.compile(r'\b(manager|director|head of)\b')
        self._email_pattern = re.compile(r'[\w.\-]+@[\w.\-]+\.\w+')
        self._years_patterns = [
            re.compile(r'(\d+)\+?\s*years?\s*(?:of\s*)?experience', re.IGNORECASE),
            re.compile(r'experience\s*:\s*(\d+)\+?\s*years?', re.IGNORECASE),
            re.compile(r'(\d{4})\s*-\s*(present|now|current)', re.IGNORECASE),
        ]

    def analyze_text(self, text: str) -> dict[str, Any]:
        """Analyze text content for skills and keywords."""
        if not text or not isinstance(text, str):
            raise ValueError("text must be a non-empty string")

        text_lower = text.lower()

        # Deduplicate skills by name
        seen: set[str] = set()
        found_skills: list[dict[str, str]] = []
        for category, keywords in self.tech_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text_lower and keyword not in seen:
                    seen.add(keyword)
                    found_skills.append({'name': keyword, 'category': category})

        indicators = {
            'senior_mentions': len(self._senior_pattern.findall(text_lower)),
            'management_mentions': len(self._management_pattern.findall(text_lower)),
            'years_exp': self._extract_years_experience(text),
        }

        return {
            'skills': found_skills,
            'indicators': indicators,
            'word_count': len(text.split()),
            'has_portfolio': 'portfolio' in text_lower or 'github' in text_lower,
            'has_contact': bool(self._email_pattern.search(text)),
        }

    def _extract_years_experience(self, text: str) -> int:
        """Extract years of experience from text."""
        current_year = datetime.now().year

        for i, pattern in enumerate(self._years_patterns):
            match = pattern.search(text)
            if match:
                if i == 2:
                    # Date range pattern: (start_year) - (present|now|current)
                    # group(2) is the temporal word, group(1) is the start year
                    start_year = int(match.group(1))
                    return max(0, current_year - start_year)
                else:
                    return int(match.group(1))

        return 0

    def generate_optimized_headline(self, current_headline: str = '') -> list[str]:
        """Generate optimized LinkedIn headline options.

        If current_headline is provided, it is prepended so comparison
        against the suggested alternatives is straightforward.
        """
        suggestions = [
            "Automation & AI Engineer | RevOps Consultant | Building Intelligent Systems",
            "AI Automation Expert | n8n, OpenAI, Claude | Remote-First Consultant",
            "RevOps & AI Engineer | Process Automation | Full-Stack Solutions",
            "Technical Lead - AI & Automation | SaaS & FinTech | 10+ Years Experience",
        ]
        if current_headline and current_headline not in suggestions:
            return [current_headline] + suggestions
        return suggestions

    def generate_about_section(self, profile_data: dict[str, Any]) -> str:
        """Generate a LinkedIn About section template from profile data.

        Returns a template with placeholder metrics that must be replaced
        with real data before publishing. Placeholders are marked with
        [FILL: description] so they are impossible to accidentally publish.
        """
        if not isinstance(profile_data, dict):
            raise ValueError("profile_data must be a dict")

        years = profile_data.get('years_exp', 10)
        years_str = f"{years}+" if isinstance(years, int) else str(years)

        # Caller must supply concrete achievements — placeholders are intentional
        achievement_1 = profile_data.get('achievement_1', '[FILL: -X% metric for specific client]')
        achievement_2 = profile_data.get('achievement_2', '[FILL: +Y% outcome via automation]')

        about = f"""🚀 Automation & AI Engineer | RevOps Consultant

Je transforme les processus métier complexes en systèmes automatisés intelligents.

💡 Ce que je fais :
• Architecture d'agents IA autonomes (OpenAI, Claude, n8n)
• Automation RevOps : CRM, pipelines, reporting
• Développement full-stack : React, Node.js, Python
• Cloud & DevOps : AWS, Docker, CI/CD

🎯 Résultats concrets :
• {years_str} ans d'expérience en automation et IA
• {achievement_1}
• {achievement_2}

🛠️ Stack technique :
AI/LLM : OpenAI, Claude, LangChain, RAG
Automation : n8n, Make, Zapier, GitHub Actions
Frontend : React, Next.js, TypeScript, Tailwind
Backend : Node.js, Python, PostgreSQL, Prisma
Cloud : AWS, Vercel, Docker

📍 Full Remote | Disponible pour missions longue durée

💬 Parlons de votre projet :
→ Automation de processus
→ Intégration IA dans vos outils
→ Consulting RevOps
"""
        return about

    def suggest_improvements(self, profile_data: dict[str, Any]) -> list[dict[str, str]]:
        """Suggest profile improvements based on profile data."""
        if not isinstance(profile_data, dict):
            raise ValueError("profile_data must be a dict")

        suggestions: list[dict[str, str]] = []

        if not profile_data.get('headline') or len(profile_data['headline']) < 50:
            suggestions.append({
                'section': 'headline',
                'priority': 'high',
                'issue': 'Headline trop courte ou générique',
                'suggestion': 'Utiliser : "Automation & AI Engineer | RevOps Consultant | Building Intelligent Systems"',  # noqa: E501
                'impact': 'Augmente visibilité recherche de 40%',
            })

        if not profile_data.get('about') or len(profile_data['about']) < 500:
            suggestions.append({
                'section': 'about',
                'priority': 'high',
                'issue': 'Section About manquante ou trop courte',
                'suggestion': 'Ajouter section structurée avec stack, résultats, CTA',
                'impact': '+60% de messages de recruteurs',
            })

        if not profile_data.get('featured_projects'):
            suggestions.append({
                'section': 'featured',
                'priority': 'medium',
                'issue': 'Pas de projets mis en avant',
                'suggestion': 'Ajouter 3 projets : Trading Bot, JobHunter AI, Portfolio',
                'impact': 'Démontre expertise technique concrète',
            })

        skills = profile_data.get('skills', [])
        skill_names = {s if isinstance(s, str) else s.get('name', '') for s in skills}
        priority_skills = {'AI Automation', 'n8n', 'RevOps', 'LangChain', 'RAG', 'MCP'}
        if not priority_skills.intersection(skill_names):
            suggestions.append({
                'section': 'skills',
                'priority': 'medium',
                'issue': 'Compétences à optimiser',
                'suggestion': 'Top 3 : AI Automation, n8n, RevOps. Ajouter : LangChain, RAG, MCP',
                'impact': 'Meilleur matching algorithmique',
            })

        return suggestions

    def generate_job_search_strategy(self) -> dict[str, Any]:
        """Generate job search strategy."""
        return {
            'target_roles': [
                {'title': 'Automation Engineer', 'match': 95, 'salary': '80-120k€'},
                {'title': 'AI Engineer', 'match': 90, 'salary': '90-130k€'},
                {'title': 'RevOps Consultant', 'match': 95, 'salary': '700-1000€/jour'},
                {'title': 'Platform Engineer', 'match': 85, 'salary': '85-120k€'},
                {'title': 'Solutions Architect', 'match': 80, 'salary': '100-140k€'},
            ],
            'target_companies': {
                'fintech': ['Qonto', 'Spendesk', 'Alan', 'Lydia', 'Payfit'],
                'saas': ['Notion', 'Figma', 'Linear', 'Vercel', 'Supabase'],
                'consulting': ['Theodo', 'BAM', 'Malt', 'Comet', 'Aneo'],
            },
            'keywords_for_search': [
                'automation engineer',
                'AI engineer',
                'RevOps',
                'n8n',
                'workflow automation',
                'LLM integration',
                'process optimization',
            ],
            'content_strategy': [
                "Case study : Comment j'ai automatisé [process] pour [client]",
                "Tutorial n8n + OpenAI : Build your first AI agent",
                "Retour d'expérience : Migration CRM + gains mesurables",
            ],
        }


def main() -> None:
    """Demo analysis."""
    analyzer = ProfileAnalyzer()

    sample_text = """
    Matthieu de Villele - Automation & AI Engineer
    10+ years experience in automation, RevOps, and AI systems.
    Expert in n8n, OpenAI, Claude, React, Node.js, Python.
    Built trading bots, job automation systems, and CRM integrations.
    Full remote consultant available for FinTech and SaaS companies.
    """

    analysis = analyzer.analyze_text(sample_text)

    print("=" * 60)
    print("ANALYSE DE PROFIL")
    print("=" * 60)
    print(f"\nSkills détectés : {len(analysis['skills'])}")
    for skill in analysis['skills'][:10]:
        print(f"   • {skill['name']} ({skill['category']})")

    print("\nIndicateurs :")
    print(f"   • Mentions senior : {analysis['indicators']['senior_mentions']}")
    print(f"   • Années expérience estimées : {analysis['indicators']['years_exp']}")

    print("\nChecks :")
    print(f"   • Portfolio présent : {'Oui' if analysis['has_portfolio'] else 'Non'}")
    print(f"   • Contact présent : {'Oui' if analysis['has_contact'] else 'Non'}")

    print("\n" + "=" * 60)
    print("SUGGESTIONS DE TITRES LINKEDIN")
    print("=" * 60)
    for i, headline in enumerate(analyzer.generate_optimized_headline(), 1):
        print(f"\n{i}. {headline}")

    print("\n" + "=" * 60)
    print("STRATÉGIE DE RECHERCHE")
    print("=" * 60)
    strategy = analyzer.generate_job_search_strategy()
    print("\nRôles cibles :")
    for role in strategy['target_roles'][:3]:
        print(f"   • {role['title']} - Match {role['match']}% - {role['salary']}")


if __name__ == '__main__':
    main()
