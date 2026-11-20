const BASE = '/api'

async function call(method, path, body) {
  const r = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  rooms: () => call('GET', '/rooms'),
  imageUrl: (roomId) => `${BASE}/rooms/${roomId}/image`,
  createSession: (roomId) => call('POST', '/sessions', { roomId }),
  putSpace: (sid, space) => call('PUT', `/sessions/${sid}/space`, space),
  validate: (sid, poses, profile = 'preference') => call('POST', `/sessions/${sid}/validate`, { poses, profile }),
  layouts: (sid) => call('POST', `/sessions/${sid}/layouts`),
  guide: (sid, poses) => call('POST', `/sessions/${sid}/guide`, { poses }),
  getSession: (sid) => call('GET', `/sessions/${sid}`),
  analyzePhoto: (sid, mode = 'auto') => call('POST', `/sessions/${sid}/draft/photo?mode=${mode}`),
  questions: (sid) => call('GET', `/sessions/${sid}/questions`),
  answer: (sid, cues, answers) => call('POST', `/sessions/${sid}/answers`, { cues, answers }),
}

export const LABEL = {
  bed: '침대', desk: '책상', chair: '의자', storage: '수납장',
  table: '테이블', sofa: '소파', wardrobe: '옷장', fridge: '냉장고',
}
