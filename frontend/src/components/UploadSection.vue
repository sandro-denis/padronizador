<script setup>
import { ref, watch } from "vue";

const props = defineProps({
  status: { type: Object, default: null },
});
const emit = defineEmits(["uploaded"]);

const escavadorFile = ref(null);
const clientesFile = ref(null);
const financeiroFile = ref(null);
const advboxPessoasFile = ref(null);
const advboxProcessosFile = ref(null);
const sending = ref(false);
const localError = ref("");

watch(() => props.status, () => { sending.value = false; });

function onSubmit() {
  if (!escavadorFile.value && !clientesFile.value) {
    localError.value = "Envie pelo menos a planilha do Escavador ou a de Clientes.";
    return;
  }
  localError.value = "";
  const fd = new FormData();
  if (escavadorFile.value) fd.append("escavador", escavadorFile.value);
  if (clientesFile.value) fd.append("clientes", clientesFile.value);
  if (financeiroFile.value) fd.append("financeiro", financeiroFile.value);
  if (advboxPessoasFile.value) fd.append("advbox_pessoas", advboxPessoasFile.value);
  if (advboxProcessosFile.value) fd.append("advbox_processos", advboxProcessosFile.value);
  sending.value = true;
  emit("uploaded", fd);
}
</script>

<template>
  <section id="upload-section" class="card">
    <h2>1. Envie as planilhas</h2>
    <p class="hint">Envie pelo menos uma das duas planilhas abaixo — pode ser só a de Clientes, por exemplo, pra validar contra o ADVBOX sem mexer em processos.</p>
    <form @submit.prevent="onSubmit">
      <div class="field">
        <label>Planilha do Escavador (Processos) <span class="opt">opcional</span></label>
        <input type="file" accept=".xlsx" @change="escavadorFile = $event.target.files[0] || null">
      </div>
      <div class="field">
        <label>Planilha de Clientes (com CPF) <span class="opt">opcional</span></label>
        <input type="file" accept=".xlsx" @change="clientesFile = $event.target.files[0] || null">
      </div>
      <div class="field">
        <label>Planilha de Financeiro <span class="opt">opcional</span></label>
        <input type="file" accept=".xlsx" @change="financeiroFile = $event.target.files[0] || null">
        <p class="hint">Confere se cada nome dos lançamentos existe em Processos ou Clientes. Quem não existir em nenhuma das duas some da coluna do cliente e vai para a descrição do lançamento.</p>
      </div>

      <div class="upload-divider"><span>Validar com o ADVBOX</span><span class="opt">opcional</span></div>
      <p class="hint">Envie os relatórios em PDF ("Página de impressão") exportados do ADVBOX para cruzar os nomes já cadastrados na sua conta com os desta planilha.</p>
      <div class="field">
        <label>ADVBOX — Lista de pessoas <span class="opt">opcional</span></label>
        <input type="file" accept=".pdf" @change="advboxPessoasFile = $event.target.files[0] || null">
      </div>
      <div class="field">
        <label>ADVBOX — Resumo de processos <span class="opt">opcional</span></label>
        <input type="file" accept=".pdf" @change="advboxProcessosFile = $event.target.files[0] || null">
      </div>

      <button type="submit" :disabled="sending">{{ sending ? "Enviando..." : "Enviar e analisar" }}</button>
    </form>
    <div v-if="localError" class="error-msg">{{ localError }}</div>
    <div v-if="sending" class="ok-msg">Enviando...</div>
    <div v-else-if="status && status.type === 'ok'" class="ok-msg">{{ status.message }}</div>
    <div v-else-if="status && status.type === 'error'" class="error-msg">{{ status.message }}</div>
  </section>
</template>
