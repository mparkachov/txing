import { extractSparkplugCapabilityAvailability } from '../../../office/src/sparkplug-model'
import type { MavlinkVideoStatus } from '../../../office/src/VideoControlOverlay'

export function readQuadMediaAvailability(
  fresh: boolean, phase: string | undefined, redcon: number | null, sparkplug: unknown,
) {
  const operational = fresh && phase === 'operational' && redcon === 1
  return {
    mavlink: fresh && (phase === 'starting' || phase === 'operational') &&
      (redcon === 1 || redcon === 2) && extractSparkplugCapabilityAvailability(sparkplug, 'mavlink') === true,
    video: operational && extractSparkplugCapabilityAvailability(sparkplug, 'video') === true,
  }
}

export function readQuadMavlinkStatus(
  view: { heartbeat: boolean; connected: boolean } | null, connectionError: string | null,
): MavlinkVideoStatus {
  if (view?.heartbeat) return 'live'
  if (view?.connected) return 'waiting for heartbeat'
  return connectionError ? 'reconnecting' : 'connecting'
}
