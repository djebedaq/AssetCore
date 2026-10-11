import type { Preview } from './guidedTypes'

// Extraction boxes are in unrotated PDF points; preview images use page rotation.
// Missing/invalid evidence must never produce a guessed highlight.
export function evidenceRegion(preview: Preview, box?: number[]) {
  const { width, height, rotation_matrix: matrix } = preview.page_geometry || {}
  if (!width || !height || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0
    || !box || box.length !== 4 || box.some(value => !Number.isFinite(value))
    || !matrix || matrix.length !== 6 || matrix.some(value => !Number.isFinite(value))
    || box[2] <= box[0] || box[3] <= box[1]) return null
  const [a, b, c, d, e, f] = matrix
  const points = [[box[0], box[1]], [box[2], box[1]], [box[0], box[3]], [box[2], box[3]]]
    .map(([x, y]) => [a * x + c * y + e, b * x + d * y + f])
  const left = Math.min(...points.map(p => p[0])) / width, top = Math.min(...points.map(p => p[1])) / height
  const right = Math.max(...points.map(p => p[0])) / width, bottom = Math.max(...points.map(p => p[1])) / height
  if (left < 0 || top < 0 || right > 1 || bottom > 1 || right <= left || bottom <= top) return null
  return { left: `${left * 100}%`, top: `${top * 100}%`, width: `${(right - left) * 100}%`, height: `${(bottom - top) * 100}%` }
}
