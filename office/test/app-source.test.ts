import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const repoRoot = resolve(import.meta.dir, '../..')

describe('app route catalog source wiring', () => {
  test('signed-in Cognito users are not filtered by token email', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).not.toContain('adminEmailMismatch')
    expect(appSource).not.toContain('Signed-in user is not allowed')
    expect(appSource).not.toContain('appConfig.adminEmail')
  })

  test('rig device catalog queries by rig thing id, not display name', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain("const currentRigCatalogThingName = route.kind === 'rig' ? route.rig : null")
    expect(appSource).toContain('listRigDevices(resolveSessionIdToken, currentRigCatalogThingName)')
    expect(appSource).not.toContain('listRigDevices(resolveSessionIdToken, currentRigCatalogName)')
  })

  test('town and rig route headers refresh sparkplug shadows without a device session', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const routeSparkplugPollIntervalMs = 2_000')
    expect(appSource).toContain("if (route.kind !== 'town' && route.kind !== 'rig')")
    expect(appSource).toContain('void refreshRouteSparkplugShadow(currentRouteThingName)')
  })

  test('town and rig catalog rows render sparkplug status without short ids', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

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
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const navigationCapabilities =')
    expect(appSource).toContain('className="navigation-capabilities"')
    expect(appSource).toContain('{navigationCapabilities}')
  })

  test('wake commands converge from reported shadow redcon without command-status success', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('hasReachedTargetRedcon({')
    expect(appSource).toContain('reportedRedcon: extractReportedRedcon(nextShadow)')
    expect(appSource).toContain('const commandSequence = createSparkplugRedconCommandSeq(')
    expect(appSource).toContain('commandStatus.seq === commandSequence')
    expect(appSource).toContain('setPendingTargetRedcon(redcon)')
    expect(appSource).toContain('sparkplugRedcon={reportedRedcon}')
    expect(appSource).toContain('reportedRedcon,')
    expect(appSource).not.toContain("commandStatus?.status === 'succeeded'")
    expect(appSource).not.toContain('effectiveReportedRedcon')
    expect(appSource).not.toContain('isWakeRedconPending')
    expect(appSource).not.toContain('commandStatus.seq === commandSequence - 1')
    expect(appSource).not.toContain('commandSequence - 1')
  })

  test('redcon commandability remains governed by sparkplug wiring, not mcp control state', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')
    const commandabilityMatch = appSource.match(
      /const isSparkplugDeviceCommandAvailable =([\s\S]*?)\n {2}const isRedconCommandDisabled/,
    )

    expect(commandabilityMatch?.[1]).toContain('currentThingSparkplugCommandTarget !== null')
    expect(commandabilityMatch?.[1]).toContain('commandableRedconLevels.length > 0')
    expect(commandabilityMatch?.[1]).toContain('!isSparkplugUnavailable')
    expect(commandabilityMatch?.[1]).not.toMatch(
      /canUseDriveControl|isDriveControl|isDriveInputEnabled|isDriveControlOwnedByOther|robotState|mcp|Mcp/,
    )
    expect(appSource).toContain('isInteractive={isSparkplugDeviceCommandAvailable}')
    expect(appSource).toContain('sparkplugRedcon={reportedRedcon}')
  })

  test('route transitions use busy navigation styling instead of transient loading copy', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const isNavigationBusy =')
    expect(appSource).toContain("className={`card navigation-panel ${isNavigationBusy ? 'navigation-panel-busy' : ''}`}")
    expect(appSource).toContain('aria-busy={isNavigationBusy}')
    expect(appSource).not.toContain('className="navigation-activity"')
    expect(appSource).not.toContain('<h1>Loading route</h1>')
    expect(appSource).not.toContain('<p>Loading rigs...</p>')
    expect(appSource).not.toContain('<p>Loading devices...</p>')
  })

  test('public landing can request office-origin sign-in', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain("const signInRequestParam = 'signin'")
    expect(appSource).toContain('const consumeSignInRequest = (): boolean =>')
    expect(appSource).toContain("currentUrl.searchParams.get(signInRequestParam) !== '1'")
    expect(appSource).toContain('currentUrl.searchParams.delete(signInRequestParam)')
    expect(appSource).toContain('const shouldBeginRequestedSignIn = consumeSignInRequest()')
    expect(appSource).toContain('if (shouldBeginRequestedSignIn)')
    expect(appSource).toContain("setStatus('authenticating')")
    expect(appSource).toContain('await beginSignIn()')
  })

  test('drive detail keeps polling robot feedback while motion is active', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const robotStatePollIntervalMs = 5_000')
    expect(appSource).toContain('const intervalId = window.setInterval(() => {')
    expect(appSource).toContain('void requestRobotState()')
    expect(appSource).toContain('}, robotStatePollIntervalMs)')
    expect(appSource).not.toContain('if (isRobotMotionActive || isRobotControlActive)')
  })

  test('drive cmd_vel suppresses recoverable WebRTC transport timeouts', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('isRecoverableMcpDriveTransportError')
    expect(appSource).toContain('isRecoverableMcpDriveTransportError(caughtError)')
    expect(appSource).toContain("'board-cmd-vel'")
  })

  test('drive input auto-acquires control when no owner exists and requires takeover for another owner', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')
    const shadowRuntimeSource = readFileSync(resolve(repoRoot, 'office/src/shadow-api-runtime.ts'), 'utf-8')

    expect(appSource).toContain("type DriveControlOwnership = 'unknown' | 'no-owner' | 'current-browser' | 'another-session'")
    expect(appSource).toContain('const driveControlOwnership = getDriveControlOwnership(robotState)')
    expect(appSource).toContain("return 'no-owner'")
    expect(appSource).toContain("return robotState.control.activeHeldByCaller ? 'current-browser' : 'another-session'")
    expect(appSource).toContain(
      "driveControlOwnership === 'current-browser' || driveControlOwnership === 'no-owner'",
    )
    expect(appSource).toContain('await shadowSession.takeMcpControl()')
    expect(shadowRuntimeSource).toContain('return this.activateMcpControl()')
    expect(shadowRuntimeSource).toContain("this.activateMcpControl(true)")
    expect(shadowRuntimeSource).toContain('buildMcpActivateArguments(this.options.mcpActor, takeover)')
    expect(shadowRuntimeSource).toContain('activateArguments.takeover = true')
    expect(shadowRuntimeSource).not.toContain("actor: 'txing-web'")
  })

  test('mcp active-control actor comes from the signed-in user', () => {
    const appSource = readFileSync(resolve(repoRoot, 'office/src/App.tsx'), 'utf-8')

    expect(appSource).toContain('const buildMcpActor = (authUser: AuthUser | null): string =>')
    expect(appSource).toContain('authUser?.email ?? authUser?.name ?? authUser?.sub')
    expect(appSource).toContain('const mcpActor = useMemo(() => buildMcpActor(authUser), [authUser])')
    expect(appSource).toContain('mcpActor,')
  })
})
