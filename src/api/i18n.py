"""UI translations for the JobHunter AI dashboard.

Language is stored in profile_yaml under ``ui.language`` (default: "fr").
Supported: fr, en, es.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.storage.models import User

TRANSLATIONS: dict[str, dict[str, str]] = {
    "fr": {
        # Nav
        "nav_dashboard": "Dashboard",
        "nav_jobs": "Offres",
        "nav_settings": "Paramètres",

        # Stats
        "stat_scanned": "Scannées",
        "stat_matched": "Matchées",
        "stat_applied": "Appliquées",
        "stat_replied": "Réponses",
        "stat_today": "aujourd'hui",

        # Pipeline
        "section_pipeline": "Contrôles pipeline",
        "phase_scan": "🔍 Scanner",
        "phase_match": "⭐ Matcher",
        "phase_apply": "📤 Appliquer (dry)",
        "phase_respond": "💬 Répondre",
        "phase_running": "en cours…",
        "phase_error": "erreur",

        # Jobs section
        "section_jobs": "Offres",
        "filter_all": "Tous",
        "jobs_empty": "Aucune offre trouvée.",
        "col_title": "Titre",
        "col_company": "Entreprise",
        "col_source": "Source",
        "col_score": "Score",
        "col_salary": "Salaire",
        "col_remote": "Remote",
        "col_status": "Status",
        "col_date": "Date",
        "col_actions": "Actions",
        "job_see": "Voir →",
        "job_skip": "Passer",
        "job_approve": "Approuver",
        "job_confirm_skip": "Passer cette offre ?",
        "job_remote": "Remote",
        "job_onsite": "Présentiel",
        "pagination_prev": "← Précédent",
        "pagination_next": "Suivant →",

        # Job detail
        "back_dashboard": "Dashboard",
        "job_view_offer": "Voir l'offre",
        "job_unknown_company": "Entreprise inconnue",
        "section_score": "Score de matching",
        "section_description": "Description du poste",
        "section_evaluation": "Évaluation AI",
        "section_application": "Candidature",
        "no_description": "Pas de description disponible.",

        # Dashboard
        "dashboard_subtitle": "Vue d'ensemble de votre pipeline de recherche d'emploi.",

        # Settings
        "settings_title": "Paramètres de recherche",
        "settings_subtitle": "Configure les sources, mots-clés et filtres du scanner.",
        "section_sources": "Sources de scan",
        "keywords_label": "Mots-clés",
        "keywords_hint": "un par ligne",
        "location_label": "Location",
        "section_filters": "Filtres",
        "contract_types_label": "Types de contrat acceptés",
        "excluded_label": "Mots-clés exclus",
        "excluded_hint": "un par ligne — offres contenant ces mots sont ignorées",
        "language_label": "Langue de l'interface",
        "btn_save": "Sauvegarder",
        "toast_saved": "Paramètres sauvegardés",

        # Auth
        "login_title": "Connexion",
        "register_title": "Créer un compte",
        "email_label": "Email",
        "password_label": "Mot de passe",
        "confirm_password_label": "Confirmer le mot de passe",
        "btn_login": "Se connecter",
        "btn_register": "Créer le compte",
        "no_account": "Pas encore de compte ?",
        "create_account": "Créer un compte",
        "already_account": "Déjà un compte ?",

        # Job detail extras
        "score_excellent": "Excellent match — priorité haute",
        "score_good": "Bon match — à considérer",
        "score_weak": "Match faible — à review manuel",
        "section_evaluation_detailed": "Évaluation détaillée",
        "cover_letter_label": "Lettre de motivation",
        "cv_download": "Télécharger le CV (PDF)",
        "section_progress": "Progression",
        "step_new_label": "Découverte",
        "step_new_desc": "Offre scrapée et enregistrée",
        "step_matched_label": "Matching",
        "step_matched_desc": "Score IA calculé",
        "step_applied_label": "Candidature",
        "step_applied_desc": "CV + lettre envoyés",
        "step_replied_label": "Réponse",
        "step_replied_desc": "Réponse reçue",

        # Settings page
        "section_profile": "Mon profil",
        "profile_subtitle": "Utilisé par l'IA pour scorer les offres selon votre expérience.",
        "search_section_title": "Recherche",
        "sources_title": "Sources actives",
        "sources_subtitle": "Activez une source puis configurez vos mots-clés et localisation.",
        "api_keys_title": "Clés API",
        "api_keys_subtitle": "Chiffrées côté serveur — jamais stockées en clair.",
        "advanced_mode_label": "Mode avancé — Profil YAML complet",
        "advanced_mode_click": "Cliquer pour déplier",
        "configured_label": "Configurée",
        "not_configured_label": "Non configurée",
        "btn_save_profile": "Sauvegarder le profil",
        "btn_save_keys": "Sauvegarder les clés",
        "btn_save_yaml": "Sauvegarder YAML",
        "btn_reload": "Recharger",
        "toast_profile_saved": "Profil sauvegardé",
        "toast_keys_saved": "Clés sauvegardées",
        "toast_yaml_saved": "Profil YAML sauvegardé",

        # Evaluation block labels (A-F)
        "block_A": "A — Rôle & catégorie",
        "block_B": "B — Fit CV / offre",
        "block_C": "C — Niveau / stratégie",
        "block_D": "D — Compensation",
        "block_E": "E — Personnalisation",
        "block_F": "F — Préparation entretien",

        # Profile form labels
        "lbl_name": "Prénom / Nom",
        "ph_name": "Prénom Nom",
        "lbl_job_title": "Titre du poste recherché",
        "lbl_experience": "Années d'expérience",
        "lbl_salary_min": "Salaire annuel min (€)",
        "lbl_salary_max": "Salaire annuel max (€)",
        "lbl_tjm_min": "TJM min (€/jour)",
        "lbl_tjm_max": "TJM max (€/jour)",
        "lbl_optional": "optionnel",
        "lbl_skills": "Compétences principales",
        "ph_add_skill": "Ajouter une compétence…",
        "lbl_excl_keywords": "Mots à exclure",
        "ph_add_excl": "Ajouter un mot à exclure…",

        # Search section
        "lbl_max_age": "Ancienneté max des offres",
        "opt_today": "Aujourd'hui (1 jour)",
        "opt_3days": "3 jours",
        "opt_7days": "7 jours",
        "opt_2weeks": "2 semaines",
        "opt_30days": "30 jours (défaut)",
        "opt_all": "Tout (pas de filtre)",
        "hint_max_age": "Indeed et LinkedIn filtrent via l'API. WTTJ filtre en post-traitement si le champ date est disponible.",

        # Source config labels
        "lbl_search_kw": "Mots-clés de recherche",
        "ph_add_kw": "Ajouter un mot-clé…",
        "lbl_work_modes": "Modes de travail",
        "work_mode_remote": "Remote",
        "work_mode_hybrid": "Hybride",
        "work_mode_onsite": "Présentiel",
        "lbl_railway_key": "Clé Railway",
        "lbl_key_missing": "Clé manquante",
        "lbl_api_key_missing_server": "Clé API manquante côté serveur",

        # Credential field labels/hints
        "cred_wttj_password_label": "WTTJ Mot de passe",
        "cred_openrouter_hint": "Requis pour la phase de scoring (Match). Créez un compte sur openrouter.ai (~1$ suffit).",
        "cred_anthropic_hint": "Optionnel — si vous préférez Claude directement.",
        "cred_wttj_email_hint": "Email de votre compte Welcome to the Jungle (requis pour le scraping).",
        "cred_wttj_password_hint": "Mot de passe Welcome to the Jungle.",

        # Language toggle
        "lang_toggle_label": "Langue",
    },

    "en": {
        # Nav
        "nav_dashboard": "Dashboard",
        "nav_jobs": "Jobs",
        "nav_settings": "Settings",

        # Stats
        "stat_scanned": "Scanned",
        "stat_matched": "Matched",
        "stat_applied": "Applied",
        "stat_replied": "Replies",
        "stat_today": "today",

        # Pipeline
        "section_pipeline": "Pipeline controls",
        "phase_scan": "🔍 Scan",
        "phase_match": "⭐ Match",
        "phase_apply": "📤 Apply (dry)",
        "phase_respond": "💬 Respond",
        "phase_running": "running…",
        "phase_error": "error",

        # Jobs section
        "section_jobs": "Jobs",
        "filter_all": "All",
        "jobs_empty": "No jobs found.",
        "col_title": "Title",
        "col_company": "Company",
        "col_source": "Source",
        "col_score": "Score",
        "col_salary": "Salary",
        "col_remote": "Remote",
        "col_status": "Status",
        "col_date": "Date",
        "col_actions": "Actions",
        "job_see": "View →",
        "job_skip": "Skip",
        "job_approve": "Approve",
        "job_confirm_skip": "Skip this job?",
        "job_remote": "Remote",
        "job_onsite": "On-site",
        "pagination_prev": "← Previous",
        "pagination_next": "Next →",

        # Job detail
        "back_dashboard": "Dashboard",
        "job_view_offer": "View job",
        "job_unknown_company": "Unknown company",
        "section_score": "Match score",
        "section_description": "Job description",
        "section_evaluation": "AI evaluation",
        "section_application": "Application",
        "no_description": "No description available.",

        # Dashboard
        "dashboard_subtitle": "Overview of your job search pipeline.",

        # Settings
        "settings_title": "Search settings",
        "settings_subtitle": "Configure sources, keywords and filters for the scanner.",
        "section_sources": "Scan sources",
        "keywords_label": "Keywords",
        "keywords_hint": "one per line",
        "location_label": "Location",
        "section_filters": "Filters",
        "contract_types_label": "Accepted contract types",
        "excluded_label": "Excluded keywords",
        "excluded_hint": "one per line — jobs containing these words are ignored",
        "language_label": "Interface language",
        "btn_save": "Save",
        "toast_saved": "Settings saved",

        # Auth
        "login_title": "Sign in",
        "register_title": "Create account",
        "email_label": "Email",
        "password_label": "Password",
        "confirm_password_label": "Confirm password",
        "btn_login": "Sign in",
        "btn_register": "Create account",
        "no_account": "No account yet?",
        "create_account": "Create account",
        "already_account": "Already have an account?",

        # Job detail extras
        "score_excellent": "Excellent match — high priority",
        "score_good": "Good match — worth considering",
        "score_weak": "Weak match — needs manual review",
        "section_evaluation_detailed": "Detailed evaluation",
        "cover_letter_label": "Cover letter",
        "cv_download": "Download CV (PDF)",
        "section_progress": "Progress",
        "step_new_label": "Discovery",
        "step_new_desc": "Job scraped and saved",
        "step_matched_label": "Matching",
        "step_matched_desc": "AI score computed",
        "step_applied_label": "Application",
        "step_applied_desc": "CV + letter sent",
        "step_replied_label": "Reply",
        "step_replied_desc": "Reply received",

        # Settings page
        "section_profile": "My profile",
        "profile_subtitle": "Used by the AI to score jobs against your experience.",
        "search_section_title": "Search",
        "sources_title": "Active sources",
        "sources_subtitle": "Enable a source then configure keywords and location.",
        "api_keys_title": "API Keys",
        "api_keys_subtitle": "Encrypted server-side — never stored in plaintext.",
        "advanced_mode_label": "Advanced mode — Raw YAML profile",
        "advanced_mode_click": "Click to expand",
        "configured_label": "Configured",
        "not_configured_label": "Not configured",
        "btn_save_profile": "Save profile",
        "btn_save_keys": "Save keys",
        "btn_save_yaml": "Save YAML",
        "btn_reload": "Reload",
        "toast_profile_saved": "Profile saved",
        "toast_keys_saved": "Keys saved",
        "toast_yaml_saved": "YAML profile saved",

        # Evaluation block labels (A-F)
        "block_A": "A — Role & category",
        "block_B": "B — CV fit / job",
        "block_C": "C — Level / strategy",
        "block_D": "D — Compensation",
        "block_E": "E — Personalization",
        "block_F": "F — Interview prep",

        # Profile form labels
        "lbl_name": "First / Last name",
        "ph_name": "First Last",
        "lbl_job_title": "Target job title",
        "lbl_experience": "Years of experience",
        "lbl_salary_min": "Annual salary min (€)",
        "lbl_salary_max": "Annual salary max (€)",
        "lbl_tjm_min": "Daily rate min (€/day)",
        "lbl_tjm_max": "Daily rate max (€/day)",
        "lbl_optional": "optional",
        "lbl_skills": "Main skills",
        "ph_add_skill": "Add a skill…",
        "lbl_excl_keywords": "Words to exclude",
        "ph_add_excl": "Add word to exclude…",

        # Search section
        "lbl_max_age": "Max job age",
        "opt_today": "Today (1 day)",
        "opt_3days": "3 days",
        "opt_7days": "7 days",
        "opt_2weeks": "2 weeks",
        "opt_30days": "30 days (default)",
        "opt_all": "All (no filter)",
        "hint_max_age": "Indeed and LinkedIn filter via API. WTTJ filters in post-processing if the date field is available.",

        # Source config labels
        "lbl_search_kw": "Search keywords",
        "ph_add_kw": "Add a keyword…",
        "lbl_work_modes": "Work modes",
        "work_mode_remote": "Remote",
        "work_mode_hybrid": "Hybrid",
        "work_mode_onsite": "On-site",
        "lbl_railway_key": "Railway key",
        "lbl_key_missing": "Key missing",
        "lbl_api_key_missing_server": "API key missing on server",

        # Credential field labels/hints
        "cred_wttj_password_label": "WTTJ Password",
        "cred_openrouter_hint": "Required for the scoring phase (Match). Create an account on openrouter.ai (~$1 is enough).",
        "cred_anthropic_hint": "Optional — if you prefer Claude directly.",
        "cred_wttj_email_hint": "Your Welcome to the Jungle account email (required for scraping).",
        "cred_wttj_password_hint": "Your Welcome to the Jungle password.",

        # Language toggle
        "lang_toggle_label": "Language",
    },

    "es": {
        # Nav
        "nav_dashboard": "Panel",
        "nav_jobs": "Ofertas",
        "nav_settings": "Configuración",

        # Stats
        "stat_scanned": "Escaneadas",
        "stat_matched": "Coincidencias",
        "stat_applied": "Aplicadas",
        "stat_replied": "Respuestas",
        "stat_today": "hoy",

        # Pipeline
        "section_pipeline": "Controles del pipeline",
        "phase_scan": "🔍 Escanear",
        "phase_match": "⭐ Coincidir",
        "phase_apply": "📤 Aplicar (prueba)",
        "phase_respond": "💬 Responder",
        "phase_running": "en curso…",
        "phase_error": "error",

        # Jobs section
        "section_jobs": "Ofertas",
        "filter_all": "Todas",
        "jobs_empty": "No se encontraron ofertas.",
        "col_title": "Título",
        "col_company": "Empresa",
        "col_source": "Fuente",
        "col_score": "Puntuación",
        "col_salary": "Salario",
        "col_remote": "Remoto",
        "col_status": "Estado",
        "col_date": "Fecha",
        "col_actions": "Acciones",
        "job_see": "Ver →",
        "job_skip": "Omitir",
        "job_approve": "Aprobar",
        "job_confirm_skip": "¿Omitir esta oferta?",
        "job_remote": "Remoto",
        "job_onsite": "Presencial",
        "pagination_prev": "← Anterior",
        "pagination_next": "Siguiente →",

        # Job detail
        "back_dashboard": "Panel",
        "job_view_offer": "Ver oferta",
        "job_unknown_company": "Empresa desconocida",
        "section_score": "Puntuación de coincidencia",
        "section_description": "Descripción del puesto",
        "section_evaluation": "Evaluación IA",
        "section_application": "Candidatura",
        "no_description": "Sin descripción disponible.",

        # Dashboard
        "dashboard_subtitle": "Vista general de tu pipeline de búsqueda de empleo.",

        # Settings
        "settings_title": "Configuración de búsqueda",
        "settings_subtitle": "Configura las fuentes, palabras clave y filtros del escáner.",
        "section_sources": "Fuentes de escaneo",
        "keywords_label": "Palabras clave",
        "keywords_hint": "una por línea",
        "location_label": "Ubicación",
        "section_filters": "Filtros",
        "contract_types_label": "Tipos de contrato aceptados",
        "excluded_label": "Palabras clave excluidas",
        "excluded_hint": "una por línea — las ofertas con estas palabras se ignoran",
        "language_label": "Idioma de la interfaz",
        "btn_save": "Guardar",
        "toast_saved": "Configuración guardada",

        # Auth
        "login_title": "Iniciar sesión",
        "register_title": "Crear cuenta",
        "email_label": "Correo electrónico",
        "password_label": "Contraseña",
        "confirm_password_label": "Confirmar contraseña",
        "btn_login": "Iniciar sesión",
        "btn_register": "Crear cuenta",
        "no_account": "¿Aún no tienes cuenta?",
        "create_account": "Crear cuenta",
        "already_account": "¿Ya tienes cuenta?",

        # Job detail extras
        "score_excellent": "Excelente match — prioridad alta",
        "score_good": "Buen match — vale la pena considerar",
        "score_weak": "Match débil — revisar manualmente",
        "section_evaluation_detailed": "Evaluación detallada",
        "cover_letter_label": "Carta de motivación",
        "cv_download": "Descargar CV (PDF)",
        "section_progress": "Progreso",
        "step_new_label": "Descubrimiento",
        "step_new_desc": "Oferta guardada",
        "step_matched_label": "Coincidencia",
        "step_matched_desc": "Puntuación IA calculada",
        "step_applied_label": "Candidatura",
        "step_applied_desc": "CV + carta enviados",
        "step_replied_label": "Respuesta",
        "step_replied_desc": "Respuesta recibida",

        # Settings page
        "section_profile": "Mi perfil",
        "profile_subtitle": "Usado por la IA para puntuar las ofertas según tu experiencia.",
        "search_section_title": "Búsqueda",
        "sources_title": "Fuentes activas",
        "sources_subtitle": "Activa una fuente y configura palabras clave y ubicación.",
        "api_keys_title": "Claves API",
        "api_keys_subtitle": "Cifradas en el servidor — nunca almacenadas en texto plano.",
        "advanced_mode_label": "Modo avanzado — Perfil YAML completo",
        "advanced_mode_click": "Clic para expandir",
        "configured_label": "Configurada",
        "not_configured_label": "No configurada",
        "btn_save_profile": "Guardar perfil",
        "btn_save_keys": "Guardar claves",
        "btn_save_yaml": "Guardar YAML",
        "btn_reload": "Recargar",
        "toast_profile_saved": "Perfil guardado",
        "toast_keys_saved": "Claves guardadas",
        "toast_yaml_saved": "Perfil YAML guardado",

        # Evaluation block labels (A-F)
        "block_A": "A — Rol & categoría",
        "block_B": "B — Fit CV / oferta",
        "block_C": "C — Nivel / estrategia",
        "block_D": "D — Compensación",
        "block_E": "E — Personalización",
        "block_F": "F — Preparación entrevista",

        # Profile form labels
        "lbl_name": "Nombre / Apellido",
        "ph_name": "Nombre Apellido",
        "lbl_job_title": "Título del puesto buscado",
        "lbl_experience": "Años de experiencia",
        "lbl_salary_min": "Salario anual mín (€)",
        "lbl_salary_max": "Salario anual máx (€)",
        "lbl_tjm_min": "TMD mín (€/día)",
        "lbl_tjm_max": "TMD máx (€/día)",
        "lbl_optional": "opcional",
        "lbl_skills": "Habilidades principales",
        "ph_add_skill": "Añadir una habilidad…",
        "lbl_excl_keywords": "Palabras a excluir",
        "ph_add_excl": "Añadir palabra a excluir…",

        # Search section
        "lbl_max_age": "Antigüedad máx de las ofertas",
        "opt_today": "Hoy (1 día)",
        "opt_3days": "3 días",
        "opt_7days": "7 días",
        "opt_2weeks": "2 semanas",
        "opt_30days": "30 días (defecto)",
        "opt_all": "Todo (sin filtro)",
        "hint_max_age": "Indeed y LinkedIn filtran por API. WTTJ filtra en post-procesamiento si el campo fecha está disponible.",

        # Source config labels
        "lbl_search_kw": "Palabras clave de búsqueda",
        "ph_add_kw": "Añadir una palabra clave…",
        "lbl_work_modes": "Modos de trabajo",
        "work_mode_remote": "Remoto",
        "work_mode_hybrid": "Híbrido",
        "work_mode_onsite": "Presencial",
        "lbl_railway_key": "Clave Railway",
        "lbl_key_missing": "Clave faltante",
        "lbl_api_key_missing_server": "Clave API faltante en servidor",

        # Credential field labels/hints
        "cred_wttj_password_label": "WTTJ Contraseña",
        "cred_openrouter_hint": "Requerido para la fase de puntuación (Match). Crea una cuenta en openrouter.ai (~1$ es suficiente).",
        "cred_anthropic_hint": "Opcional — si prefieres Claude directamente.",
        "cred_wttj_email_hint": "Email de tu cuenta Welcome to the Jungle (requerido para el scraping).",
        "cred_wttj_password_hint": "Contraseña de Welcome to the Jungle.",

        # Language toggle
        "lang_toggle_label": "Idioma",
    },
}

SUPPORTED_LANGS = list(TRANSLATIONS.keys())
DEFAULT_LANG = "fr"


def get_ui_lang(user: "User") -> str:
    """Return the UI language for *user* (default: 'fr')."""
    from src.config.profile import get_profile_for_user
    try:
        profile = get_profile_for_user(user)
        lang = profile.get("ui", {}).get("language", DEFAULT_LANG)
        return lang if lang in TRANSLATIONS else DEFAULT_LANG
    except Exception:
        return DEFAULT_LANG


def get_t(user: "User") -> dict[str, str]:
    """Return the translation dict for *user*'s preferred language."""
    return TRANSLATIONS[get_ui_lang(user)]
