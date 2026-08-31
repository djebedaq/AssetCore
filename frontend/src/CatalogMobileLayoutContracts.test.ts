import { describe, expect, it } from 'vitest'

import styles from './styles.css?raw'

describe('mobile catalog parts-table containment contract', () => {
  it('contains the wide table in its catalog scroller without clipping the page globally', () => {
    expect(styles).toContain('.catalog-v2-parts{min-width:0}')
    expect(styles).toContain('.catalog-v2-parts>.table-card{min-width:0;contain:layout}')
    expect(styles).toContain('.catalog-v2-search-tools{min-width:0;grid-template-columns:minmax(0,1fr) auto}')
    expect(styles).toContain('.catalog-v2-search-tools .searchbox{min-width:0}')
    expect(styles).toContain('.catalog-v2-parts>.table-card{max-height:520px;overflow:auto}')
    expect(styles).toContain('.catalog-v2-parts table{min-width:760px}')
    expect(styles).not.toMatch(/(?:html|body)\{[^}]*overflow-x:hidden/)
  })
})
