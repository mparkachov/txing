export type AppRoute =
  | {
      kind: 'root'
    }
  | {
      kind: 'town'
      town: string
    }
  | {
      kind: 'rig'
      town: string
      rig: string
    }
  | {
      kind: 'device'
      town: string
      rig: string
      device: string
    }
  | {
      kind: 'device_video'
      town: string
      rig: string
      device: string
    }
  | {
      kind: 'not_found'
      pathname: string
    }

const normalizePathname = (pathname: string): string => {
  if (!pathname || pathname === '/') {
    return '/'
  }

  const normalized = pathname.replace(/\/{2,}/g, '/').replace(/\/+$/, '')
  return normalized || '/'
}

const decodeSegment = (segment: string): string | null => {
  if (!segment) {
    return null
  }

  try {
    return decodeURIComponent(segment)
  } catch {
    return null
  }
}

const encodeSegment = (segment: string): string => encodeURIComponent(segment)

export const parseAppRoute = (pathname: string): AppRoute => {
  const normalizedPathname = normalizePathname(pathname)

  if (normalizedPathname === '/') {
    return { kind: 'root' }
  }

  const rawSegments = normalizedPathname.split('/').filter((segment) => segment.length > 0)
  if (rawSegments[0] === 'video') {
    return {
      kind: 'not_found',
      pathname: normalizedPathname,
    }
  }
  const segments = rawSegments.map(decodeSegment)
  if (segments.some((segment) => segment === null)) {
    return {
      kind: 'not_found',
      pathname: normalizedPathname,
    }
  }

  const [town, rig, device, extraSegment, unexpectedSegment] = segments
  if (!town) {
    return {
      kind: 'not_found',
      pathname: normalizedPathname,
    }
  }

  if (unexpectedSegment) {
    return {
      kind: 'not_found',
      pathname: normalizedPathname,
    }
  }

  if (!rig) {
    return { kind: 'town', town }
  }

  if (!device) {
    return { kind: 'rig', town, rig }
  }

  if (extraSegment === 'video') {
    return { kind: 'device_video', town, rig, device }
  }

  if (extraSegment) {
    return {
      kind: 'not_found',
      pathname: normalizedPathname,
    }
  }

  return { kind: 'device', town, rig, device }
}

export const buildTownPath = (town: string): string => `/${encodeSegment(town)}`

export const buildRigPath = (town: string, rig: string): string =>
  `${buildTownPath(town)}/${encodeSegment(rig)}`

export const buildDevicePath = (town: string, rig: string, device: string): string =>
  `${buildRigPath(town, rig)}/${encodeSegment(device)}`

export const buildDeviceVideoPath = (
  town: string,
  rig: string,
  device: string,
): string => `${buildDevicePath(town, rig, device)}/video`

export const describeRouteTown = (route: AppRoute): string | null => {
  if (
    route.kind === 'town' ||
    route.kind === 'rig' ||
    route.kind === 'device' ||
    route.kind === 'device_video'
  ) {
    return route.town
  }

  return null
}
