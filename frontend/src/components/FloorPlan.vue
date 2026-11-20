<script setup>
// 2D floor plan. Coordinates are cm (y down); the stage scale converts to px.
// Furniture groups use Konva's clockwise rotation, matching the backend model.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { LABEL } from '../api'

const props = defineProps({
  space: { type: Object, required: true },
  poses: { type: Object, required: true },
  result: { type: Object, default: null }, // validate() output
  editable: { type: Boolean, default: false },
  selected: { type: String, default: null },
  showZones: { type: Boolean, default: true },
})
const emit = defineEmits(['update:poses', 'update:selected'])

const PAD = 12
const wrap = ref(null)
const width = ref(320)
let ro
onMounted(() => {
  ro = new ResizeObserver(([e]) => (width.value = e.contentRect.width))
  ro.observe(wrap.value)
})
onBeforeUnmount(() => ro && ro.disconnect())

const pts = computed(() => props.space.room.polygon)
const bounds = computed(() => {
  const xs = pts.value.map((p) => p[0]), ys = pts.value.map((p) => p[1])
  return { minx: Math.min(...xs), miny: Math.min(...ys), maxx: Math.max(...xs), maxy: Math.max(...ys) }
})
const scale = computed(() => width.value / (bounds.value.maxx - bounds.value.minx + PAD * 2))
const stage = computed(() => ({
  width: width.value,
  height: (bounds.value.maxy - bounds.value.miny + PAD * 2) * scale.value,
  scaleX: scale.value, scaleY: scale.value,
}))
const origin = computed(() => ({ x: PAD - bounds.value.minx, y: PAD - bounds.value.miny }))
const flat = (ring) => ring.flat()

function openingSegment(op) {
  const p = pts.value, a = p[op.wall], b = p[(op.wall + 1) % p.length]
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]), u = [(b[0] - a[0]) / L, (b[1] - a[1]) / L]
  const s = [a[0] + u[0] * op.offset, a[1] + u[1] * op.offset]
  return [s[0], s[1], s[0] + u[0] * op.width, s[1] + u[1] * op.width]
}
const windows = computed(() => props.space.room.openings.filter((o) => o.type === 'window').map(openingSegment))
const doors = computed(() => props.space.room.openings.filter((o) => o.type === 'door').map(openingSegment))
const swings = computed(() => Object.values(props.result?.doorSwings || {}).flat())

const ZONE_COLOR = { sleep: '#3d5a80', work: '#0f9d8a', hobby: '#65a30d' }
const ZONE_NAME = { sleep: '수면', work: '업무', hobby: '취미' }
const zonesOn = ref(props.showZones)
const zones = computed(() => {
  if (!zonesOn.value || !props.result) return []
  return Object.entries(props.result.zones || {}).flatMap(([k, rings]) => rings.map((r) => ({ k, r })))
})
const zoneLabels = computed(() => zones.value.map(({ k, r }) => {
  const xs = r.map((p) => p[0]), ys = r.map((p) => p[1])
  const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys)
  // label in the zone's bottom-left corner so it does not sit on top of the furniture name
  return { k, x: minx + 4, y: maxy - 20, w: maxx - minx }
}))
const interference = computed(() => (zonesOn.value && props.result?.interference) || [])
const interferenceM2 = computed(() => ((props.result?.metrics?.interferenceArea || 0) / 10000).toFixed(2))
const legend = computed(() => {
  const present = new Set(Object.entries(props.result?.zones || {}).filter(([, r]) => r.length).map(([k]) => k))
  return ['sleep', 'work', 'hobby'].filter((k) => present.has(k))
})
const hardRings = computed(() => (props.result?.hard || []).flatMap((v) => v.geometry))
const softRings = computed(() => (props.result?.soft || []).flatMap((v) => v.geometry))
const flagged = computed(() => new Set((props.result?.hard || []).map((v) => v.objects[0])))

const items = computed(() =>
  props.space.furniture
    .filter((f) => props.poses[f.id])
    .map((f) => {
      const c = f.clearance || {}, w = f.width, d = f.depth
      const cl = []
      if (c.front) cl.push({ x: -w / 2, y: d / 2, width: w, height: c.front })
      if (c.back) cl.push({ x: -w / 2, y: -d / 2 - c.back, width: w, height: c.back })
      if (c.left) cl.push({ x: -w / 2 - c.left, y: -d / 2, width: c.left, height: d })
      if (c.right) cl.push({ x: w / 2, y: -d / 2, width: c.right, height: d })
      return { f, pose: props.poses[f.id], cl }
    }),
)

function onDragEnd(id, e) {
  const n = e.target
  const snap = (v) => Math.round(v / 5) * 5
  const next = { ...props.poses, [id]: { ...props.poses[id], x: snap(n.x()), y: snap(n.y()) } }
  n.position({ x: next[id].x, y: next[id].y })
  emit('update:poses', next)
}
function select(id) {
  emit('update:selected', props.selected === id ? null : id)
}
</script>

<template>
  <div ref="wrap" class="plan">
    <v-stage :config="stage">
      <v-layer>
        <v-group :config="origin">
          <v-line :config="{ points: flat(pts), closed: true, fill: '#fafbfd', stroke: '#1f2a44', strokeWidth: 4 }" />
          <v-line v-for="(z, i) in zones" :key="'z' + i"
            :config="{ points: flat(z.r), closed: true, fill: ZONE_COLOR[z.k], opacity: 0.16, listening: false }" />
          <v-line v-for="(r, i) in interference" :key="'if' + i"
            :config="{ points: flat(r), closed: true, fill: '#7c3aed', opacity: 0.22, stroke: '#7c3aed',
                       strokeWidth: 1.5, dash: [5, 4], listening: false }" />
          <v-line v-for="(fx, i) in space.room.fixtures" :key="'fx' + i"
            :config="{ points: flat(fx.polygon), closed: true, fill: '#d9dee7', stroke: '#b8c0cc', strokeWidth: 1 }" />
          <v-line v-for="(s, i) in windows" :key="'w' + i" :config="{ points: s, stroke: '#7fb3d5', strokeWidth: 6 }" />
          <v-line v-for="(s, i) in doors" :key="'d' + i" :config="{ points: s, stroke: '#fafbfd', strokeWidth: 6 }" />
          <v-line v-for="(r, i) in swings" :key="'sw' + i"
            :config="{ points: flat(r), closed: true, stroke: '#667085', strokeWidth: 1, dash: [4, 4], listening: false }" />

          <v-group v-for="it in items" :key="it.f.id"
            :config="{ x: it.pose.x, y: it.pose.y, rotation: it.pose.rotation || 0,
                       draggable: editable && it.f.movable !== false }"
            @dragend="onDragEnd(it.f.id, $event)" @click="select(it.f.id)" @tap="select(it.f.id)">
            <v-rect v-for="(c, i) in it.cl" :key="i"
              :config="{ ...c, fill: '#667085', opacity: 0.08, stroke: '#98a2b3', strokeWidth: 1, dash: [3, 3] }" />
            <v-rect :config="{ x: -it.f.width / 2, y: -it.f.depth / 2, width: it.f.width, height: it.f.depth,
                               fill: '#fff', cornerRadius: 3,
                               stroke: selected === it.f.id ? '#f26b3a' : flagged.has(it.f.id) ? '#c2410c' : '#3d5a80',
                               strokeWidth: selected === it.f.id ? 4 : 2 }" />
            <v-line :config="{ points: [-it.f.width / 2 + 6, it.f.depth / 2 - 4, it.f.width / 2 - 6, it.f.depth / 2 - 4],
                               stroke: '#3d5a80', strokeWidth: 2, opacity: 0.6 }" />
            <v-text :config="{ text: (LABEL[it.f.type] || it.f.type) + (it.f.movable === false ? ' 🔒' : ''),
                               rotation: -(it.pose.rotation || 0), width: 90, offsetX: 45, offsetY: 7,
                               align: 'center', fontSize: 13, fill: '#1f2a44', listening: false }" />
          </v-group>

          <v-text v-for="(z, i) in zoneLabels" :key="'zl' + i"
            :config="{ x: z.x, y: z.y, text: ZONE_NAME[z.k] + ' 영역', fontSize: 12, fontStyle: 'bold',
                       fill: ZONE_COLOR[z.k], listening: false }" />
          <v-line v-for="(r, i) in softRings" :key="'s' + i"
            :config="{ points: flat(r), closed: true, stroke: '#b7791f', strokeWidth: 2, dash: [6, 3], listening: false }" />
          <v-line v-for="(r, i) in hardRings" :key="'h' + i"
            :config="{ points: flat(r), closed: true, fill: '#c2410c', opacity: 0.35, listening: false }" />
        </v-group>
      </v-layer>
    </v-stage>
    <div class="legend">
      <button class="toggle" :class="{ on: zonesOn }" @click="zonesOn = !zonesOn">활동 영역 {{ zonesOn ? '켜짐' : '꺼짐' }}</button>
      <template v-if="zonesOn">
        <span v-for="k in legend" :key="k"><i :style="{ background: ZONE_COLOR[k], opacity: .45 }" />{{ ZONE_NAME[k] }} 영역</span>
        <span v-if="interference.length"><i class="intf" />겹치는 구간 {{ interferenceM2 }}㎡</span>
      </template>
      <span><i class="use" />가구 사용 공간</span>
      <span><i class="door" />문 열림</span>
      <span><i class="win" />창문</span>
      <span v-if="hardRings.length"><i class="hard" />위반</span>
      <span v-if="softRings.length"><i class="soft" />주의</span>
    </div>
  </div>
</template>

<style scoped>
.plan { width: 100%; touch-action: none; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; margin-top: 8px; font-size: 12px; color: var(--ink); }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend i { display: inline-block; width: 14px; height: 10px; border-radius: 3px; }
.legend .intf { background: #7c3aed; opacity: .4; outline: 1px dashed #7c3aed; }
.legend .use { background: #667085; opacity: .25; outline: 1px dashed #98a2b3; }
.legend .door { border: 1.5px dashed #667085; border-radius: 0 10px 0 0; background: none; }
.legend .win { background: #7fb3d5; height: 4px; }
.legend .hard { background: #c2410c; opacity: .5; }
.legend .soft { border: 1.5px dashed #b7791f; background: none; }
.toggle { background: var(--card); color: var(--muted); padding: 4px 10px; font-size: 12px; font-weight: 700; border-radius: 999px; }
.toggle.on { background: var(--navy); color: #fff; }
</style>
