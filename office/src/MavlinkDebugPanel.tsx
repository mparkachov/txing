import type { ReactNode } from 'react'
import type { MavlinkFlightState } from './mavlink-control'

export default function MavlinkDebugPanel({ vehicleName, connection, owner, flight, leaseTtlMs, children }: {
  vehicleName: string
  connection: string
  owner: string
  flight: MavlinkFlightState
  leaseTtlMs?: number
  children?: ReactNode
}) {
  const armed = flight.armed === null ? 'Arm state pending' : flight.armed ? 'Armed' : 'Disarmed'
  const mode = flight.mode === null ? 'Mode pending' : `Mode ${flight.mode}`
  return (
    <section className="mavlink-debug-panel" aria-label={`${vehicleName} ArduPilot debug`}>
      <div className="mavlink-debug-heading">
        <strong>ArduPilot / MAVLink</strong>
        <span>{connection}</span>
      </div>
      <p>{owner}</p>
      <p>{armed} · {mode}</p>
      {leaseTtlMs !== undefined && <p>{leaseTtlMs / 1_000}-second renewable lease</p>}
      {children}
      <p className="mavlink-debug-help">Use the video overlay to acquire or release control.</p>
    </section>
  )
}
