#!/usr/bin/env python3
"""
Profile Analyzer
Analyze portfolio and generate insights for job search
"""

import json
import re
from typing import Dict, List, Any
from dataclasses import dataclass

@dataclass
class Skill:
    name: str
    category: str
    level: str  # beginner, intermediate, expert

@dataclass
class Experience:
    title: str
    company: str
    duration: str
    description: str

class ProfileAnalyzer:
    """Analyze professional profile"""
    
    def __init__(self):
        self.tech_keywords = {
            'languages': ['Python', 'JavaScript', 'TypeScript', 'Go', 'Java', 'SQL', 'Bash'],
            'frameworks': ['React', 'Next.js', 'Node.js', 'Express', 'Django', 'FastAPI'],
            'cloud': ['AWS', 'GCP', 'Azure', 'Docker', 'Kubernetes', 'Terraform'],
            'automation': ['n8n', 'Zapier', 'Make', 'GitHub Actions', 'CI/CD'],
            'ai': ['OpenAI', 'Claude', 'LLM', 'RAG', 'Agents', 'MCP'],
            'data': ['PostgreSQL', 'MongoDB', 'Redis', 'Prisma', 'BigQuery'],
            'tools': ['Git', 'Linux', 'Vim', 'VS Code', 'Figma', 'Notion']
        }
        
        self.target_roles = [
            'Automation Engineer',
            'AI Engineer',
            'RevOps Consultant',
            'Platform Engineer',
            'DevOps Engineer',
            'Solutions Architect',
            'Technical Lead'
        ]
    
    def analyze_text(self, text: str) -> Dict[str, Any]:
        """Analyze text content for skills and keywords"""
        text_lower = text.lower()
        
        found_skills = []
        for category, keywords in self.tech_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    found_skills.append({
                        'name': keyword,
                        'category': category
                    })
        
        # Calculate experience level indicators
        indicators = {
            'senior_mentions': len(re.findall(r'\b(senior|lead|architect|principal)\b', text_lower)),
            'management_mentions': len(re.findall(r'\b(manager|director|head of)\b', text_lower)),
            'years_exp': self._extract_years_experience(text)
        }
        
        return {
            'skills': found_skills,
            'indicators': indicators,
            'word_count': len(text.split()),
            'has_portfolio': 'portfolio' in text_lower or 'github' in text_lower,
            'has_contact': bool(re.search(r'[\w\.-]+@[\w\.-]+', text))
        }
    
    def _extract_years_experience(self, text: str) -> int:
        """Extract years of experience from text"""
        patterns = [
            r'(\d+)\+?\s*years?\s*(of\s*)?experience',
            r'experience\s*:\s*(\d+)\+?\s*years?',
            r'(\d{4})\s*-\s*(present|now|current)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                if 'present' in match.group(0) or 'now' in match.group(0):
                    # Extract start year
                    year = int(match.group(1))
                    return 2026 - year
                else:
                    return int(match.group(1))
        
        return 0
    
    def generate_optimized_headline(self, current_headline: str = '') -> List[str]:
        """Generate optimized LinkedIn headline options"""
        headlines = [
            "Automation & AI Engineer | RevOps Consultant | Building Intelligent Systems",
            "AI Automation Expert | n8n, OpenAI, Claude | Remote-First Consultant",
            "RevOps & AI Engineer | Process Automation | Full-Stack Solutions",
            "Technical Lead - AI & Automation | SaaS & FinTech | 10+ Years Experience"
        ]
        
        return headlines
    
    def generate_about_section(self, profile_data: Dict) -> str:
        """Generate optimized LinkedIn About section"""
        about = f"""🚀 Automation & AI Engineer | RevOps Consultant

Je transforme les processus métier complexes en systèmes automatisés intelligents.

💡 Ce que je fais :
• Architecture d'agents IA autonomes (OpenAI, Claude, n8n)
• Automation RevOps : CRM, pipelines, reporting
• Développement full-stack : React, Node.js, Python
• Cloud & DevOps : AWS, Docker, CI/CD

🎯 Résultats concrets :
• -40% temps de traitement pour [Client X]
• +25% conversion leads via automation marketing
• 10+ projets IA livrés en 2025

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
    
    def suggest_improvements(self, profile_data: Dict) -> List[Dict]:
        """Suggest profile improvements"""
        suggestions = []
        
        # Check headline
        if not profile_data.get('headline') or len(profile_data['headline']) < 50:
            suggestions.append({
                'section': 'headline',
                'priority': 'high',
                'issue': 'Headline trop courte ou générique',
                'suggestion': 'Utiliser : "Automation & AI Engineer | RevOps Consultant | Building Intelligent Systems"',
                'impact': 'Augmente visibilité recherche de 40%'
            })
        
        # Check about section
        if not profile_data.get('about') or len(profile_data['about']) < 500:
            suggestions.append({
                'section': 'about',
                'priority': 'high',
                'issue': 'Section About manquante ou trop courte',
                'suggestion': 'Ajouter section structurée avec stack, résultats, CTA',
                'impact': '+60% de messages de recruteurs'
            })
        
        # Check featured section
        suggestions.append({
            'section': 'featured',
            'priority': 'medium',
            'issue': 'Pas de projets mis en avant',
            'suggestion': 'Ajouter 3 projets : Trading Bot, JobHunter AI, Portfolio',
            'impact': 'Démontre expertise technique concrète'
        })
        
        # Check skills
        suggestions.append({
            'section': 'skills',
            'priority': 'medium',
            'issue': 'Compétences à optimiser',
            'suggestion': 'Top 3 : AI Automation, n8n, RevOps. Ajouter : LangChain, RAG, MCP',
            'impact': 'Meilleur matching algorithmique'
        })
        
        return suggestions
    
    def generate_job_search_strategy(self) -> Dict[str, Any]:
        """Generate job search strategy"""
        return {
            'target_roles': [
                {'title': 'Automation Engineer', 'match': 95, 'salary': '80-120k€'},
                {'title': 'AI Engineer', 'match': 90, 'salary': '90-130k€'},
                {'title': 'RevOps Consultant', 'match': 95, 'salary': '700-1000€/jour'},
                {'title': 'Platform Engineer', 'match': 85, 'salary': '85-120k€'},
                {'title': 'Solutions Architect', 'match': 80, 'salary': '100-140k€'}
            ],
            'target_companies': {
                'fintech': ['Qonto', 'Spendesk', 'Alan', 'Lydia', 'Payfit'],
                'saas': ['Notion', 'Figma', 'Linear', 'Vercel', 'Supabase'],
                'consulting': ['Theodo', 'BAM', 'Malt', 'Comet', 'Aneo']
            },
            'keywords_for_search': [
                'automation engineer',
                'AI engineer',
                'RevOps',
                'n8n',
                'workflow automation',
                'LLM integration',
                'process optimization'
            ],
            'content_strategy': {
                'post_1': 'Case study : Comment j\'ai automatisé [process] pour [client]',
                'post_2': 'Tutorial n8n + OpenAI : Build your first AI agent',
                'post_3': 'Retour d\'expérience : Migration CRM + gains mesurables'
            }
        }

def main():
    """Demo analysis"""
    analyzer = ProfileAnalyzer()
    
    # Example analysis
    sample_text = """
    Matthieu de Villele - Automation & AI Engineer
    10+ years experience in automation, RevOps, and AI systems.
    Expert in n8n, OpenAI, Claude, React, Node.js, Python.
    Built trading bots, job automation systems, and CRM integrations.
    Full remote consultant available for FinTech and SaaS companies.
    """
    
    analysis = analyzer.analyze_text(sample_text)
    
    print("=" * 60)
    print("📊 ANALYSE DE PROFIL")
    print("=" * 60)
    print(f"\n🎯 Skills détectés : {len(analysis['skills'])}")
    for skill in analysis['skills'][:10]:
        print(f"   • {skill['name']} ({skill['category']})")
    
    print(f"\n📈 Indicateurs :")
    print(f"   • Mentions senior : {analysis['indicators']['senior_mentions']}")
    print(f"   • Années expérience estimées : {analysis['indicators']['years_exp']}")
    
    print(f"\n✅ Checks :")
    print(f"   • Portfolio présent : {'Oui' if analysis['has_portfolio'] else 'Non'}")
    print(f"   • Contact présent : {'Oui' if analysis['has_contact'] else 'Non'}")
    
    print("\n" + "=" * 60)
    print("💡 SUGGESTIONS DE TITRES LINKEDIN")
    print("=" * 60)
    for i, headline in enumerate(analyzer.generate_optimized_headline(), 1):
        print(f"\n{i}. {headline}")
    
    print("\n" + "=" * 60)
    print("🎯 STRATÉGIE DE RECHERCHE")
    print("=" * 60)
    strategy = analyzer.generate_job_search_strategy()
    print(f"\nRôles cibles :")
    for role in strategy['target_roles'][:3]:
        print(f"   • {role['title']} - Match {role['match']}% - {role['salary']}")

if __name__ == '__main__':
    main()
