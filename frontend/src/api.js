// Wrapper fino sobre as mesmas rotas /api/* que o Flask ja expunha antes
// dessa reescrita de front-end - nenhuma delas mudou (upload, analyze,
// apply, ocr, download), so quem consome mudou de vanilla JS pra Vue.
const BASE = "/api";

// Como reerguer uma sessao que morreu no servidor. Fica AQUI, e nao em cada
// chamada, porque a sessao pode cair em qualquer uma delas - e quem chama nao
// tem como saber disso. Ver App.vue (recuperarSessao).
let recuperar = null;
let recuperacaoEmCurso = null;

export function configurarRecuperacao(fn) {
  recuperar = fn;
}

const SESSAO_MORTA = /sess[aã]o n[aã]o encontrada/i;

function trocarSessao(options, sessionId) {
  if (!options.body || typeof options.body !== "string") return options;
  try {
    const corpo = JSON.parse(options.body);
    if (!("session_id" in corpo)) return options;
    return { ...options, body: JSON.stringify({ ...corpo, session_id: sessionId }) };
  } catch {
    return options;
  }
}

async function request(path, options = {}, jaTentou = false) {
  const res = await fetch(BASE + path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const morreu = res.status === 404 && SESSAO_MORTA.test(data.error || "");
    if (morreu && recuperar && !jaTentou) {
      // Reenviar os arquivos e refazer a analise custa segundos; perder a
      // revisao custa o trabalho inteiro da pessoa. Uma tentativa so: se a
      // sessao nova tambem nao for encontrada, o erro sobe de verdade.
      //
      // A promessa fica compartilhada pra que duas chamadas simultaneas nao
      // disparem dois uploads - a segunda espera a mesma recuperacao.
      if (!recuperacaoEmCurso) {
        recuperacaoEmCurso = Promise.resolve()
          .then(recuperar)
          .finally(() => { recuperacaoEmCurso = null; });
      }
      const novoId = await recuperacaoEmCurso;
      if (novoId) return request(path, trocarSessao(options, novoId), true);
    }
    throw new Error(data.error || `Erro ${res.status}`);
  }
  return data;
}

export function carregarConfig() {
  return request("/config");
}

export function uploadArquivos(formData) {
  return request("/upload", { method: "POST", body: formData });
}

export function analisar(payload) {
  return request("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function aplicar(payload) {
  return request("/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Sinal de vida: segura a sessao no servidor e acorda a instancia. */
export function ping(sessionId) {
  return request(`/ping/${sessionId}`, { method: "POST" });
}

export function extrairOcr(formData) {
  return request("/ocr", { method: "POST", body: formData });
}

export function downloadUrl(sessionId, kind) {
  return `${BASE}/download/${sessionId}/${kind}`;
}
