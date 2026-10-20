#!/usr/bin/env bash
# Padronizador de Clientes - instalação inicial (Linux, macOS ou Git Bash no Windows).
# Uso: ./setup.sh
#
# Instala as dependências Python e da interface, e compila a interface (npm run build).
# NÃO inicia o servidor: depois do setup, rode "python app.py" (ou "python3 app.py").
#
# Observação: o OCR de prints (ocr_helper.py / ocr_engine.ps1) só funciona no Windows.
# No Linux/macOS o restante do app funciona normalmente.
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Padronizador de Clientes: setup ==="
echo ""

# --- Python 3.11+ -----------------------------------------------------------
# Tenta "python3" e depois "python" (no Git Bash do Windows, "python3" costuma
# ser um atalho da Microsoft Store que não executa Python de verdade).
PY=""
for candidato in python3 python; do
  if command -v "$candidato" >/dev/null 2>&1 \
     && "$candidato" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    PY="$candidato"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "ERRO: Python 3.11 ou superior não foi encontrado (procurei 'python3' e 'python')." >&2
  echo "Instale em https://www.python.org/downloads/ e rode ./setup.sh de novo." >&2
  exit 1
fi

if ! "$PY" -m pip --version >/dev/null 2>&1; then
  echo "ERRO: o pip não está disponível para '$PY'." >&2
  echo "Instale o pip (python -m ensurepip) e rode ./setup.sh de novo." >&2
  exit 1
fi

# --- Node.js (LTS) + npm ----------------------------------------------------
if ! command -v node >/dev/null 2>&1; then
  echo "ERRO: Node.js não foi encontrado. Ele é necessário para compilar a interface Vue." >&2
  echo "Instale a versão LTS em https://nodejs.org/ e rode ./setup.sh de novo." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERRO: npm não foi encontrado. Reinstale o Node.js LTS (ele já inclui o npm)." >&2
  exit 1
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "ERRO: Node.js 18 ou superior é necessário (encontrado: $(node -v))." >&2
  echo "Instale a versão LTS em https://nodejs.org/ e rode ./setup.sh de novo." >&2
  exit 1
fi

echo "Python: $("$PY" --version 2>&1) ($PY)"
echo "Node:   $(node -v)"
echo ""

# --- Dependências -----------------------------------------------------------
echo "[1/3] Instalando dependências Python (requirements.txt)..."
"$PY" -m pip install -r requirements.txt

echo ""
echo "[2/3] Instalando dependências da interface (npm install)..."
(cd frontend && npm install)

echo ""
echo "[3/3] Compilando a interface (npm run build)..."
(cd frontend && npm run build)

if [ ! -f static/dist/app.js ] || [ ! -f static/dist/app.css ]; then
  echo "ERRO: a compilação não gerou static/dist/app.js e static/dist/app.css." >&2
  echo "Veja a mensagem de erro acima e tente 'cd frontend && npm run build'." >&2
  exit 1
fi

echo ""
echo "=== Setup concluído! ==="
echo ""
echo "Próximos passos:"
echo "  1. (Opcional) Mude a porta ou o endereço exportando as variáveis, por exemplo:"
echo "       export PADRONIZADOR_PORT=5058"
echo "     O app NÃO lê o arquivo .env; veja .env.example para os nomes e padrões."
echo "  2. Inicie o programa:  $PY app.py"
echo "  3. Abra no navegador:  http://127.0.0.1:5057  (o app tenta abrir sozinho)"
echo "  4. Usando o Claude Code? O CLAUDE.md tem todo o contexto do projeto."
