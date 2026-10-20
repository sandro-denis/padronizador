"""
Extrai texto de uma imagem (print de tela) usando o OCR nativo do Windows,
via um script PowerShell (ocr_engine.ps1) que chama a API Windows.Media.Ocr.
Nao precisa instalar nada (Tesseract, etc.) - so funciona no Windows 10/11.
"""
import os
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(BASE_DIR, "ocr_engine.ps1")
POWERSHELL_EXE = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
)

# palavras de interface que costumam aparecer perto de listas de usuarios e
# nao sao nomes de pessoa - filtradas automaticamente das linhas extraidas.
NOISE_WORDS = {"NOME", "STATUS", "ONLINE", "OFFLINE", "USUARIO", "USUARIOS", "AÇÕES", "ACOES"}


def run_ocr(image_path):
    """Roda o OCR e retorna a lista de linhas de texto detectadas (cru, sem filtro)."""
    try:
        proc = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SCRIPT_PATH, "-ImagePath", image_path],
            capture_output=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("PowerShell nao encontrado - OCR so funciona no Windows.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("OCR demorou demais para responder.")

    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        raise RuntimeError(f"OCR falhou: {stderr.strip() or 'motivo desconhecido'}")

    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    return lines


def extract_candidate_names(image_path):
    """Roda o OCR e filtra linhas obviamente nao-nome (cabecalhos, status).
    O resultado ainda deve ser revisado pelo usuario antes de usar - OCR erra,
    principalmente em acentos."""
    lines = run_ocr(image_path)
    candidates = []
    for line in lines:
        upper = line.strip().upper()
        if upper in NOISE_WORDS:
            continue
        if len(line.strip()) < 3:
            continue
        candidates.append(line.strip())
    return candidates
