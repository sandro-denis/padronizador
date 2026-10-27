# Padronizador de Clientes

Ferramenta web local (Flask + Vue 3) para padronizar nomes de partes em planilhas
de processos jurídicos antes da importação no sistema de gestão de processos.

Ela encontra homônimos e duplicatas (o mesmo cliente, ou a mesma empresa, escrito
de formas diferentes), mostra os grupos para você revisar um a um, registra cada
decisão e gera as planilhas corrigidas e um resumo das alterações.

Ao resolver uma duplicata no cadastro de clientes, o dado da linha removida
**não é descartado**: o que estava vazio na linha que fica é preenchido, e o que
diverge vai para `ANOTAÇÕES GERAIS` dizendo de qual coluna veio — porque dois
valores diferentes para o mesmo campo são uma divergência que só quem conhece o
cliente resolve.

**Rodando na sua máquina — que é o uso para o qual foi feita — nenhum dado sai
dela.** A ferramenta não chama serviço externo nenhum: a única requisição que a
página faz para fora é a fonte do Google (e dá para remover, veja
[Privacidade](#privacidade)).

Dá para hospedar numa instância compartilhada, e há um `Dockerfile` pronto para
isso, mas aí essa frase deixa de valer: as planilhas passam a subir para um
servidor. Leia [Hospedar uma instância](#hospedar-uma-instância) antes.

## Requisitos

- Python 3.11 ou superior
- Node.js LTS (necessário para compilar a interface Vue; veja abaixo)
- Windows, para o OCR de prints de tela (usa o OCR nativo do Windows via PowerShell).
  O restante funciona em outros sistemas, mas o `run.bat` é específico para Windows.

## Instalação e execução

```bash
pip install -r requirements.txt

cd frontend
npm install
npm run build        # gera ../static/dist (app.js e app.css)
cd ..

python app.py
```

O Flask serve a interface a partir de `static/dist/`. Essa pasta **não** vem no
repositório: ela é gerada por `npm run build` e precisa existir antes da primeira
execução. Depois de alterar qualquer arquivo em `frontend/src`, rode `npm run build`
de novo e reinicie o servidor.

No Windows, o `run.bat` faz tudo isso sozinho: instala as dependências na primeira
vez, compila a interface se o Node.js estiver disponível, libera a porta e abre o
programa no navegador.

## Configuração

Veja `.env.example`. As variáveis são lidas do ambiente:

| Variável               | Padrão      | Para que serve                             |
|------------------------|-------------|--------------------------------------------|
| `PADRONIZADOR_PORT`    | `5057`      | Porta do servidor (também usada pelo proxy do Vite) |
| `PADRONIZADOR_HOST`    | `127.0.0.1` | Endereço de escuta do servidor             |
| `PADRONIZADOR_MEMORIA` | `0`         | Memória de decisões entre planilhas — ver abaixo |
| `PADRONIZADOR_SESSAO_TTL_MIN` | `1440` (24h) | Minutos que uma sessão fica no disco antes de ser apagada; `0` desliga a limpeza |

O app não carrega o `.env` automaticamente: defina as variáveis no shell antes de
iniciar, ou ajuste o valor diretamente no `run.bat`.

## O app não guarda o que você padroniza

Por padrão, **nada do que você decide na revisão é salvo**. Cada planilha é
revisada do zero, e o arquivo de decisões nem chega a ser criado. O que sai da
revisão são as planilhas corrigidas e o resumo — nada além disso fica na máquina.

Existe uma memória opcional: ligada, o app lembra os pares que você confirmou (e
os que você disse que **não** são a mesma pessoa) e já vem com eles marcados na
próxima planilha. É útil quando você reprocessa as mesmas contas sempre.

**Mas só ligue se a instalação for de uso pessoal, na sua própria máquina, com
os dados de um único escritório.** O arquivo de decisões é **único e global** —
não há separação por usuário nem por conta. Numa instalação usada por mais de
uma pessoa, ou com planilhas de mais de um escritório, ligar a memória faria os
nomes de clientes de um aparecerem como sugestão no do outro.

Para ligar:

```bash
PADRONIZADOR_MEMORIA=1 python app.py
```

A trava fica no servidor, não na tela: com a memória desligada, nem um pedido
feito à mão na API consegue gravar decisão. Quando está desligada, a tela também
deixa de oferecer a opção de lembrar, em vez de prometer algo que não aconteceria.

## Dados locais

O app cria a pasta `data/`, que guarda:

- `data/sessions/`: os arquivos enviados e as planilhas geradas em cada sessão.
- `data/decisions.json`: **só existe se você ligar `PADRONIZADOR_MEMORIA`**;
  guarda as decisões da revisão.

Essa pasta contém dados de clientes. Ela está no `.gitignore` e não deve ser
versionada nem compartilhada. Apagar `data/sessions/` é seguro a qualquer
momento — são arquivos de trabalho já baixados.

## Hospedar uma instância

Há um `Dockerfile` e um `render.yaml` prontos. **Mas pense antes de hospedar**,
porque o modelo de confiança muda por completo.

### O que muda

Rodando local, a planilha nunca sai da sua máquina. Numa instância compartilhada,
ela sobe para um servidor que **você** escolheu — e se quem usa for outro
escritório, você passa a tratar dado pessoal de terceiros (nome, CPF) em
infraestrutura sua. Isso tem consequência de LGPD que não é técnica e este
README não resolve.

### O que já está configurado para reduzir risco

| Medida | Como |
|---|---|
| Memória de decisões **desligada** | `PADRONIZADOR_MEMORIA=0`. O `decisions.json` é único e global: ligado, mostraria decisões e nomes de um escritório a outro |
| Sessão **apagada** do disco | `PADRONIZADOR_SESSAO_TTL_MIN=60`. A varredura roda a cada upload e remove o que passou do prazo, inclusive o que sobrou de um reinício |
| Nenhuma tela de histórico | Não existe rota que liste sessões. Ninguém enumera o que outro rodou |
| OCR ausente em vez de quebrado | O OCR usa a API do Windows; em Linux `/api/config` informa e a interface esconde a seção |
| Um worker só | O estado da revisão vive na memória do processo — mas é **cache**: qualquer worker remonta a sessão a partir dos arquivos no disco |
| A revisão **não se perde** | O navegador guarda as decisões e os arquivos enviados; se a sessão morrer no servidor, a página reenvia e religa tudo sozinha |
| Sessão em uso **não é varrida** | A aba manda sinal de vida (`/api/ping`). Sem isso, o upload de uma pessoa apagava a revisão longa de outra |

### O que NÃO está resolvido

- **Não há login.** O ID da sessão (48 bits, no caminho da URL) é a única
  credencial. URL entra em log de servidor, de proxy e no histórico do
  navegador — quem alcançar o log alcança o download enquanto a sessão existir.
  Para uso com dado real por mais de um escritório, **coloque autenticação na
  frente** (proxy com senha, OAuth, VPN).
- **Mais de um worker ainda não foi exercitado.** A sessão já é remontável do
  disco (`_rehidratar_sessao`), que era o impedimento de fundo, mas o
  `Dockerfile` segue com um worker só até isso ser testado de verdade.
- **Reiniciar interrompe, mas não perde.** A revisão volta sozinha. O que se
  perde é o tempo do reenvio e de refazer a análise, não o trabalho.

### Como a revisão sobrevive ao servidor

A revisão inteira acontece no navegador: entre "analisar" e "aplicar" **nenhuma
requisição é feita**. Para o servidor, alguém lendo 300 nomes com cuidado é
alguém ausente — e foi assim que uma revisão real de 158 itens se perdeu, numa
instância gratuita que dormiu por inatividade.

Três camadas resolvem isso, nessa ordem de defesa:

1. **Sinal de vida** (`POST /api/ping/<id>`, a cada 3 minutos enquanto a aba
   está aberta). Mantém a instância acordada e marca a sessão como em uso, para
   que a varredura por tempo não apague o trabalho de quem ainda está nele —
   nem mesmo quando disparada pelo upload de outra pessoa.
2. **Remontagem do disco.** O que a sessão guarda na memória é cache: dados já
   lidos e caminhos. Se o processo reinicia e os arquivos continuam no disco, a
   sessão é reconstruída sozinha na requisição seguinte.
3. **Autossalvamento no navegador.** As decisões vão para o `localStorage` a
   cada 15 segundos e os arquivos enviados, para o IndexedDB. Se a sessão morreu
   de vez (disco efêmero que reiniciou limpo), a página reenvia os arquivos,
   refaz a análise e religa cada decisão **pelo nome** — nunca pelo id, que só
   vale dentro de uma análise. Nada disso sai da máquina de quem está revisando.

A terceira camada depende de o agrupamento ser determinístico: o mesmo arquivo
com o mesmo limiar produz exatamente os mesmos grupos. É o que permite casar as
decisões salvas com a análise nova sem ambiguidade.

### Subindo no Render

1. Faça um fork ou use este repositório.
2. No Render: **New → Blueprint**, aponte para o repositório. O `render.yaml`
   já traz as variáveis.
3. Prefira hospedagem de **disco efêmero**: aí o dado desaparece no deploy
   seguinte, além da varredura por tempo.

Em qualquer outro host de contêiner, o `Dockerfile` basta:

```bash
docker build -t padronizador .
docker run -p 5057:5057 -e PADRONIZADOR_SESSAO_TTL_MIN=60 padronizador
```

## Testes

```bash
pip install pytest
python -m pytest tests
```

Os testes usam planilhas e nomes fictícios criados dentro do próprio teste. Os
testes de integração passam pelo app e, por isso, criam `data/sessions/` dentro do
projeto; essa pasta é ignorada pelo git e pode ser apagada depois.

## Estrutura

- `app.py`: rotas Flask e fluxo de upload, análise, revisão, aplicação e download.
- `matching.py`: normalização de nomes, clusters de homônimos e sugestão de forma canônica.
- `excel_io.py`, `advbox_io.py`, `ajustes_io.py`: leitura e escrita das planilhas.
- `rules_store.py`: persistência das decisões em `data/decisions.json`.
- `report.py`: resumo textual das alterações.
- `ocr_helper.py` e `ocr_engine.ps1`: OCR nativo do Windows para extrair nomes de prints.
- `frontend/`: interface Vue 3 + Vite (código-fonte). A saída vai para `static/dist/`.
- `templates/app.html`: página carregada pelo Flask.
- `tests/`: testes automatizados (pytest).

## Privacidade

A interface carrega a fonte Inter e JetBrains Mono do Google Fonts. Essa é a única
requisição externa feita pela página. Se quiser evitá-la, troque as fontes no
`templates/app.html` e no `frontend/index.html` por fontes locais.

## Licença

MIT. Veja `LICENSE`.
