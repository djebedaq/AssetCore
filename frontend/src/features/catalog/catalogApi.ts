import { api } from '../../api'
import type {
  AssemblyDetails,
  CatalogPart,
  CatalogRepairKit,
  HotspotUpdate,
  HotspotUpdateResult,
  MachineCatalog,
  PositionMappingCoverage,
  PositionHotspot,
} from './catalogTypes'

export const catalogApi = {
  machine(machineId: number) {
    return api<MachineCatalog>(`/catalog/v2/machines/${machineId}`)
  },
  assembly(machineId: number, sourceId: string) {
    return api<AssemblyDetails>(
      `/catalog/v2/assemblies/${encodeURIComponent(sourceId)}?machine_id=${machineId}`,
    )
  },
  search(machineId: number, query: string, sourceId?: string) {
    const params = new URLSearchParams({ machine_id: String(machineId), q: query })
    if (sourceId) params.set('source_id', sourceId)
    return api<CatalogPart[]>(`/catalog/v2/search?${params}`)
  },
  hotspots(machineId: number, diagramId: number, verifiedOnly = true) {
    return api<PositionHotspot[]>(
      `/catalog/v2/diagrams/${diagramId}/hotspots?machine_id=${machineId}&verified_only=${verifiedOnly}`,
    )
  },
  updateHotspot(hotspotId: number, payload: HotspotUpdate) {
    return api<HotspotUpdateResult>(`/catalog/v2/hotspots/${hotspotId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  mappingCoverage() {
    return api<PositionMappingCoverage>('/catalog/v2/position-mapping/coverage')
  },
  repairKits(machineId: number, sourceId?: string) {
    const params = new URLSearchParams({ machine_id: String(machineId) })
    if (sourceId) params.set('source_id', sourceId)
    return api<CatalogRepairKit[]>(`/catalog/v2/repair-kits?${params}`)
  },
}
