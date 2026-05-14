#!/usr/bin/env bash
# init-profile.sh — Configure JobHunter AI en 2 questions
# Fonctionne sur : Mac (Terminal), Linux, Windows (Git Bash)
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║      JobHunter AI — Setup            ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# ── Question 1 : nom ───────────────────────────────────────
echo -e "${YELLOW}1. Ton prénom et nom (sans accents, avec un tiret) :${NC}"
echo "   Ex : jean-dupont   marie-martin   john-doe"
echo ""
read -r -p "   > " PROFILE_NAME

if [[ -z "$PROFILE_NAME" ]]; then
  echo -e "${RED}Erreur : nom vide.${NC}"
  exit 1
fi

PROFILE_NAME=$(echo "$PROFILE_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
PROFILE_DIR="$PROJECT_ROOT/profiles/$PROFILE_NAME"

if [[ -d "$PROFILE_DIR" ]]; then
  echo ""
  echo -e "${YELLOW}Le profil '$PROFILE_NAME' existe déjà. Continuer écrasera le .env.${NC}"
  read -r -p "   Continuer ? (o/N) : " OVERWRITE
  if [[ "$OVERWRITE" != "o" && "$OVERWRITE" != "O" ]]; then
    echo "Annulé."
    exit 0
  fi
fi

# ── Question 2 : clé API ───────────────────────────────────
echo ""
echo -e "${YELLOW}2. Ta clé API OpenRouter :${NC}"
echo "   → Crée-en une gratuitement sur https://openrouter.ai/keys"
echo "   → Elle commence par : sk-or-..."
echo ""
read -r -p "   > " API_KEY

if [[ -z "$API_KEY" ]]; then
  echo -e "${RED}Erreur : clé API vide.${NC}"
  exit 1
fi

# ── Création du profil ─────────────────────────────────────
mkdir -p "$PROFILE_DIR"

# Écrire .env directement avec la clé
cat > "$PROFILE_DIR/.env" <<EOF
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=$API_KEY
LOG_LEVEL=INFO
DRY_RUN=true
MAX_APPLICATIONS_PER_DAY=10
MIN_MATCH_SCORE=70
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=
GMAIL_USER_EMAIL=
EOF

# Copier le template profile.yaml uniquement s'il n'existe pas déjà
if [[ ! -f "$PROFILE_DIR/profile.yaml" ]]; then
  cp "$PROJECT_ROOT/profiles/template/profile.yaml" "$PROFILE_DIR/profile.yaml"
fi

echo ""
echo -e "${GREEN}✓ Profil créé : profiles/$PROFILE_NAME/${NC}"

# ── Instructions finales ────────────────────────────────────
echo ""
echo -e "${BLUE}══ Prochaine étape : glisse ton profile.yaml ══════════${NC}"
echo ""
echo "   Copie ton fichier profile.yaml dans :"
echo ""
echo -e "   ${GREEN}$PROFILE_DIR/${NC}"
echo ""
echo "   Ensuite, lance le dashboard avec cette commande :"
echo ""
echo -e "   ${GREEN}PROFILE_DIR=./profiles/$PROFILE_NAME docker compose up -d jobhunter-web${NC}"
echo ""
echo "   Puis ouvre : http://localhost:8000"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

# Ouvrir le dossier profil (Mac uniquement)
if command -v open &>/dev/null; then
  open "$PROFILE_DIR"
fi
