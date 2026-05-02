import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const repoRoot = resolve(import.meta.dir, '../..')

describe('app route catalog source wiring', () => {
  test('rig device catalog queries by rig thing id, not display name', () => {
    const appSource = readFileSync(resolve(repoRoot, 'web/src/App.tsx'), 'utf-8')

    expect(appSource).toContain("const currentRigCatalogThingName = route.kind === 'rig' ? route.rig : null")
    expect(appSource).toContain('listRigDevices(resolveSessionIdToken, currentRigCatalogThingName)')
    expect(appSource).not.toContain('listRigDevices(resolveSessionIdToken, currentRigCatalogName)')
  })

  test('town and rig route headers refresh sparkplug shadows without a device session', () => {
    const appSource = readFileSync(resolve(repoRoot, 'web/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const routeSparkplugPollIntervalMs = 2_000')
    expect(appSource).toContain("if (route.kind !== 'town' && route.kind !== 'rig')")
    expect(appSource).toContain('void refreshRouteSparkplugShadow(currentRouteThingName)')
  })
})
