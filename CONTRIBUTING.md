# Como contribuir

Obrigado pelo interesse. Este é um projeto pequeno e prático: a prioridade é não
estragar planilha de ninguém.

## Nunca envie dado real de cliente

Esta é a regra mais importante, e vale para código, testes, comentários, issues
e prints de tela.

- **Não** faça commit de `.xlsx`, `.xls`, `.csv`, `.pdf`, `decisions.json` ou de
  qualquer coisa dentro de `data/`. O `.gitignore` já cobre isso — não force.
- **Não** use nome real de pessoa ou de empresa em teste, fixture, comentário ou
  docstring. Nem o de um cliente, nem o da sua equipe.
- Em issue, **não** cole nome real nem anexe planilha de verdade. Reproduza com
  dado fictício. Se o problema só acontece com um nome específico, descreva a
  **forma** dele ("nome de 5 palavras, com 'VARA' no meio") em vez do nome.

## Nome fictício tem que ter a mesma forma

Boa parte dos testes aqui não verifica código: verifica **forma de nome**. As
regras do motor foram calibradas em cima de propriedades exatas — quantas
palavras, quais iniciais, onde cai o acento, se um nome é prefixo do outro, se
duas palavras têm o mesmo radical.

Por isso, trocar um nome de fixture por outro qualquer faz o teste continuar
verde sem provar mais nada. Quando precisar de um nome, escolha um fictício com
a **mesma propriedade** do caso que você quer cobrir.

Exemplos reais do repositório:

| Propriedade que o teste exercita | Como manter ao inventar o nome |
|---|---|
| `expandir_sigla("MARF")` acha o nome pelas iniciais | o substituto tem que continuar dando M-A-R-F |
| partícula ignorada na sigla (`CELIA MARIA DE MONÇÃO PACHECO` → `CMMP`) | manter o `DE` no meio e as 4 iniciais |
| nome curto que é prefixo estrito do longo (`LUZA` / `LUZANIR`) | manter a relação de prefixo e o tamanho |
| palavra quebrada na importação (`CONSTRUC` + `OES`) | manter a quebra no mesmo ponto |
| última palavra flexionada (`ALIMENTACAO` / `ALIMENTOS`) | manter um par de mesmo radical |
| artigo no início da razão social (`O FACILITADOR …`) | manter o artigo |

Se não der para preservar a forma, diga isso no PR em vez de ajustar a asserção
para o teste passar.

## Rodando

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python -m pytest tests
```

São 176 testes. Precisam passar antes e depois da sua mudança.

Mexeu em `frontend/src`? Rode `npm run build` de novo — o Flask serve o bundle
de `static/dist/`, não os fontes. Mexeu num `.py` ou num template? Reinicie o
servidor: ele roda com `debug=False` e mantém tudo em cache.

## Mudança no motor de comparação vem com teste

`matching.py` é a parte do projeto em que um acerto aparente vira erro silencioso
em escala: afrouxar um limiar para juntar dois nomes que você viu hoje pode
juntar duas pessoas diferentes em mil planilhas amanhã.

Então, para qualquer mudança em `matching.py`:

1. escreva o teste do caso que você quer passar a cobrir;
2. escreva **também** o teste do caso vizinho que precisa continuar separado —
   é esse que protege contra o efeito colateral;
3. implemente.

Vários testes existentes têm esse par (um `test_..._agrupa` e um
`test_..._nao_agrupa` logo abaixo). Siga o padrão.

## Memória de decisões

A memória entre planilhas (`PADRONIZADOR_MEMORIA`) vem **desligada** e deve
continuar assim por padrão. O arquivo de decisões é único e global, sem
separação por usuário — ligá-lo por padrão faria uma instalação compartilhada
misturar dados de escritórios diferentes. Há teste cobrindo isso
(`tests/test_memoria_desligada.py`).

Se mexer nisso, mexa nos dois lados: servidor e tela. Desligar no servidor sem
esconder o checkbox na interface faz o app prometer o que não cumpre.

## Estilo

Olhe o arquivo em volta e escreva parecido. Comentários e docstrings em
português, explicando **por que** a regra existe — de preferência com o caso que
a motivou, descrito de forma genérica. É esse "por quê" que impede alguém de
remover a regra seis meses depois por parecer arbitrária.
