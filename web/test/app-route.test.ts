import { describe, expect, test } from 'bun:test'
import {
  buildDevicePath,
  buildDeviceVideoPath,
  buildRigPath,
  buildTownPath,
  parseAppRoute,
} from '../src/app-route'

describe('app route helpers', () => {
  test('parses root route and rejects removed legacy video route', () => {
    expect(parseAppRoute('/')).toEqual({ kind: 'root' })
    expect(parseAppRoute('/video')).toEqual({ kind: 'not_found', pathname: '/video' })
    expect(parseAppRoute('/video/')).toEqual({ kind: 'not_found', pathname: '/video' })
  })

  test('parses town, rig, device, and device video routes with trailing slashes', () => {
    expect(parseAppRoute('/town')).toEqual({ kind: 'town', town: 'town' })
    expect(parseAppRoute('/town/rig/')).toEqual({
      kind: 'rig',
      town: 'town',
      rig: 'rig',
    })
    expect(parseAppRoute('/town/rig/unit-bvrh10/')).toEqual({
      kind: 'device',
      town: 'town',
      rig: 'rig',
      device: 'unit-bvrh10',
    })
    expect(parseAppRoute('/town/rig/unit-bvrh10/video/')).toEqual({
      kind: 'device_video',
      town: 'town',
      rig: 'rig',
      device: 'unit-bvrh10',
    })
  })

  test('marks unsupported extra segments as not found', () => {
    expect(parseAppRoute('/town/rig/unit-bvrh10/extra')).toEqual({
      kind: 'not_found',
      pathname: '/town/rig/unit-bvrh10/extra',
    })
  })

  test('builds encoded compact drilldown paths', () => {
    expect(buildTownPath('town name')).toBe('/town%20name')
    expect(buildRigPath('town', 'rig alpha')).toBe('/town/rig%20alpha')
    expect(buildDevicePath('town', 'rig', 'unit-a7k2p9')).toBe('/town/rig/unit-a7k2p9')
    expect(buildDeviceVideoPath('town', 'rig', 'unit-a7k2p9')).toBe(
      '/town/rig/unit-a7k2p9/video',
    )
  })
})
