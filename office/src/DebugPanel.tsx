import type { ReactNode } from 'react'
import type { ShadowName } from './shadow-protocol'

type DebugPanelProps = {
  agentShadow?: { status: 'loading' | 'ready' | 'missing' | 'error'; json: string; error: string }
  canLoadShadow: boolean
  deviceDiagnostics?: ReactNode
  initialSparkplugShadow?: unknown
  lastShadowUpdateLabel: string
  lastShadowUpdateTitle: string
  onLoadShadow: () => void
  shadowDocument: unknown
  shadowNames: readonly ShadowName[]
}

const shadowDisplayNames: Readonly<Partial<Record<ShadowName, string>>> = {
  ble: 'BLE',
  ecs: 'ECS',
  mavlink: 'MAVLink',
  mcp: 'MCP',
  sqs: 'SQS',
}

function DebugPanel({
  agentShadow,
  canLoadShadow,
  deviceDiagnostics,
  initialSparkplugShadow,
  lastShadowUpdateLabel,
  lastShadowUpdateTitle,
  onLoadShadow,
  shadowDocument,
  shadowNames,
}: DebugPanelProps) {
  const namedShadows = shadowDocument && typeof shadowDocument === 'object' && 'namedShadows' in shadowDocument
    ? shadowDocument.namedShadows
    : null
  const documents = namedShadows && typeof namedShadows === 'object'
    ? namedShadows as Record<ShadowName, unknown>
    : {}

  return (
    <section className="debug-panel" aria-label="Debug">
      <div className="card">
        {deviceDiagnostics ? (
          <div className="debug-panel-device-diagnostics">{deviceDiagnostics}</div>
        ) : null}

        <div className="debug-panel-meta">
          <span className="debug-panel-meta-label">Last shadow update</span>
          <div className="debug-panel-meta-actions">
            <button
              type="button"
              className="debug-panel-load-shadow"
              disabled={!canLoadShadow}
              onClick={onLoadShadow}
            >
              Load Shadow
            </button>
            <time className="status-last-shadow-update" title={lastShadowUpdateTitle}>
              {lastShadowUpdateLabel}
            </time>
          </div>
        </div>
      </div>

      {shadowNames.map((name) => {
        const displayName = (Object.hasOwn(shadowDisplayNames, name) ? shadowDisplayNames[name] : undefined)
          ?? name.charAt(0).toUpperCase() + name.slice(1)
        const title = `${displayName} shadow`
        const agent = name === 'agent' ? agentShadow : undefined
        const document = Object.hasOwn(documents, name)
          ? documents[name]
          : name === 'sparkplug' ? initialSparkplugShadow ?? undefined : undefined
        const json = agent
          ? agent.status === 'ready' ? agent.json : undefined
          : JSON.stringify(document, null, 2)

        return (
          <section key={name} className="card debug-shadow-panel" aria-label={title}>
            <h2>{title}</h2>
            {json !== undefined ? (
              <textarea
                aria-label={`${title} JSON`}
                className="editor"
                value={json}
                rows={10}
                readOnly
                spellCheck={false}
              />
            ) : (
              <p>
                {agent?.status === 'loading' && 'Loading agent status…'}
                {agent?.status === 'missing' && 'Agent status has not been initialized.'}
                {agent?.status === 'error' && `Agent status unavailable: ${agent.error}`}
                {!agent && 'No shadow data received.'}
              </p>
            )}
          </section>
        )
      })}
    </section>
  )
}

export default DebugPanel
