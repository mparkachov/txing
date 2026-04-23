import type { AppRoute } from './app-route'

export type RouteDetailPanelOpenState = {
  isTownPanelOpen: boolean
  isRigPanelOpen: boolean
}

export type DeviceDetailPanelOpenState = {
  isBotPanelOpen: boolean
  isBoardVideoExpanded: boolean
}

export const getRouteDetailPanelOpenState = (
  route: AppRoute,
): RouteDetailPanelOpenState => ({
  isTownPanelOpen: route.kind === 'town',
  isRigPanelOpen: route.kind === 'rig',
})

export const getAutoOpenDeviceDetailPanelState = ({
  hasActiveSession,
  nextRedcon,
  previousRedcon,
  route,
}: {
  hasActiveSession: boolean
  nextRedcon: number | null
  previousRedcon: number | null
  route: AppRoute
}): DeviceDetailPanelOpenState | null => {
  if (
    route.kind !== 'device' ||
    !hasActiveSession ||
    previousRedcon === 1 ||
    nextRedcon !== 1
  ) {
    return null
  }

  return {
    isBotPanelOpen: true,
    isBoardVideoExpanded: true,
  }
}

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
