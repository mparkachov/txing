import { useState } from 'react'
import type { DeviceSessionProps, SessionDeviceWebAdapter } from '../../../office/src/device-adapter'
import { readAgentStatus } from '../../../office/src/agent-shadow-status'
import { extractReportedRedcon } from '../../../office/src/sparkplug-model'
import { VirtualQuadLiveView, VirtualQuadMavlinkDiagnostics } from './VirtualQuadLiveView'
import { readQuadMediaAvailability } from './virtual-quad-media-status'
import { useVirtualQuadRedcon } from './virtual-quad-redcon'
import { isVirtualQuadProjectionFresh, readVirtualQuadSession, useVirtualQuadSession } from './virtual-quad-session'

function displayRedcon(redcon: number | null, fresh: boolean) {
  return redcon !== null && redcon < 3 && !fresh ? 3 : redcon
}

function VirtualQuadDeviceView({
  target, actor, sparkplug, agentShadow, resolveIdToken, debugEnabled, onToggleDebug, notify, log, children,
}: DeviceSessionProps) {
  const view = useVirtualQuadSession(target, resolveIdToken)
  const [debugTarget, setDebugTarget] = useState<HTMLDivElement | null>(null)
  const { session, fresh, now } = view
  const commands = useVirtualQuadRedcon(target, view, resolveIdToken, notify, log)
  const sessionId = session?.sessionId ?? null

  const projection = view.sparkplug ?? sparkplug
  const redcon = extractReportedRedcon(projection)
  const media = readQuadMediaAvailability(fresh, session?.phase, redcon, view.sparkplug)
  const hasMedia = sessionId !== null && (media.mavlink || media.video)
  const deadline = session?.phase === 'starting' ? session.startupDeadlineMs
    : session?.phase === 'operational' ? session.flightDeadlineMs
      : session?.phase === 'stopping' ? session.shutdownDeadlineMs : null
  const seconds = deadline === null ? null : Math.max(0, Math.ceil((deadline - now) / 1_000))

  return children({
    sparkplug: projection,
    redcon: displayRedcon(redcon, fresh),
    targetRedcon: commands.pendingRedcon,
    canStart: commands.canStart,
    canStop: commands.canStop,
    selectRedcon: commands.select,
    statusDetail: seconds === null ? null : (
      <span aria-label="Session time remaining">
        {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}
      </span>
    ),
    agentStatus: readAgentStatus(agentShadow, now, media.video && media.mavlink ? sessionId : null),
    simulationExpiresAtMs: fresh ? session?.availabilityExpiresAtMs ?? null : null,
    debugDiagnostics: hasMedia ? <div ref={setDebugTarget} /> : (
      <VirtualQuadMavlinkDiagnostics status="inactive" connectionError={null} view={null} videoAvailable={false} />
    ),
    content: hasMedia ? (
      <VirtualQuadLiveView
        key={sessionId}
        deviceId={target.deviceId}
        actor={actor}
        videoAvailable={media.video}
        mavlinkAvailable={media.mavlink}
        resolveIdToken={resolveIdToken}
        debugEnabled={debugEnabled}
        onToggleDebug={onToggleDebug}
        debugTarget={debugTarget}
        notify={notify}
      />
    ) : <></>,
  })
}

const virtualQuadAdapter: SessionDeviceWebAdapter = {
  type: 'virtual-quad',
  displayName: 'Virtual Quadcopter',
  View: VirtualQuadDeviceView,
  catalogShadows: ['simulation'],
  readCatalogStatus: (target, { sparkplug, agent, simulation }, now) => {
    const session = readVirtualQuadSession(simulation)
    const fresh = isVirtualQuadProjectionFresh(target, session, sparkplug, now)
    const redcon = extractReportedRedcon(sparkplug)
    const media = readQuadMediaAvailability(fresh, session?.phase, redcon, sparkplug)
    return {
      redcon: displayRedcon(redcon, fresh),
      agentStatus: readAgentStatus(agent, now, media.video && media.mavlink ? session?.sessionId ?? null : null),
      simulationExpiresAtMs: fresh ? session?.availabilityExpiresAtMs ?? null : null,
    }
  },
}

export default virtualQuadAdapter
