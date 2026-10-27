<script setup>
import { reactive, ref, computed, watch, onMounted, onUnmounted } from "vue";
import * as api from "../api";
import { config } from "../config";

const props = defineProps({
  titulo: { type: String, required: true },
  descricao: { type: String, required: true },
  placeholder: { type: String, default: "" },
  registryText: { type: String, default: "" },
  suggestions: { type: Array, required: true },
  rotuloLista: { type: String, default: "Lista oficial da conta (um valor por linha)" },
  showOcr: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  // Homonimos DENTRO da propria planilha (find_label_clusters) - "COBRANÇA"
  // e "AÇÃO DE COBRANÇA" sendo provavelmente a mesma coisa, sem precisar de
  // lista nenhuma colada. Comparacao diferente da de baixo (que so aponta
  // divergencia contra uma lista externa ja vetada pelo usuario) - por isso
  // e um bloco proprio, revisado ANTES da comparacao com a lista.
  clusters: { type: Array, default: () => [] },
});
const emit = defineEmits(["update:registryText", "compare"]);

// ---- homonimos dentro da planilha (bloco de cima) ----
const clusterState = reactive({});
function initClusterState() {
  for (const key of Object.keys(clusterState)) delete clusterState[key];
  for (const c of props.clusters) {
    const remembered = c.remembered_canonical;
    const isRememberedCustom = !!remembered && !c.variants.some((v) => v.text === remembered);
    clusterState[c.id] = {
      action: "merge",
      canonical: remembered && !isRememberedCustom ? remembered : c.suggested_canonical,
      useCustom: isRememberedCustom,
      customCanonical: isRememberedCustom ? remembered : c.suggested_canonical,
      excluded: new Set(),
      // mesma regra de ClustersSection.vue: `remembered_canonical` e so
      // sugestao (memoria global entre campos iguais de outras planilhas) -
      // nao significa que o usuario ja revisou ESTE grupo NESTA planilha.
      touched: false,
    };
  }
}
watch(() => props.clusters, initClusterState, { immediate: true });

function markClusterTouched(id) {
  clusterState[id].touched = true;
}

function toggleClusterExclude(id, norm, checked) {
  if (checked) clusterState[id].excluded.add(norm);
  else clusterState[id].excluded.delete(norm);
  markClusterTouched(id);
}

function onClusterCanonicalChange(c, value) {
  if (value === "__custom__") {
    clusterState[c.id].useCustom = true;
  } else {
    clusterState[c.id].useCustom = false;
    clusterState[c.id].canonical = value;
  }
  markClusterTouched(c.id);
}

function formatClusterRows(rows, maxShow = 6) {
  if (!rows || !rows.length) return "";
  if (rows.length <= maxShow) return rows.join(", ");
  return rows.slice(0, maxShow).join(", ") + ` e mais ${rows.length - maxShow}`;
}

function aplicarTodosClusters() {
  for (const c of props.clusters) {
    clusterState[c.id].action = "merge";
    clusterState[c.id].touched = true;
  }
}
function separarTodosClusters() {
  for (const c of props.clusters) {
    clusterState[c.id].action = "ignore";
    clusterState[c.id].touched = true;
  }
}

function collectClusterDecisions() {
  return props.clusters.map((c) => {
    const s = clusterState[c.id];
    const canonical = s.useCustom ? s.customCanonical : s.canonical;
    const excludedMembers = c.variants.filter((v) => s.excluded.has(v.norm)).map((v) => v.norm);
    const keptMembers = c.members.filter((n) => !excludedMembers.includes(n));
    return {
      cluster_id: c.id,
      members: keptMembers,
      excluded_members: excludedMembers,
      action: s.action,
      canonical,
      touched: !!s.touched,
    };
  });
}
const clusterTouchedCount = computed(() =>
  Object.values(clusterState).filter((s) => s.touched).length
);

const registry = computed(() =>
  props.registryText.split("\n").map((l) => l.trim()).filter(Boolean)
);

// O bloco do print tambem depende do servidor: numa instancia Linux o OCR
// nativo do Windows nao existe (ver /api/config), e oferecer um botao que
// sempre falha e pior que nao oferecer nada.
const mostrarOcr = computed(() => props.showOcr && config.ocr);

const imageFile = ref(null);
const ocrLoading = ref(false);
const ocrError = ref("");

const state = reactive({});

function initState() {
  for (const key of Object.keys(state)) delete state[key];
  for (const s of props.suggestions) {
    // Regra: nada e aplicado sem o usuario marcar "Aplicar" explicitamente.
    // A unica excecao e quando ELE JA decidiu isso antes (decisao lembrada) -
    // ai a escolha anterior volta do jeito que estava.
    let action = "manter";
    let selected = s.suggested_official || "";
    if (s.remembered_action === "aplicar" && s.remembered_canonical) {
      action = "aplicar";
      selected = s.remembered_canonical;
    } else if (s.remembered_action === "manter") {
      action = "manter";
    }
    // `touched` = o usuario mexeu neste item nesta sessao. So o que ele
    // realmente decidiu e guardado pra proxima vez (ver app.py).
    state[s.norm] = { action, selected, custom: "", touched: false };
  }
}
watch(() => props.suggestions, initState, { immediate: true });

// `id` so vale dentro de UMA analise. O que atravessa uma sessao nova e o
// conjunto de nomes do grupo - o agrupamento e deterministico pro mesmo
// arquivo e o mesmo limiar, entao o mesmo grupo reaparece igual.
function chaveDeGrupo(nomes) {
  return [...nomes].sort().join("|");
}

function restaurar(salvasSugestoes, salvasClusters) {
  let n = 0;
  if (salvasSugestoes && salvasSugestoes.length) {
    const porNorm = new Map(salvasSugestoes.map((d) => [d.norm, d]));
    for (const s of props.suggestions) {
      const d = porNorm.get(s.norm);
      if (!d || !state[s.norm]) continue;
      state[s.norm].action = d.action === "aplicar" ? "aplicar" : "manter";
      if (d.canonical) state[s.norm].selected = d.canonical;
      state[s.norm].touched = !!d.touched;
      n++;
    }
  }
  if (salvasClusters && salvasClusters.length) {
    const porChave = new Map(salvasClusters.map((d) => [
      chaveDeGrupo([...(d.members || []), ...(d.excluded_members || [])]), d,
    ]));
    for (const c of props.clusters) {
      const d = porChave.get(chaveDeGrupo(c.members));
      const s = clusterState[c.id];
      if (!d || !s) continue;
      const ehVariante = c.variants.some((v) => v.text === d.canonical);
      s.action = d.action;
      s.useCustom = !ehVariante;
      if (ehVariante) s.canonical = d.canonical;
      else s.customCanonical = d.canonical;
      s.excluded = new Set(d.excluded_members || []);
      s.touched = !!d.touched;
      n++;
    }
  }
  return n;
}

function formatRowList(rows, maxShow = 6) {
  if (!rows || !rows.length) return "";
  if (rows.length <= maxShow) return rows.join(", ");
  return rows.slice(0, maxShow).join(", ") + ` e mais ${rows.length - maxShow}`;
}

function onTextareaInput(e) {
  emit("update:registryText", e.target.value);
}

function marcarTocado(norm) {
  if (state[norm]) state[norm].touched = true;
}

function aplicarTodasSugestoes() {
  for (const s of props.suggestions) {
    if (s.suggested_official && state[s.norm]) {
      state[s.norm].action = "aplicar";
      state[s.norm].selected = s.suggested_official;
      state[s.norm].touched = true;
    }
  }
}

function naoAlterarNenhuma() {
  for (const s of props.suggestions) {
    if (state[s.norm]) {
      state[s.norm].action = "manter";
      state[s.norm].touched = true;
    }
  }
}

async function onExtractOcr() {
  if (!imageFile.value) {
    ocrError.value = "Escolha uma imagem primeiro.";
    return;
  }
  ocrError.value = "";
  ocrLoading.value = true;
  try {
    const fd = new FormData();
    fd.append("image", imageFile.value);
    const data = await api.extrairOcr(fd);
    const existing = props.registryText.trim();
    const extracted = (data.names || []).join("\n");
    emit("update:registryText", existing ? existing + "\n" + extracted : extracted);
  } catch (err) {
    ocrError.value = `Erro no OCR: ${err.message}`;
  } finally {
    ocrLoading.value = false;
  }
}

function collectDecisions() {
  return props.suggestions.map((s) => {
    const st = state[s.norm];
    const touched = !!(st && st.touched);
    if (!st || st.action !== "aplicar") {
      return { norm: s.norm, action: "manter", touched };
    }
    const canonical = st.selected === "__custom__" ? st.custom.trim() : st.selected;
    if (!canonical) return { norm: s.norm, action: "manter", touched };
    return { norm: s.norm, action: "aplicar", canonical, touched };
  });
}

const touchedCount = computed(() =>
  Object.values(state).filter((s) => s.touched).length + clusterTouchedCount.value
);

defineExpose({ restaurar, collectDecisions, collectClusterDecisions, touchedCount });

// Mesmo padrao de ClustersSection.vue: atalho so age com o mouse sobre a
// lista e nunca com foco em campo de texto.
const isHovered = ref(false);
function onKeydown(e) {
  if (!isHovered.value) return;
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (e.key === "A" && e.shiftKey) { e.preventDefault(); aplicarTodasSugestoes(); }
  if (e.key === "I" && e.shiftKey) { e.preventDefault(); naoAlterarNenhuma(); }
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <section @mouseenter="isHovered = true" @mouseleave="isHovered = false">
    <h2>{{ titulo }}</h2>
    <p class="hint">{{ descricao }}</p>

    <div v-if="clusters.length" class="clusters-grid homonimos-planilha">
      <h3>Homônimos dentro desta planilha</h3>
      <p class="hint">
        Valores que aparecem escritos de formas diferentes na própria planilha e provavelmente são a mesma coisa —
        isso é comparado antes e não depende da lista colada abaixo.
      </p>

      <div class="toolbar">
        <div class="bulk-actions">
          <button type="button" class="secondary small" @click="aplicarTodosClusters">Unificar todos</button>
          <button type="button" class="secondary small" @click="separarTodosClusters">Manter todos separados</button>
        </div>
      </div>

      <div
        v-for="c in clusters"
        :key="c.id"
        class="cluster-card"
        :class="{ 'is-touched': clusterState[c.id] && clusterState[c.id].touched }"
      >
        <div class="cluster-header">
          <span class="badge badge-confidence" :class="c.score >= 98 ? 'score-high' : 'score-mid'">{{ c.score.toFixed(1) }}%</span>
          <span v-for="r in c.reasons" :key="r" class="badge reason">{{ r === 'confirmado' ? 'confirmado antes' : 'mesmo conteúdo, grafia diferente' }}</span>
          <span v-if="c.remembered_canonical" class="badge badge-remembered">nome já visto antes</span>
        </div>

        <div class="variants-col" v-if="clusterState[c.id]">
          <div
            v-for="v in c.variants"
            :key="v.text"
            class="variant-row"
            :class="{ 'variant-excluded': clusterState[c.id].excluded.has(v.norm) }"
          >
            <label class="variant-exclude" title="Não faz parte deste grupo - excluir da fusão">
              <input
                type="checkbox"
                :checked="clusterState[c.id].excluded.has(v.norm)"
                @change="toggleClusterExclude(c.id, v.norm, $event.target.checked)"
              >
            </label>
            <span class="variant-text">{{ v.text }}</span>
            <span class="variant-counts">Linha{{ v.rows.length > 1 ? "s" : "" }} {{ formatClusterRows(v.rows) }}</span>
          </div>
        </div>

        <div class="decision-col" v-if="clusterState[c.id]">
          <div class="canonical-row">
            <label>Valor final:</label>
            <select
              :value="clusterState[c.id].useCustom ? '__custom__' : clusterState[c.id].canonical"
              @change="onClusterCanonicalChange(c, $event.target.value)"
            >
              <option v-for="v in c.variants" :key="v.text" :value="v.text">{{ v.text }}</option>
              <option value="__custom__">Outro (digitar)...</option>
            </select>
            <input
              v-if="clusterState[c.id].useCustom"
              type="text"
              placeholder="valor final..."
              v-model="clusterState[c.id].customCanonical"
              @input="markClusterTouched(c.id)"
            >
          </div>

          <div class="action-row">
            <label>
              <input type="radio" :name="`acao-cluster-${titulo}-${c.id}`" value="merge" v-model="clusterState[c.id].action" @change="markClusterTouched(c.id)">
              Unificar (é o mesmo valor)
            </label>
            <label>
              <input type="radio" :name="`acao-cluster-${titulo}-${c.id}`" value="ignore" v-model="clusterState[c.id].action" @change="markClusterTouched(c.id)">
              Manter separados
            </label>
          </div>
        </div>
      </div>
    </div>

    <div class="field" v-if="mostrarOcr">
      <label>Print da lista (opcional)</label>
      <div class="field inline">
        <input type="file" accept="image/*" @change="imageFile = $event.target.files[0] || null">
        <button type="button" class="secondary" :disabled="ocrLoading" @click="onExtractOcr">
          {{ ocrLoading ? "Extraindo..." : "Extrair nomes do print" }}
        </button>
      </div>
      <div v-if="ocrError" class="error-msg">{{ ocrError }}</div>
    </div>

    <div class="field">
      <label>{{ rotuloLista }}</label>
      <textarea
        rows="5"
        :placeholder="placeholder"
        :value="registryText"
        @input="onTextareaInput"
      ></textarea>
    </div>

    <button type="button" :disabled="loading" @click="emit('compare')">{{ loading ? "Comparando..." : "Comparar" }}</button>

    <div class="toolbar" v-if="suggestions.length">
      <div class="bulk-actions">
        <button type="button" class="secondary small" @click="aplicarTodasSugestoes">Aplicar todas as sugestões</button>
        <button type="button" class="secondary small" @click="naoAlterarNenhuma">Não alterar nenhuma</button>
        <span class="shortcut-hint"><kbd>Shift</kbd>+<kbd>A</kbd> aplicar tudo · <kbd>Shift</kbd>+<kbd>I</kbd> não alterar (com o mouse sobre a lista)</span>
      </div>
    </div>

    <div class="clusters-grid">
      <p v-if="!registry.length" class="hint">Cole a lista acima (ou extraia de um print) e clique em "Comparar" para ver as divergências.</p>
      <p v-else-if="suggestions.length === 0">Nenhuma divergência encontrada — todos os valores da planilha batem com a lista.</p>

      <div
        v-for="s in suggestions"
        :key="s.norm"
        class="cluster-card"
        :class="{ 'is-touched': state[s.norm] && state[s.norm].action === 'aplicar' }"
      >
        <div class="cluster-header">
          <span v-if="s.score" class="badge badge-confidence score-mid">{{ s.score.toFixed(1) }}%</span>
          <span class="badge reason">{{ s.count }}x na planilha</span>
          <span v-if="s.remembered_action" class="badge badge-remembered">decisão lembrada</span>
          <span v-if="!s.suggested_official" class="badge conflict">sem correspondente na lista</span>
        </div>

        <div class="variants-col">
          <div class="variant-row">
            <span class="variant-text">"{{ s.text }}"</span>
            <span class="variant-counts">Linha{{ s.rows && s.rows.length > 1 ? "s" : "" }} {{ formatRowList(s.rows) }}</span>
          </div>
          <div class="variant-row" v-if="s.suggested_official">
            <span class="variant-text">→ sugestão da lista: <b>{{ s.suggested_official }}</b></span>
          </div>
        </div>

        <div class="decision-col" v-if="state[s.norm]">
          <div class="action-row">
            <label>
              <input type="radio" :name="`acao-${titulo}-${s.norm}`" value="aplicar" v-model="state[s.norm].action" @change="marcarTocado(s.norm)">
              Aplicar
            </label>
            <label>
              <input type="radio" :name="`acao-${titulo}-${s.norm}`" value="manter" v-model="state[s.norm].action" @change="marcarTocado(s.norm)">
              Não alterar
            </label>
          </div>

          <div class="canonical-row" v-if="state[s.norm].action === 'aplicar'">
            <label>Valor final:</label>
            <select v-model="state[s.norm].selected" @change="marcarTocado(s.norm)">
              <option value="">(escolha um valor)</option>
              <option v-for="name in registry" :key="name" :value="name">{{ name }}</option>
              <option value="__custom__">Outro (digitar)...</option>
            </select>
            <input
              v-if="state[s.norm].selected === '__custom__'"
              type="text"
              placeholder="valor final..."
              v-model="state[s.norm].custom"
              @input="marcarTocado(s.norm)"
            >
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
