import type { AppRoute } from './app-route'

export type RouteDetailPanelOpenState = {
  isTownPanelOpen: boolean
  isRigPanelOpen: boolean
}

export const getRouteDetailPanelOpenState = (
  route: AppRoute,
): RouteDetailPanelOpenState => ({
  isTownPanelOpen: route.kind === 'town',
  isRigPanelOpen: route.kind === 'rig',
})

export const shouldAutoOpenDeviceDetailPanel = ({
  hasActiveSession,
  nextRedcon,
  previousRedcon,
  route,
}: {
  hasActiveSession: boolean
  nextRedcon: number | null
  previousRedcon: number | null
  route: AppRoute
}): boolean =>
  route.kind === 'device' &&
  hasActiveSession &&
  previousRedcon !== 1 &&
  nextRedcon === 1

export const formatCatalogDetailLine = (
  shortId: string | null | undefined,
  name: string,
): string => {
  const normalizedName = name.trim()
  if (!shortId) {
    return normalizedName
  }
  return `${shortId}: ${normalizedName}`
}
