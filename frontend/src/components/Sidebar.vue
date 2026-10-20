<script setup>
defineProps({
  counts: { type: Object, required: true },
});
</script>

<template>
  <nav class="sidebar">
    <div class="nav-group">
      <span class="nav-group-label">Configuração</span>
      <a href="#upload-section" class="nav-item">1. Planilhas</a>
      <a href="#sensibilidade-section" class="nav-item">2. Sensibilidade</a>
    </div>
    <div class="nav-group">
      <span class="nav-group-label">Revisão de nomes</span>
      <a href="#clusters-section" class="nav-item">3. Clientes <span class="nav-count">{{ counts.clusters || "" }}</span></a>
      <a href="#clientes-duplicatas-section" class="nav-item">4. Duplicatas em Clientes <span class="nav-count">{{ counts.clientesDuplicatas || "" }}</span></a>
      <a href="#cliente-parte-section" class="nav-item">5. Cliente × Parte <span class="nav-count">{{ counts.clienteParte || "" }}</span></a>
      <a href="#court-judge-section" class="nav-item">6. Tribunal/Juiz <span class="nav-count">{{ counts.courtJudge || "" }}</span></a>
    </div>
    <div class="nav-group">
      <span class="nav-group-label">Validação externa</span>
      <a href="#financeiro-section" class="nav-item">7. Financeiro <span class="nav-count">{{ counts.financeiro || "" }}</span></a>
      <a href="#advbox-section" class="nav-item">8. ADVBOX <span class="nav-count">{{ counts.advbox || "" }}</span></a>
      <a href="#nome-validacao-section" class="nav-item">9. Conferir nomes <span class="nav-count">{{ counts.nomeValidacao || "" }}</span></a>
      <a href="#responsaveis-section" class="nav-item">10. Responsáveis <span class="nav-count">{{ counts.resp || "" }}</span></a>
      <a href="#tipo-acao-section" class="nav-item">11. Tipos de Ação <span class="nav-count">{{ counts.tipoAcao || "" }}</span></a>
      <a href="#grupo-acao-section" class="nav-item">12. Grupos de Ação <span class="nav-count">{{ counts.grupoAcao || "" }}</span></a>
    </div>
    <div class="nav-group">
      <a href="#apply-section" class="nav-item nav-item-primary">13. Aplicar</a>
    </div>
  </nav>
</template>
