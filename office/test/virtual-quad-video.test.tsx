import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { VirtualQuadLiveView, VirtualQuadMavlinkDiagnostics } from '../../devices/virtual-quad/web/VirtualQuadLiveView'
import DebugPanel from '../src/DebugPanel'

test.each([[false], [true]])('virtual quad keeps Debug and MAVLink on the video with Debug enabled = %s', (debugEnabled) => {
  const markup = renderToStaticMarkup(
    <VirtualQuadLiveView deviceId="virtual-quad-test" actor="operator"
      videoAvailable mavlinkAvailable resolveIdToken={async () => 'token'}
      debugEnabled={debugEnabled} onToggleDebug={() => {}} debugTarget={null} notify={() => {}} />,
  )
  const stage = markup.slice(markup.indexOf('class="status-video-stage"'), markup.indexOf('class="mavlink-controller"'))
  expect(stage).toContain('class="status-video-overlay-side status-video-overlay-side-start"')
  expect(stage).toContain(`aria-label="${debugEnabled ? 'Disable' : 'Enable'} Debug"`)
  expect(stage).toContain(`aria-pressed="${debugEnabled}"`)
  expect(stage).toContain('aria-description="Connecting MAVLink · View only"')
  expect(stage).toContain('aria-label="Acquire control"')
  expect(stage).toContain('aria-label="On-screen controller"')
  expect(stage).toContain('aria-expanded="false"')
  expect(markup).toContain('class="mavlink-controller" aria-label="Virtual quadcopter controller" hidden=""')
  expect(markup.match(/aria-label="Acquire control"/g)).toHaveLength(1)
  expect(markup).not.toContain('ArduPilot / MAVLink')
  expect(markup).not.toContain('Waiting for camera')
})

test('shows quad flight telemetry alongside the named shadows in Debug', () => {
  const markup = renderToStaticMarkup(
    <DebugPanel canLoadShadow lastShadowUpdateLabel="09:48:56" lastShadowUpdateTitle="Last shadow update"
      onLoadShadow={() => {}} shadowDocument={undefined} shadowNames={['mavlink']}
      deviceDiagnostics={(
        <VirtualQuadMavlinkDiagnostics status="live" connectionError={null} videoAvailable view={{
          connected: true, heartbeat: true, camera: true, supported: true,
          held: true, owner: 'operator', mode: 'Guided', armed: true, landed: 2,
          position: { latitude: 0, longitude: 0, altitude: 2, heading: 72, speed: 0.5 },
          error: null, pending: null, canAcquire: false, canTakeOff: false, canMove: true, canLand: true,
        }} />
      )} />,
  )
  expect(markup).toContain('class="mavlink-debug-panel" aria-label="Virtual quadcopter ArduPilot debug"')
  expect(markup).toContain('Armed · Mode Guided')
  expect(markup).toContain('Airborne')
  expect(markup).toContain('Altitude 2.0 m · Heading 72.0° · Speed 0.5 m/s')
  expect(markup.indexOf('ArduPilot / MAVLink')).toBeLessThan(markup.indexOf('MAVLink shadow'))
})
