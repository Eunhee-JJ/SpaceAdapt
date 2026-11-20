<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, LABEL } from './api'
import FloorPlan from './components/FloorPlan.vue'
import ResultPanel from './components/ResultPanel.vue'

const clone = (o) => JSON.parse(JSON.stringify(o))

// select → edit (correct the current layout) → [questions: Sunday] → compare → guide
const step = ref('select')
const rooms = ref([])
const err = ref('')
const busy = ref(false)

const sid = ref(null)
const space = ref(null)
const poses = ref({})
const check = ref(null) // {validation, score} for the plan on screen
const selected = ref(null)

const layouts = ref(null)
const tab = ref('preference')
const steps = ref([])

const TABS = [
  { k: 'baseline', label: '현재' },
  { k: 'preference', label: 'A 선호 우선' },
  { k: 'minimal_move', label: 'B 이동 최소' },
]

onMounted(async () => {
  try { rooms.value = await api.rooms() } catch (e) { err.value = '백엔드에 연결할 수 없습니다. (uvicorn 실행 확인)' }
})

async function run(fn) {
  busy.value = true; err.value = ''
  try { await fn() } catch (e) { err.value = String(e.message || e) } finally { busy.value = false }
}

function openRoom(id) {
  run(async () => {
    const s = await api.createSession(id)
    sid.value = s.id; space.value = s.space
    poses.value = clone(s.space.baselineLayout.poses)
    check.value = await api.validate(s.id, poses.value)
    step.value = 'edit'
  })
}

// live re-validation (NFR-02): debounce edits by 300ms
let timer
watch(poses, (p) => {
  if (!sid.value) return
  clearTimeout(timer)
  const profile = step.value === 'compare' && tab.value !== 'baseline' ? tab.value : 'preference'
  timer = setTimeout(async () => {
    const t = performance.now()
    check.value = await api.validate(sid.value, p, profile)
    check.value.ms = Math.round(performance.now() - t)
  }, 300)
}, { deep: true, immediate: false })

function rotate(deg) {
  if (!selected.value) return
  const p = poses.value[selected.value]
  poses.value = { ...poses.value, [selected.value]: { ...p, rotation: (((p.rotation || 0) + deg) % 360 + 360) % 360 } }
}

const selectedItem = computed(() => space.value?.furniture.find((f) => f.id === selected.value))

function makeLayouts() {
  run(async () => {
    const corrected = clone(space.value)
    corrected.baselineLayout.poses = clone(poses.value)
    await api.putSpace(sid.value, corrected)
    space.value = corrected
    layouts.value = await api.layouts(sid.value)
    step.value = 'compare'
    showTab('preference')
  })
}

function showTab(k) {
  tab.value = k
  selected.value = null
  const l = layouts.value[k]
  if (!l) return
  poses.value = clone(l.poses)
  check.value = { validation: l.validation, score: l.score }
}

function openGuide() {
  run(async () => {
    steps.value = (await api.guide(sid.value, poses.value)).steps
    step.value = 'guide'
  })
}

function name(id) {
  const f = space.value.furniture.find((x) => x.id === id)
  return f ? LABEL[f.type] || f.type : id
}
</script>

<template>
  <header>
    <b>SpaceAdapt</b>
    <span v-if="step !== 'select'" class="crumb">{{ { edit: '현재 배치 보정', compare: '배치안 비교', guide: '이동 가이드' }[step] }}</span>
  </header>
  <p v-if="err" class="err">{{ err }}</p>

  <!-- 방 선택 -->
  <section v-if="step === 'select'" class="pad">
    <h2>어떤 방을 바꿔 볼까요?</h2>
    <p class="muted">데모용 합성 방입니다. 실제 사용자는 사진을 올리거나 직접 입력합니다.</p>
    <button v-for="r in rooms" :key="r.id" class="room" :disabled="busy" @click="openRoom(r.id)">
      <img v-if="r.hasImage" :src="api.imageUrl(r.id)" alt="" />
      <span>{{ r.title }}</span>
    </button>
  </section>

  <!-- 현재 배치 보정 -->
  <section v-if="step === 'edit' && space" class="pad">
    <h2>지금 방 모습이 맞나요?</h2>
    <p class="muted">가구를 끌어서 실제 위치로 맞추세요. 탭하면 선택, 아래 버튼으로 회전합니다.</p>
    <FloorPlan v-model:poses="poses" v-model:selected="selected" :space="space" :result="check?.validation" editable />
    <div class="tools">
      <span>{{ selectedItem ? (LABEL[selectedItem.type] || selectedItem.type) : '가구를 탭하세요' }}</span>
      <button class="mini" :disabled="!selected" @click="rotate(-15)">⟲ 15°</button>
      <button class="mini" :disabled="!selected" @click="rotate(15)">⟳ 15°</button>
      <button class="mini" :disabled="!selected" @click="rotate(90)">⟳ 90°</button>
    </div>
    <ResultPanel v-if="check" :validation="check.validation" />
    <button class="btn" :disabled="busy" @click="makeLayouts">{{ busy ? '배치안 계산 중…' : '배치안 만들기' }}</button>
  </section>

  <!-- 배치안 비교 -->
  <section v-if="step === 'compare' && layouts" class="pad">
    <div class="tabs">
      <button v-for="t in TABS" :key="t.k" :class="{ on: tab === t.k }" @click="showTab(t.k)">
        {{ t.label }}<small v-if="layouts[t.k]">{{ layouts[t.k].score.total }}점</small>
      </button>
    </div>
    <p v-if="!layouts[tab]" class="muted">이 조건에서는 제약을 모두 만족하는 배치를 찾지 못했습니다.</p>
    <template v-else>
      <FloorPlan v-model:poses="poses" v-model:selected="selected" :space="space" :result="check?.validation"
                 :editable="tab !== 'baseline'" />
      <div v-if="tab !== 'baseline'" class="tools">
        <span>{{ selectedItem ? (LABEL[selectedItem.type] || selectedItem.type) : '끌어서 직접 조정할 수 있어요' }}</span>
        <button class="mini" :disabled="!selected" @click="rotate(90)">⟳ 90°</button>
      </div>
      <ResultPanel v-if="check" :validation="check.validation" :score="check.score" />
      <p v-if="check?.ms" class="muted small">재검증 {{ check.ms }}ms</p>
      <button v-if="tab !== 'baseline'" class="btn" :disabled="busy || check?.validation.hard.length" @click="openGuide">
        이 배치로 이동 순서 보기
      </button>
    </template>
  </section>

  <!-- 이동 가이드 -->
  <section v-if="step === 'guide'" class="pad">
    <h2>이렇게 옮기세요</h2>
    <ol class="steps">
      <li v-for="s in steps" :key="s.order" :class="{ temp: s.temporary }">
        <b>{{ s.order }}. {{ name(s.id) }}</b>
        <p>{{ s.text }}</p>
        <small v-for="c in s.cautions || []" :key="c">· {{ c }}</small>
      </li>
      <li v-if="!steps.length">옮길 가구가 없습니다.</li>
    </ol>
    <button class="btn ghost" @click="step = 'compare'">배치안으로 돌아가기</button>
  </section>
</template>

<style scoped>
header { position: sticky; top: 0; z-index: 5; display: flex; gap: 10px; align-items: baseline;
  padding: 14px 16px; background: var(--navy); color: #fff; }
.crumb { font-size: 13px; color: #a9bcd6; }
.pad { padding: 16px; display: grid; gap: 12px; }
h2 { margin: 0; font-size: 20px; color: var(--navy); }
.muted { margin: 0; color: var(--muted); font-size: 14px; } .small { font-size: 12px; }
.err { margin: 0; padding: 10px 16px; background: var(--bad-soft); color: var(--bad); font-size: 14px; }
.room { display: grid; gap: 6px; padding: 8px; background: var(--card); text-align: left; font-weight: 700; color: var(--navy); }
.room img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 8px; }
.tools { display: flex; gap: 6px; align-items: center; font-size: 14px; }
.tools span { flex: 1; color: var(--muted); }
.mini { background: var(--card); color: var(--navy); padding: 8px 10px; font-weight: 700; }
.mini:disabled { opacity: .4; }
.tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.tabs button { background: var(--card); color: var(--navy); padding: 10px 4px; font-weight: 700; font-size: 14px; }
.tabs button small { display: block; font-weight: 500; color: var(--muted); font-size: 12px; }
.tabs button.on { background: var(--accent); color: #fff; } .tabs button.on small { color: #fff; }
.steps { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.steps li { background: var(--card); border-radius: 10px; padding: 10px 12px; }
.steps li.temp { background: var(--warn-soft); }
.steps p { margin: 4px 0; } .steps small { display: block; color: var(--muted); }
</style>
