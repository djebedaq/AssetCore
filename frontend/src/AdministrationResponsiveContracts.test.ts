import { describe, expect, it } from 'vitest'
import styles from './styles.css?raw'

describe('administration tablet-width responsive contract', () => {
  const tabletRule = styles.match(/@media\(max-width:1023px\)\{[^\n]+/)?.[0] || ''

  it('stacks only the administration layouts that exceed the compact desktop content width', () => {
    expect(tabletRule).toContain('.users-filters{grid-template-columns:1fr}')
    expect(tabletRule).toContain('.admin-grid{grid-template-columns:1fr}')
    expect(tabletRule).toContain('.admin-list>div{grid-template-columns:minmax(0,1fr) auto}')
    expect(tabletRule).toContain('.admin-list>div>.link{grid-column:1/-1;justify-self:start}')
    expect(tabletRule).toContain('.settings-list>div{gap:12px}')
  })

  it('keeps wide Users table content locally scrollable without masking page overflow', () => {
    expect(styles).toContain('.table-card{overflow:auto}')
    expect(styles).toContain('.users-table table{min-width:880px}')
    expect(styles).not.toMatch(/(?:html|body)\{[^}]*overflow-x:hidden/)
  })
})
