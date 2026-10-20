// Configuracao do servidor, lida uma vez em /api/config.
//
// Fica num modulo proprio em vez de prop vinda do App.vue porque mais de uma
// secao precisa dela (ApplySection, ClustersSection) e nenhuma e filha direta
// da outra.
import { reactive } from "vue";

import * as api from "./api";

export const config = reactive({
  // Pessimista de proposito: ANTES da resposta chegar, a tela se comporta como
  // se nao houvesse memoria. Assim nenhum texto chega a prometer que o sistema
  // vai lembrar de algo que talvez ele nao va lembrar.
  memoria: false,
  carregada: false,
});

export async function inicializarConfig() {
  try {
    const data = await api.carregarConfig();
    config.memoria = !!data.memoria;
  } catch {
    // Servidor antigo ou fora do ar: fica no padrao sem memoria, que e o
    // comportamento seguro - no pior caso a tela deixa de oferecer "lembrar",
    // nunca o contrario.
  } finally {
    config.carregada = true;
  }
}
