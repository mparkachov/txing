import type { AppRoute } from './app-route'

export type RouteDetailPanelOpenState = {
  isTownPanelOpen: boolean
  isRigPanelOpen: boolean
}

export const shouldRenderRouteCatalogPanel = ({
  thingKind,
  reportedRedcon,
}: {
  thingKind: string | null | undefined
  reportedRedcon: number | null
}): boolean => (thingKind === 'townType' || thingKind === 'rigType') && reportedRedcon === 1

export const getRouteDetailPanelOpenState = (
  route: AppRoute,
): RouteDetailPanelOpenState => ({
  isTownPanelOpen: route.kind === 'town',
  isRigPanelOpen: route.kind === 'rig',
})

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
