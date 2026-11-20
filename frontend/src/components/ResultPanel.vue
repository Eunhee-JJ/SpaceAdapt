<script setup>
defineProps({
  validation: { type: Object, required: true },
  score: { type: Object, default: null },
})
</script>

<template>
  <div class="panel">
    <div v-if="score" class="kpis">
      <div><span>총점</span><b>{{ score.total }}</b></div>
      <div :class="validation.hard.length ? 'bad' : 'ok'"><span>하드 위반</span><b>{{ validation.hard.length }}건</b></div>
      <div><span>이동 가구</span><b>{{ score.movedCount }}개</b></div>
      <div><span>활동 간섭</span><b>{{ (validation.metrics.interferenceArea / 10000).toFixed(2) }}㎡</b></div>
    </div>
    <ul v-if="score && score.goals.length" class="goals">
      <li v-for="g in score.goals" :key="g.label" :class="g.ok ? 'ok' : 'no'">{{ g.ok ? '✓' : '✗' }} {{ g.label }}</li>
    </ul>
    <ul class="viol">
      <li v-for="(v, i) in validation.hard" :key="'h' + i" class="hard">⛔ {{ v.reason }}</li>
      <li v-for="(v, i) in validation.soft" :key="'s' + i" class="soft">⚠ {{ v.reason }}</li>
      <li v-if="!validation.hard.length && !validation.soft.length" class="clean">문·통로·사용 공간 문제가 없습니다.</li>
    </ul>
  </div>
</template>

<style scoped>
.panel { display: grid; gap: 10px; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.kpis div { background: var(--card); border-radius: 10px; padding: 8px 6px; text-align: center; }
.kpis span { display: block; font-size: 11px; color: var(--muted); }
.kpis b { font-size: 16px; color: var(--navy); }
.kpis .bad b { color: var(--bad); } .kpis .ok b { color: var(--ok); }
ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; font-size: 14px; }
.goals li.ok { color: var(--ok); } .goals li.no { color: var(--muted); }
.viol li { padding: 6px 10px; border-radius: 8px; }
.hard { background: var(--bad-soft); color: var(--bad); }
.soft { background: var(--warn-soft); color: var(--warn); }
.clean { background: var(--ok-soft); color: var(--ok); }
</style>
