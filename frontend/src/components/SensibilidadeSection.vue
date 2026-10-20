<script setup>
defineProps({
  threshold: { type: Number, required: true },
  stats: { type: Object, default: null },
  clienteParteCount: { type: Number, default: 0 },
  courtJudgeCount: { type: Number, default: 0 },
  advboxCount: { type: Number, default: 0 },
  temAdvbox: { type: Boolean, default: false },
  respCount: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(["update:threshold", "reanalyze"]);

function onInput(e) {
  emit("update:threshold", Number(e.target.value));
}
</script>

<template>
  <section id="sensibilidade-section" class="card">
    <h2>2. Ajuste da sensibilidade</h2>
    <div class="field inline">
      <label>Limiar de similaridade (nomes parecidos, sem relação de abreviação): <b>{{ threshold }}</b></label>
      <input type="range" min="70" max="98" :value="threshold" @input="onInput">
      <button @click="emit('reanalyze')" :disabled="loading">{{ loading ? "Analisando..." : "Reanalisar" }}</button>
    </div>
    <div class="stats-strip" v-if="stats">
      <div class="stat-tile">Grupos de homônimos: <b>{{ stats.total_clusters }}</b></div>
      <div class="stat-tile warn" v-if="stats.cpf_conflicts">Conflitos de CPF: <b>{{ stats.cpf_conflicts }}</b></div>
      <div class="stat-tile info" v-if="clienteParteCount">Cliente × Parte: <b>{{ clienteParteCount }}</b></div>
      <div class="stat-tile info" v-if="courtJudgeCount">Tribunal/Juiz: <b>{{ courtJudgeCount }}</b></div>
      <div class="stat-tile advbox" v-if="temAdvbox">Só no ADVBOX / conflitos: <b>{{ advboxCount }}</b></div>
      <div class="stat-tile info" v-if="respCount">Responsáveis: <b>{{ respCount }}</b></div>
    </div>
    <div v-else class="hint">Analisando...</div>
  </section>
</template>
