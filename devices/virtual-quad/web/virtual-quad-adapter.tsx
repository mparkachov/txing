import { useEffect, useState } from 'react'
import { getThingNamedShadow } from '../../../office/src/catalog-api'
import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import { extractReportedRedcon } from '../../../office/src/sparkplug-model'

const rigStatusPollIntervalMs = 5_000

export const VirtualQuadStartButton = ({
  rigId,
  resolveIdToken,
  disabled,
  onStart,
}: {
  rigId: string
  resolveIdToken: () => Promise<string>
  disabled: boolean
  onStart: () => void
}) => {
  const [awake, setAwake] = useState(false)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const refresh = async () => {
      let rigAwake = false
      try {
        const shadow = await getThingNamedShadow(resolveIdToken, rigId, 'sparkplug')
        rigAwake = extractReportedRedcon(shadow) === 1
      } catch {
        // Start remains unavailable while the rig projection cannot be read.
      }
      if (!cancelled) {
        setAwake(rigAwake)
        timer = window.setTimeout(() => { void refresh() }, rigStatusPollIntervalMs)
      }
    }
    void refresh()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [resolveIdToken, rigId])

  return awake ? <button type="button" disabled={disabled} onClick={onStart}>Start</button> : null
}

const virtualQuadAdapter: DeviceWebAdapter = {
  type: 'virtual-quad',
  displayName: 'Virtual Quadcopter',
  buildVideoChannelName: (deviceId) => `${deviceId}-board-video`,
  buildMavlinkChannelName: (deviceId) => `${deviceId}-mavlink`,
  canUseBoardVideo: () => false,
  canUseDriveControl: () => false,
  extractTelemetry: () => ({
    reportedBatteryMv: null,
    reportedBoardPower: null,
    reportedBoardOnline: null,
    reportedMcuOnline: null,
    reportedMcuPower: null,
  }),
  getAutoOpenState: () => null,
  shouldCloseDetail: () => false,
  renderDetail: ({ reportedRedcon }) => (
    <section aria-label="Virtual quadcopter status">
      {reportedRedcon === 4 ? 'Stopped' : 'Unavailable'}
    </section>
  ),
  renderVideo: () => <p>Video unavailable</p>,
}

export default virtualQuadAdapter
