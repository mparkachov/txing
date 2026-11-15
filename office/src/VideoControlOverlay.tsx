import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { McpTransportKind } from './mcp-descriptor'

export type MavlinkVideoStatus = 'inactive' | 'connecting' | 'waiting for heartbeat' | 'reconnecting' | 'live'

type Link =
  | { protocol: 'MAVLink'; status: MavlinkVideoStatus; detail?: string | null }
  | { protocol: 'MCP'; transport: McpTransportKind | null }
type Authority = {
  state: 'unknown' | 'none' | 'current' | 'other'
  label: string
  action?: { label: string; disabled: boolean; run: () => void }
}

const mavlinkLabel: Record<MavlinkVideoStatus, string> = {
  inactive: 'MAVLink unavailable',
  connecting: 'Connecting MAVLink',
  'waiting for heartbeat': 'MAVLink waiting for heartbeat',
  reconnecting: 'Reconnecting MAVLink',
  live: 'MAVLink live',
}

type Icon = 'debug' | 'controller' | 'control' | 'held' | 'mcp'

const iconPaths: Record<Icon, string> = {
  debug: 'M9 8.5V7a3 3 0 0 1 6 0v1.5M8 10h8m-7 3h6m-5 3h4M7 8l-2-2m14 2 2-2M8 19l-2 2m10-2 2 2M8.5 8h7a1.5 1.5 0 0 1 1.5 1.5v5a5 5 0 0 1-10 0v-5A1.5 1.5 0 0 1 8.5 8Z',
  controller: 'M8 8h8c2 0 3.5 1.5 4 3.5l1.1 4.2c.5 2-1.7 3.3-3.1 2l-3-2.7H9l-3 2.7c-1.4 1.3-3.6 0-3.1-2L4 11.5C4.5 9.5 6 8 8 8Zm0 2.5v4m-2-2h4m5.5 0h.01m2-1.5h.01',
  control: 'M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm0 3.5v7m-3.5-3.5h7',
  held: 'm5 12.8 4.4 4.2L19 7',
  mcp: 'M6 8h2m2 0h4m2 0h2M6 16h2m2 0h4m2 0h2',
}

function VideoOverlayGlyph({ icon }: { icon: Icon }) {
  return (
    <svg className="video-overlay-glyph" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d={iconPaths[icon]} fill="none" stroke="currentColor" strokeWidth="1.8"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function VideoOverlayButton({ icon, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: Icon }) {
  return (
    <button type="button" className="video-overlay-icon" {...props}>
      <VideoOverlayGlyph icon={icon} />
    </button>
  )
}

export function VideoOverlayRow({ controls, debug, center, indicators }: {
  controls?: ReactNode
  debug?: { enabled: boolean; toggle: () => void }
  center?: ReactNode
  indicators?: ReactNode
}) {
  const debugLabel = debug?.enabled ? 'Disable Debug' : 'Enable Debug'
  return (
    <div className="status-video-overlay-bar">
      <div className="status-video-overlay-side status-video-overlay-side-start">
        {debug && <VideoOverlayButton icon="debug" aria-label={debugLabel} title={debugLabel}
          aria-pressed={debug.enabled} onClick={debug.toggle} />}
        {controls}
      </div>
      {center}
      {indicators}
    </div>
  )
}

export default function VideoControlOverlay({
  link, authority, children,
}: {
  link: Link
  authority?: Authority
  children?: ReactNode
}) {
  const status = link.protocol === 'MAVLink' ? mavlinkLabel[link.status]
    : link.transport === 'webrtc-datachannel' ? 'MCP over WebRTC data channel'
      : link.transport === 'mqtt-jsonrpc' ? 'MCP over MQTT JSON-RPC' : 'MCP transport pending'
  const active = link.protocol === 'MAVLink' ? link.status === 'live' : link.transport !== null
  const detail = link.protocol === 'MAVLink' ? link.detail : null
  const description = [status, authority?.label, detail].filter(Boolean).join(' · ')
  const icon = authority?.state === 'current' ? 'held' : link.protocol === 'MAVLink' || authority?.action ? 'control' : 'mcp'
  return (
    <div className="video-control-overlay" role="group" aria-label="Video controls">
      {authority?.action ? (
        <VideoOverlayButton icon={icon} aria-label={authority.action.label} aria-description={description}
          title={`${authority.action.label} · ${description}`} data-control-owner={authority.state}
          data-linked={active} disabled={authority.action.disabled} onClick={authority.action.run} />
      ) : (
        <span className="video-overlay-icon" role="img" aria-label={description} title={description}
          data-control-owner={authority?.state} data-linked={active}>
          <VideoOverlayGlyph icon={icon} />
        </span>
      )}
      {children}
    </div>
  )
}
