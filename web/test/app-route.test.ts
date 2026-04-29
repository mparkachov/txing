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

  test('parses town, rig, device, and device video thing-name routes with trailing slashes', () => {
    expect(parseAppRoute('/town-ab12cd')).toEqual({ kind: 'town', town: 'town-ab12cd' })
    expect(parseAppRoute('/town-ab12cd/rig-ef34gh/')).toEqual({
      kind: 'rig',
      town: 'town-ab12cd',
      rig: 'rig-ef34gh',
    })
    expect(parseAppRoute('/town-ab12cd/rig-ef34gh/unit-bvrh10/')).toEqual({
      kind: 'device',
      town: 'town-ab12cd',
      rig: 'rig-ef34gh',
      device: 'unit-bvrh10',
    })
    expect(parseAppRoute('/town-ab12cd/rig-ef34gh/unit-bvrh10/video/')).toEqual({
      kind: 'device_video',
      town: 'town-ab12cd',
      rig: 'rig-ef34gh',
      device: 'unit-bvrh10',
    })
  })

  test('marks unsupported extra segments as not found', () => {
    expect(parseAppRoute('/town-ab12cd/rig-ef34gh/unit-bvrh10/extra')).toEqual({
      kind: 'not_found',
      pathname: '/town-ab12cd/rig-ef34gh/unit-bvrh10/extra',
    })
  })

  test('builds encoded compact drilldown paths from thing names', () => {
    expect(buildTownPath('town-ab12cd')).toBe('/town-ab12cd')
    expect(buildRigPath('town-ab12cd', 'rig alpha')).toBe('/town-ab12cd/rig%20alpha')
    expect(buildDevicePath('town-ab12cd', 'rig-ef34gh', 'unit-a7k2p9')).toBe(
      '/town-ab12cd/rig-ef34gh/unit-a7k2p9',
    )
    expect(buildDeviceVideoPath('town-ab12cd', 'rig-ef34gh', 'unit-a7k2p9')).toBe(
      '/town-ab12cd/rig-ef34gh/unit-a7k2p9/video',
    )
  })
})
