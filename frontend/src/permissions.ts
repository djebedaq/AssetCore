import type { PermissionCode, UserSession } from './types'

export function storedUser(): UserSession | null {
  try {
    return JSON.parse(localStorage.getItem('assetcore_user') || 'null') as UserSession | null
  } catch {
    return null
  }
}

export function hasPermission(...permissions: PermissionCode[]): boolean {
  const granted = storedUser()?.permissions || []
  return permissions.every((permission) => granted.includes(permission))
}
