#!/bin/bash
# AIM Deploy Builder
# Creates a clean distributable archive in ~/Documents
# Usage: ./build_deploy.sh

set -e

VERSION=$(date +%Y-%m-%d)
DEPLOY_NAME="AIM_Deploy_${VERSION}"
DEPLOY_DIR="/tmp/${DEPLOY_NAME}"
OUTPUT="$HOME/Documents/${DEPLOY_NAME}.tar.gz"

echo "🚀 Building AIM deploy package: ${DEPLOY_NAME}"

# Clean temp dir
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# Core Python files
cp *.py "$DEPLOY_DIR/" 2>/dev/null || true

# Subfolders with code
for dir in agents integrations config knowledge; do
    [ -d "$dir" ] && cp -r "$dir" "$DEPLOY_DIR/" && echo "  ✓ $dir/"
done

# Static resources
cp requirements.txt "$DEPLOY_DIR/" 2>/dev/null || true
cp README.md "$DEPLOY_DIR/" 2>/dev/null || true
cp INSTALL.md "$DEPLOY_DIR/" 2>/dev/null || true
cp ИНСТРУКЦИЯ.md "$DEPLOY_DIR/" 2>/dev/null || true
cp config.json.example "$DEPLOY_DIR/" 2>/dev/null || true
cp nutrition_rules.json "$DEPLOY_DIR/" 2>/dev/null || true
cp medical_bayes.json "$DEPLOY_DIR/" 2>/dev/null || true
cp aim_icon.png "$DEPLOY_DIR/" 2>/dev/null || true
cp aim_icon_small.png "$DEPLOY_DIR/" 2>/dev/null || true
cp AIM.desktop "$HOME/Desktop/" 2>/dev/null || true

# Write fresh install.sh
cat > "$DEPLOY_DIR/install.sh" << 'EOF'
#!/bin/bash
# AIM — Install Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 Installing AIM from: $SCRIPT_DIR"

cd "$SCRIPT_DIR"

# Virtual environment
python3 -m venv venv
source venv/bin/activate

# Dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Ollama
if ! command -v ollama &> /dev/null; then
    echo "📦 Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi
ollama pull llama3.2

# DeepSeek key reminder
if [ ! -f "$HOME/.aim_env" ]; then
    echo ""
    echo "⚠️  Create ~/.aim_env with:"
    echo "    export DEEPSEEK_API_KEY=sk-..."
fi

echo ""
echo "✅ AIM installed. Run: ./start.sh"
EOF
chmod +x "$DEPLOY_DIR/install.sh"

# Write fresh start.sh
cat > "$DEPLOY_DIR/start.sh" << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
[ -f "$HOME/.aim_env" ] && source "$HOME/.aim_env"
[ -d "venv" ] && source venv/bin/activate
python3 medical_system.py
EOF
chmod +x "$DEPLOY_DIR/start.sh"

# Write INSTALL.md
cat > "$DEPLOY_DIR/INSTALL.md" << EOF
# AIM — Installation

## Requirements
- Python 3.10+
- Ollama (auto-installed)
- DeepSeek API key (optional, for LLM features)

## Quick Start

\`\`\`bash
tar -xzf AIM_Deploy_${VERSION}.tar.gz
cd ${DEPLOY_NAME}
./install.sh
./start.sh
\`\`\`

## DeepSeek API Key

Create \`~/.aim_env\`:
\`\`\`bash
export DEEPSEEK_API_KEY=sk-...
\`\`\`

## First Run

On first launch, AIM will:
1. Create a local SQLite database (\`aim.db\`)
2. Ask you to register an admin user
3. Load the menu

## Notes
- Patient data stays local (SQLite + \`Patients/\` folder)
- No cloud sync by default
- Telegram bot: configure token in \`config.json\`
EOF

# Package
cd /tmp
tar -czf "$OUTPUT" "$DEPLOY_NAME"
rm -rf "$DEPLOY_DIR"

SIZE=$(du -sh "$OUTPUT" | cut -f1)
echo ""
echo "✅ Deploy ready: $OUTPUT"
echo "   Size: $SIZE"
