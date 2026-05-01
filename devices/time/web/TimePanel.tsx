import { useEffect, useMemo, useState } from 'react'
import type { DeviceDetailRenderProps } from '../../../web/src/device-adapter'
import {
  extractTimeReportedState,
  formatEpochMs,
  formatTimeValue,
  parseTimeNowResult,
  type TimeNowResult,
} from './time-model'

type TimePanelProps = Pick<
  DeviceDetailRenderProps,
  'callMcpTool' | 'isShadowConnected' | 'reportedRedcon' | 'shadow'
>

const pollIntervalMs = 1_000

function TimePanel({
  callMcpTool,
  isShadowConnected,
  reportedRedcon,
  shadow,
}: TimePanelProps) {
  const reportedState = useMemo(() => extractTimeReportedState(shadow), [shadow])
  const [activeTime, setActiveTime] = useState<TimeNowResult | null>(null)
  const [mcpError, setMcpError] = useState<string | null>(null)
  const shouldPollMcp = reportedRedcon === 1 && isShadowConnected

  useEffect(() => {
    if (!shouldPollMcp) {
      setActiveTime(null)
      setMcpError(null)
      return
    }

    let cancelled = false
    const refresh = async (): Promise<void> => {
      try {
        const result = parseTimeNowResult(await callMcpTool('time.now', {}))
        if (cancelled) {
          return
        }
        if (!result) {
          setMcpError('Invalid time.now response')
          return
        }
        setActiveTime(result)
        setMcpError(null)
      } catch (caughtError) {
        if (!cancelled) {
          setMcpError(caughtError instanceof Error ? caughtError.message : 'Unable to read time.now')
        }
      }
    }

    void refresh()
    const intervalId = window.setInterval(() => {
      void refresh()
    }, pollIntervalMs)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [callMcpTool, shouldPollMcp])

  return (
    <section className="time-device-panel" aria-label="Time device status">
      <div className="time-device-clock" aria-label="Current time">
        <span className="time-device-clock-label">UTC</span>
        <span className="time-device-clock-value">
          {formatTimeValue(activeTime?.currentTimeIso ?? reportedState.currentTimeIso)}
        </span>
      </div>
      <div className="time-device-grid">
        <div className="time-device-metric">
          <span className="time-device-metric-label">Rendezvous</span>
          <span className="time-device-metric-value">
            {formatTimeValue(reportedState.currentTimeIso)}
          </span>
        </div>
        <div className="time-device-metric">
          <span className="time-device-metric-label">Mode</span>
          <span className="time-device-metric-value">
            {reportedState.mode ?? '--'}
          </span>
        </div>
        <div className="time-device-metric">
          <span className="time-device-metric-label">Active until</span>
          <span className="time-device-metric-value">
            {formatEpochMs(reportedState.activeUntilMs)}
          </span>
        </div>
        <div className="time-device-metric">
          <span className="time-device-metric-label">Live time</span>
          <span className="time-device-metric-value">
            {shouldPollMcp
              ? formatTimeValue(activeTime?.currentTimeIso ?? null)
              : 'unavailable'}
          </span>
        </div>
      </div>
      {mcpError ? (
        <p className="time-device-error" role="status">
          {mcpError}
        </p>
      ) : null}
    </section>
  )
}

export default TimePanel
