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

  test('town and rig catalog rows render sparkplug status without short ids', () => {
    const appSource = readFileSync(resolve(repoRoot, 'web/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const renderSparkplugCatalogCardLink = (')
    expect(appSource).toContain('<CapabilityStack')
    expect(appSource).toContain('const readRigSparkplugStatus = async')
    expect(appSource).toContain('const readDeviceSparkplugStatus = async')
    expect(appSource).toContain('rigs: createPendingCatalogItems(rigs)')
    expect(appSource).toContain('devices: createPendingCatalogItems(devices)')
    expect(appSource).toContain('rig.rigName')
    expect(appSource).toContain('getCatalogDeviceLabel(device)')
    expect(appSource).not.toContain('formatCatalogDetailLine(')
  })

  test('route navigation reuses capability stack for the current thing', () => {
    const appSource = readFileSync(resolve(repoRoot, 'web/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const navigationCapabilities =')
    expect(appSource).toContain('className="navigation-capabilities"')
    expect(appSource).toContain('{navigationCapabilities}')
  })

  test('route transitions use busy navigation styling instead of transient loading copy', () => {
    const appSource = readFileSync(resolve(repoRoot, 'web/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const isNavigationBusy =')
    expect(appSource).toContain("className={`card navigation-panel ${isNavigationBusy ? 'navigation-panel-busy' : ''}`}")
    expect(appSource).toContain('aria-busy={isNavigationBusy}')
    expect(appSource).not.toContain('className="navigation-activity"')
    expect(appSource).not.toContain('<h1>Loading route</h1>')
    expect(appSource).not.toContain('<p>Loading rigs...</p>')
    expect(appSource).not.toContain('<p>Loading devices...</p>')
  })

  test('public landing can request office-origin sign-in', () => {
    const appSource = readFileSync(resolve(repoRoot, 'web/src/App.tsx'), 'utf-8')

    expect(appSource).toContain("const signInRequestParam = 'signin'")
    expect(appSource).toContain('const consumeSignInRequest = (): boolean =>')
    expect(appSource).toContain("currentUrl.searchParams.get(signInRequestParam) !== '1'")
    expect(appSource).toContain('currentUrl.searchParams.delete(signInRequestParam)')
    expect(appSource).toContain('const shouldBeginRequestedSignIn = consumeSignInRequest()')
    expect(appSource).toContain('if (shouldBeginRequestedSignIn)')
    expect(appSource).toContain("setStatus('authenticating')")
    expect(appSource).toContain('await beginSignIn()')
  })
})
