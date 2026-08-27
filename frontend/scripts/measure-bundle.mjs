import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

// Follow static imports: async page chunks must not be counted as initial JS.
const directory = resolve(process.argv[2] || 'dist')
const manifest = JSON.parse(readFileSync(resolve(directory, '.vite/manifest.json'), 'utf8'))
const initial = new Set()
function visit(key) {
  if (initial.has(key)) return
  initial.add(key)
  for (const dependency of manifest[key].imports || []) visit(dependency)
}
for (const [key, chunk] of Object.entries(manifest)) if (chunk.isEntry) visit(key)
const chunks = Object.entries(manifest).filter(([, chunk]) => chunk.file.endsWith('.js')).map(([key, chunk]) => {
  const content = readFileSync(resolve(directory, chunk.file))
  return { source: key, file: chunk.file, initial: initial.has(key), bytes: content.length, gzip_bytes: gzipSync(content).length }
})
const sum = (items, field) => items.reduce((total, chunk) => total + chunk[field], 0)
console.log(JSON.stringify({
  initial_js_bytes: sum(chunks.filter((chunk) => chunk.initial), 'bytes'),
  initial_js_gzip_bytes: sum(chunks.filter((chunk) => chunk.initial), 'gzip_bytes'),
  total_js_bytes: sum(chunks, 'bytes'),
  largest_js_bytes: Math.max(...chunks.map((chunk) => chunk.bytes)),
  chunks,
}, null, 2))
