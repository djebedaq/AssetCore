import type { PermissionCode, UserSession } from './types'

let authenticatedUser: UserSession | null = null

export function storedUser(): UserSession | null {
  return authenticatedUser
}

export function setSessionUser(user: UserSession): void {
  authenticatedUser = user
}

export function clearSessionUser(): void {
  authenticatedUser = null
}

export function hasPermission(...permissions: PermissionCode[]): boolean {
  const granted = storedUser()?.permissions || []
  return permissions.every((permission) => granted.includes(permission))
}

export function canEditRequestDraft(requestedById: number | null | undefined): boolean {
  const user = storedUser()
  return hasPermission('requests.create') && !!user && (
    (requestedById != null && user.id === requestedById) || user.role === 'administrator'
  )
}
