# Padronizador de Clientes

**Versão:** 1.0.0 | **Porta:** 5057 | **Stack:** Python 3.11+ (Flask, openpyxl, rapidfuzz, pdfplumber) + Vue 3 / Vite

## O que é

Ferramenta web local que padroniza nomes de partes em planilhas de processos jurídicos antes da importação num sistema de gestão de processos. Encontra homônimos e duplicatas, deixa o usuário revisar grupo por grupo, memoriza cada decisão e gera as planilhas corrigidas. Tudo roda na máquina do usuário. Interface e textos em português.

## Início rápido

```bash
./setup.sh                 # Instalação (Linux/macOS/Git Bash). No Windows, use run.bat
python app.py              # Sobe em http://127.0.0.1:5057 e abre o navegador
pip install pytest && python -m pytest tests   # Testes
```

## Comandos

```bash
# Dependências
pip install -r requirements.txt        # backend (pytest NÃO está no requirements.txt)
cd frontend && npm install && cd ..    # frontend

# Build da interface (obrigatório após qualquer mudança em frontend/src)
cd frontend && npm run build && cd ..  # gera static/dist/app.js e static/dist/app.css

# Dev da interface com hot reload (opcional; o Flask precisa estar rodando)
cd frontend && npm run dev             # Vite, porta padrão 5173; /api é repassado para 127.0.0.1:5057

# Servidor e testes
python app.py                          # debug=False: reinicie após mudar .py ou templates
python -m pytest tests                 # 111 casos
```

## Armadilhas conhecidas (leia antes de editar)

1. **Dois HTML de entrada.** `templates/app.html` é o que o Flask entrega em `/` (é o que roda com `python app.py`). `frontend/index.html` é usado só pelo Vite (`npm run dev`). Mudanças no `<head>` (fontes, meta, título, favicon) precisam ser feitas nos **dois** arquivos, senão só uma das versões muda.
2. **Reinicie o servidor.** `app.py` roda com `debug=False`: o Flask guarda os templates em cache e o Python não recarrega módulos. Depois de editar qualquer `.py` ou `templates/app.html`, reinicie. Se a mudança "não fez efeito", quase sempre é um processo antigo ainda ouvindo a porta. No Windows, confira com `netstat -ano | findstr :5057` e encerre os PIDs extras com `taskkill /PID <pid> /F`.
3. **Recompile a interface.** O Flask serve `static/dist/`, não `frontend/src`. Depois de editar `frontend/src`, rode `npm run build` e recarregue a página no navegador (Ctrl+F5). O `npm run build` também gera `static/dist/index.html`, que o Flask não usa.

## Arquitetura

```
app.py              Rotas Flask: upload -> analyze -> revisão no navegador -> apply -> download
                    SESSIONS: dict em memória; arquivos em data/sessions/<id>/
matching.py         Motor: normalize_name, compare_names, find_clusters (union-find),
                    suggest_canonical, checagens de cadastro, tribunal/juiz e nomes sujos
excel_io.py         Lê e grava as planilhas Escavador (Processos), Clientes e Financeiro
advbox_io.py        Lê os PDFs exportados do ADVBOX (pessoas e processos) com pdfplumber
ajustes_io.py       Patch de planilha de AJUSTES. NÃO está ligado às rotas (só os testes usam)
rules_store.py      Decisões persistidas em data/decisions.json (arquivo global)
report.py           Resumo .txt das alterações
ocr_helper.py       Chama ocr_engine.ps1 (OCR nativo do Windows) para ler nomes de prints
frontend/src/       Vue 3: App.vue + components/*.vue (uma seção por tipo de problema)
templates/app.html  Página entregue pelo Flask
static/dist/        Saída do build (gerada; no .gitignore)
tests/              pytest
```

O navegador chama `/api/*`. `app.py` lê as planilhas e o motor agrupa os nomes.

## A memória de decisões vem DESLIGADA

`rules_store.MEMORIA` é lida de `PADRONIZADOR_MEMORIA` e o padrão é **desligado**. Isso não é um detalhe de configuração — é o comportamento que o projeto promete, e tem teste próprio (`tests/test_memoria_desligada.py`).

- Desligada, **todas** as funções de `rules_store` continuam existindo e sendo chamadas; as de leitura devolvem vazio e as de escrita não fazem nada. `data/decisions.json` nem é criado.
- A trava está em `load_raw()` / `save_raw()`, as duas funções por onde passam todas as 16 gavetas. É de propósito que ela fique aí e não no cliente: assim um pedido com `persist_rules=true` vindo de um front-end antigo (ou feito à mão na API) também não grava.
- Motivo: `decisions.json` é **único e global**, sem separação por usuário ou conta. Ligada numa instalação compartilhada, os nomes de clientes de um escritório apareceriam como sugestão no de outro.
- A tela consulta `GET /api/config` (`{"memoria": bool}`) e esconde o checkbox "Lembrar dessas decisões" e a frase "o sistema vai lembrar disso da próxima vez" quando está desligada. O módulo `frontend/src/config.js` começa **pessimista** (`memoria: false`) para que nenhum texto prometa memória antes da resposta chegar.
- Ao mexer nisso, mexa nos dois lados: desligar no servidor sem esconder na tela faz o app prometer o que não cumpre.

Por que `/api/config` e não um valor injetado no template: injetar no `templates/app.html` deixaria `frontend/index.html` (o servidor do Vite) sem o valor — a armadilha dos dois pontos de entrada, logo acima.

## Dados locais e privacidade

- `data/` é criada automaticamente (`app.py` cria `data/sessions/` ao ser importado). Contém planilhas de clientes. Está no `.gitignore`: nunca versione, nunca cole em issues.
- `data/decisions.json` só existe com a memória ligada, e aí é **global**: uma decisão tomada numa sessão vale para todas as outras.
- `SESSIONS` vive só na memória. Reiniciar o servidor encerra as sessões ativas (o download devolve 404), mas os arquivos continuam em `data/sessions/`.
- Nada é enviado para fora. A única requisição externa da página é a fonte do Google (ver README).

## Testes

- `python -m pytest tests`: 127 casos em 9 arquivos `tests/test_*.py`. Vários são parametrizados.
- Muitos testes codificam uma **forma** de nome (número de palavras, iniciais, acentos, prefixos, ordem). As regras do motor foram calibradas nessas formas. Se você trocar um nome de fixture por outro, o teste pode continuar verde sem provar mais nada. Mantenha a mesma forma e use nome fictício (ver CONTRIBUTING.md).
- Teste que toca decisões deve isolar o arquivo **e** ligar a memória: `monkeypatch.setattr(rules_store, "STORE_PATH", ...)`, `DATA_DIR` e `MEMORIA` juntos, como em `tests/test_label_clusters_integration.py`. Sem ligar `MEMORIA`, a gravação é um no-op e o teste passa sem testar nada.

## Configuração

Tudo por variáveis de ambiente (veja `.env.example`). O app **não** lê o `.env`: exporte as variáveis no shell antes de iniciar.

| Variável               | Obrigatória | Descrição                                                   |
|------------------------|-------------|-------------------------------------------------------------|
| `PADRONIZADOR_PORT`    | Não (5057)  | Porta do Flask; também usada pelo proxy do Vite e pelo run.bat |
| `PADRONIZADOR_HOST`    | Não (127.0.0.1) | Endereço de escuta                                      |
| `PADRONIZADOR_MEMORIA` | Não (`0` = desligada) | Memória de decisões entre planilhas. Só ligar em instalação de uso pessoal — ver a seção acima |

## Convenções

- Textos da interface, comentários e docstrings em português.
- `ocr_helper.py` e `run.bat` são exclusivos do Windows.
- Nunca commitar `.xlsx`, `.xls`, `.csv`, `.pdf`, `decisions.json` ou `data/`.

## Contribuição

Veja [CONTRIBUTING.md](CONTRIBUTING.md).
