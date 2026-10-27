<script setup>
import { reactive, ref, computed, watch } from "vue";
import * as api from "../api";

const props = defineProps({
  responsaveisText: { type: String, default: "" },
  suggestions: { type: Array, required: true },
});
const emit = defineEmits(["update:responsaveisText", "compare"]);

const imageFile = ref(null);
const ocrLoading = ref(false);
const ocrError = ref("");

const registry = computed(() =>
  props.responsaveisText.split("\n").map((l) => l.trim()).filter(Boolean)
);

const state = reactive({});

function initState() {
  for (const key of Object.keys(state)) delete state[key];
  for (const s of props.suggestions) {
    const useSuggestion = s.suggested_official && s.score >= 70;
    state[s.norm] = {
      selected: useSuggestion ? s.suggested_official : "",
      custom: "",
    };
  }
}
watch(() => props.suggestions, initState, { immediate: true });

function onTextareaInput(e) {
  emit("update:responsaveisText", e.target.value);
}

async function onExtractOcr() {
  if (!imageFile.value) {
    alert("Escolha uma imagem primeiro.");
    return;
  }
  ocrError.value = "";
  ocrLoading.value = true;
  try {
    const fd = new FormData();
    fd.append("image", imageFile.value);
    const data = await api.extrairOcr(fd);
    const existing = props.responsaveisText.trim();
    const extracted = data.names.join("\n");
    emit("update:responsaveisText", existing ? existing + "\n" + extracted : extracted);
  } catch (err) {
    ocrError.value = `Erro no OCR: ${err.message}`;
  } finally {
    ocrLoading.value = false;
  }
}

function restaurar(salvas) {
  if (!salvas || !salvas.length) return 0;
  const porNorm = new Map(salvas.map((d) => [d.norm, d]));
  let n = 0;
  for (const s of props.suggestions) {
    const d = porNorm.get(s.norm);
    if (!d || !state[s.norm]) continue;
    const escolhido = d.action === "apply" ? (d.canonical || "") : "";
    // se o texto salvo nao e uma das opcoes oficiais, ele foi digitado a mao
    if (escolhido && !registry.value.includes(escolhido)) {
      state[s.norm].selected = "__custom__";
      state[s.norm].custom = escolhido;
    } else {
      state[s.norm].selected = escolhido;
    }
    n++;
  }
  return n;
}

function collectDecisions() {
  return props.suggestions.map((s) => {
    const st = state[s.norm];
    const canonical = st.selected === "__custom__" ? st.custom.trim() : st.selected;
    return {
      norm: s.norm,
      action: canonical ? "apply" : "skip",
      canonical,
    };
  });
}

defineExpose({ restaurar, collectDecisions });
</script>

<template>
  <section id="responsaveis-section" class="card">
    <h2>8. Responsáveis (usuários do sistema)</h2>
    <p class="hint">
      Cole abaixo a lista de responsáveis/usuários como eles existem no seu sistema (um por linha), ou envie um print
      da tela de usuários para tentar extrair automaticamente. Revise o texto extraído antes de comparar — o OCR
      pode errar acentos.
    </p>

    <div class="field">
      <label for="responsaveis-image">Print da lista de usuários (opcional)</label>
      <div class="field inline">
        <input type="file" id="responsaveis-image" accept="image/*" @change="imageFile = $event.target.files[0] || null">
        <button type="button" class="secondary" :disabled="ocrLoading" @click="onExtractOcr">
          {{ ocrLoading ? "Extraindo..." : "Extrair nomes do print" }}
        </button>
      </div>
      <div v-if="ocrError" class="error-msg">{{ ocrError }}</div>
    </div>

    <div class="field">
      <label for="responsaveis-textarea">Lista oficial de responsáveis (um nome por linha)</label>
      <textarea
        id="responsaveis-textarea"
        rows="5"
        placeholder="ROBERTO ALVES DE MENEZES JUNIOR&#10;PATRICIA HELENA DA ROCHA&#10;..."
        :value="responsaveisText"
        @input="onTextareaInput"
      ></textarea>
    </div>

    <button type="button" @click="emit('compare')">Comparar responsáveis</button>

    <div id="responsaveis-list">
      <p v-if="suggestions.length === 0">Nenhuma divergência encontrada nos responsáveis.</p>
      <div v-for="s in suggestions" :key="s.norm" class="resp-row">
        <span class="resp-current">{{ s.text }} ({{ s.count }}x)</span>
        <span v-if="s.suggested_official" class="resp-arrow">→ ({{ s.score.toFixed(1) }}%)</span>

        <select class="resp-select" v-model="state[s.norm].selected" v-if="state[s.norm]">
          <option value="">Não alterar</option>
          <option v-for="name in registry" :key="name" :value="name">{{ name }}</option>
          <option value="__custom__">Outro (digitar)...</option>
        </select>

        <input
          v-if="state[s.norm] && state[s.norm].selected === '__custom__'"
          type="text"
          class="resp-custom"
          placeholder="nome final..."
          v-model="state[s.norm].custom"
        >

        <span v-if="!s.suggested_official" class="resp-not-found">nenhum responsável parecido encontrado na lista</span>
      </div>
    </div>
  </section>
</template>
