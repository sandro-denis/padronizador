# Build em dois estagios: o Node compila a interface, o Python so roda.
#
# Assim `static/dist` continua FORA do git (ele e gerado, nao fonte) e o deploy
# funciona igual em qualquer host de conteiner - Render, Fly, Railway ou a
# maquina de quem quiser levantar a propria instancia.

# ---------- 1. interface ----------
FROM node:22-alpine AS frontend
WORKDIR /build
# o package-lock entra primeiro pra o cache do Docker aproveitar: mexer no
# codigo Vue nao obriga a reinstalar as dependencias
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# o vite.config.js aponta a saida pra ../static/dist
RUN npm run build


# ---------- 2. servidor ----------
FROM python:3.12-slim AS app
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY *.py ./
COPY templates/ ./templates/
# o bundle vem pronto do estagio anterior
COPY --from=frontend /static/dist ./static/dist

# O ocr_engine.ps1 NAO vem: ele chama a API Windows.Media.Ocr, que nao existe
# aqui. `ocr_helper.disponivel()` devolve False em Linux, /api/config informa e
# a tela esconde a secao do print - melhor ausente do que quebrada.

# Padroes da instancia hospedada, diferentes dos de uso local:
#   - memoria de decisoes DESLIGADA: o decisions.json e unico e global, entao
#     numa instancia compartilhada lembrar decisao de um escritorio e mostra-la
#     a outro (ver rules_store.MEMORIA);
#   - sessao vive 1h no disco, nao 24h: planilha de cliente nao fica no
#     servidor depois que a pessoa terminou (ver _limpar_sessoes_antigas).
ENV PADRONIZADOR_MEMORIA=0 \
    PADRONIZADOR_SESSAO_TTL_MIN=60 \
    PADRONIZADOR_HOST=0.0.0.0 \
    PORT=5057

EXPOSE 5057

# UM worker por padrao - mas agora da pra mudar.
#
# O estado da revisao vive no dicionario SESSIONS, em memoria do processo.
# Antes isso travava o numero de workers em um: a requisicao seguinte caia no
# outro processo, que nao conhecia a sessao, e a tela levava 404 intermitente.
#
# Com _rehidratar_sessao (ver app.py) isso deixou de ser verdade: qualquer
# worker remonta do disco a sessao aberta em outro. Entao WEB_CONCURRENCY=2
# funciona - mas so compensa com VARIAS PESSOAS ao mesmo tempo, porque:
#   - o worker que nao tem a sessao paga a releitura da planilha;
#   - o cache do agrupamento e por processo, entao um "Comparar" que caia no
#     worker frio refaz a analise inteira.
# Para UMA pessoa de cada vez, um worker so continua sendo mais rapido.
#
# O timeout folgado e porque uma planilha de milhares de processos leva dezenas
# de segundos pra analisar, e o padrao de 30s do gunicorn mataria o worker.
CMD gunicorn --workers ${WEB_CONCURRENCY:-1} --threads 4 --timeout 300 --bind 0.0.0.0:$PORT app:app
