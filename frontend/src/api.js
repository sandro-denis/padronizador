// Wrapper fino sobre as mesmas rotas /api/* que o Flask ja expunha antes
// dessa reescrita de front-end - nenhuma delas mudou (upload, analyze,
// apply, ocr, download), so quem consome mudou de vanilla JS pra Vue.
const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(BASE + path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
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

export function extrairOcr(formData) {
  return request("/ocr", { method: "POST", body: formData });
}

export function downloadUrl(sessionId, kind) {
  return `${BASE}/download/${sessionId}/${kind}`;
}
