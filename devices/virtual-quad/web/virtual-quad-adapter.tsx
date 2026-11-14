import { useCallback, useState } from 'react'
import type { DeviceSessionProps, SessionDeviceWebAdapter } from '../../../office/src/device-adapter'
import { extractReportedRedcon } from '../../../office/src/sparkplug-model'
import { VirtualQuadLiveView } from './VirtualQuadLiveView'
import { readVirtualQuadAgentStatus } from './virtual-quad-agent-status'
import { readQuadMediaAvailability, type QuadMavlinkStatus } from './virtual-quad-media-status'
import { useVirtualQuadRedcon } from './virtual-quad-redcon'
import { isVirtualQuadProjectionFresh, readVirtualQuadSession, useVirtualQuadSession } from './virtual-quad-session'

function agentCapability(shadow: unknown, sessionId: string | null, now: number) {
  const label = readVirtualQuadAgentStatus(shadow, sessionId, now)
  return { label, active: label === 'running' }
}

function displayRedcon(redcon: number | null, fresh: boolean) {
  return redcon !== null && redcon < 3 && !fresh ? 3 : redcon
}

function VirtualQuadDeviceView({
  target, actor, sparkplug, agentShadow, resolveIdToken, debugEnabled, notify, log, children,
}: DeviceSessionProps) {
  const view = useVirtualQuadSession(target, resolveIdToken)
  const { session, fresh, now } = view
  const commands = useVirtualQuadRedcon(target, view, resolveIdToken, notify, log)
  const [connection, setConnection] = useState<{ sessionId: string; status: QuadMavlinkStatus } | null>(null)
  const sessionId = session?.sessionId ?? null
  const onMavlinkStatus = useCallback((status: QuadMavlinkStatus) => {
    if (sessionId) setConnection({ sessionId, status })
  }, [sessionId])

  const projection = view.sparkplug ?? sparkplug
  const redcon = extractReportedRedcon(projection)
  const media = readQuadMediaAvailability(fresh, session?.phase, redcon, view.sparkplug)
  const mavlink = !media.mavlink ? 'inactive'
    : connection?.sessionId === sessionId && connection.status !== 'inactive' ? connection.status
      : 'connecting'
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
    capabilities: {
      ...(!media.video && { video: { active: false, label: 'inactive' } }),
      mavlink: { active: mavlink === 'live', label: mavlink },
      agent: agentCapability(agentShadow, media.video && media.mavlink ? sessionId : null, now),
    },
    content: sessionId && (media.mavlink || media.video) ? (
      <VirtualQuadLiveView
        key={sessionId}
        deviceId={target.deviceId}
        actor={actor}
        videoAvailable={media.video}
        mavlinkAvailable={media.mavlink}
        resolveIdToken={resolveIdToken}
        debugEnabled={debugEnabled}
        onMavlinkStatus={onMavlinkStatus}
      />
    ) : <></>,
  })
}

const virtualQuadAdapter: SessionDeviceWebAdapter = {
  type: 'virtual-quad',
  displayName: 'Virtual Quadcopter',
  View: VirtualQuadDeviceView,
  catalogShadows: ['agent', 'simulation'],
  readCatalogStatus: (target, { sparkplug, agent, simulation }, now) => {
    const session = readVirtualQuadSession(simulation)
    const fresh = isVirtualQuadProjectionFresh(target, session, sparkplug, now)
    const redcon = extractReportedRedcon(sparkplug)
    const media = readQuadMediaAvailability(fresh, session?.phase, redcon, sparkplug)
    return {
      redcon: displayRedcon(redcon, fresh),
      capabilities: {
        video: { active: media.video, label: media.video ? 'active' : 'inactive' },
        mavlink: { active: media.mavlink, label: media.mavlink ? 'active' : 'inactive' },
        agent: agentCapability(agent, media.video && media.mavlink ? session?.sessionId ?? null : null, now),
      },
    }
  },
}

export default virtualQuadAdapter
