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
