// Autossalvamento da revisao no PROPRIO NAVEGADOR.
//
// Por que aqui e nao no servidor: a revisao inteira acontece na tela e nao
// gera nenhuma requisicao enquanto a pessoa le. Numa hospedagem que dorme por
// inatividade, isso significa que o servidor some justamente durante o
// trabalho - e, em plano de disco efemero, leva os arquivos junto. O unico
// lugar que sobrevive a tudo isso e a maquina de quem esta revisando.
//
// Sao duas coisas guardadas, em lugares diferentes de proposito:
//   - as DECISOES vao pro localStorage (texto, pequeno, leitura sincrona);
//   - os ARQUIVOS enviados vao pro IndexedDB (unico que guarda binario de
//     verdade; uma planilha nao cabe no localStorage).
//
// Nada disso sai da maquina da pessoa, e some junto com os dados do site.

const CHAVE_DECISOES = "padronizador:decisoes";
const BANCO = "padronizador";
const LOJA = "arquivos";
const CHAVE_ARQUIVOS = "sessao-atual";

// --- decisoes -------------------------------------------------------------

export function salvarDecisoes(payload) {
  try {
    localStorage.setItem(CHAVE_DECISOES, JSON.stringify({
      quando: Date.now(),
      payload,
    }));
  } catch {
    // cota cheia ou armazenamento bloqueado (aba anonima): o autossalvamento
    // e uma rede de seguranca, nunca pode derrubar a revisao em andamento
  }
}

export function carregarDecisoes() {
  try {
    const bruto = localStorage.getItem(CHAVE_DECISOES);
    if (!bruto) return null;
    return JSON.parse(bruto).payload || null;
  } catch {
    return null;
  }
}

export function limparSalvo() {
  try {
    localStorage.removeItem(CHAVE_DECISOES);
  } catch {
    // idem
  }
}

// --- arquivos enviados ----------------------------------------------------

function abrirBanco() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(BANCO, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(LOJA)) req.result.createObjectStore(LOJA);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function comLoja(modo, fn) {
  return abrirBanco().then((bd) => new Promise((resolve, reject) => {
    const tx = bd.transaction(LOJA, modo);
    const req = fn(tx.objectStore(LOJA));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  })).catch(() => null);
}

/** Guarda os arquivos do upload pra poder reenviar sozinho depois. */
export function guardarArquivos(formData) {
  const campos = [];
  for (const [nome, valor] of formData.entries()) {
    if (valor instanceof File && valor.size) campos.push({ nome, arquivo: valor });
  }
  if (!campos.length) return Promise.resolve(false);
  return comLoja("readwrite", (loja) => loja.put(campos, CHAVE_ARQUIVOS)).then(() => true);
}

/** Devolve um FormData igual ao do upload original, ou null se nao houver. */
export function recuperarArquivos() {
  return comLoja("readonly", (loja) => loja.get(CHAVE_ARQUIVOS)).then((campos) => {
    if (!campos || !campos.length) return null;
    const fd = new FormData();
    for (const { nome, arquivo } of campos) fd.append(nome, arquivo, arquivo.name);
    return fd;
  });
}

export function esquecerArquivos() {
  return comLoja("readwrite", (loja) => loja.delete(CHAVE_ARQUIVOS));
}
