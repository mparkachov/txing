import { describeRedcon, getTxingRedconToneClass } from './app-model'

type SparkplugPanelProps = {
  routeKind: 'town' | 'rig' | 'device' | 'device_video'
  botRedcon: number | null
  targetRedcon: number | null
  isRedconCommandDisabled: boolean
  isRedconSleepCommandDisabled: boolean
  onRedconSelect: (redcon: 1 | 2 | 3 | 4) => void
}

type SparkplugNodeKind = 'town' | 'rig' | 'bot'
type RedconLevel = 1 | 2 | 3 | 4

const orderedRedconLevels: readonly RedconLevel[] = [4, 3, 2, 1]

const getSparkplugNodeKind = (routeKind: SparkplugPanelProps['routeKind']): SparkplugNodeKind => {
  if (routeKind === 'town') {
    return 'town'
  }
  if (routeKind === 'rig') {
    return 'rig'
  }
  return 'bot'
}

function SparkplugRedconControl({
  isInteractive,
  isPending,
  isSleepCommandDisabled,
  onSelect,
  pendingRedcon,
  redcon,
}: {
  isInteractive: boolean
  isPending: boolean
  isSleepCommandDisabled: boolean
  onSelect: (redcon: RedconLevel) => void
  pendingRedcon: number | null
  redcon: number | null
}) {
  return (
    <div
      className="sparkplug-redcon-control"
      role="group"
      aria-label={isInteractive ? 'REDCON manual control' : 'REDCON status'}
    >
      {orderedRedconLevels.map((level, index) => {
        const isActive = redcon === level
        const isTargetPending = pendingRedcon === level && pendingRedcon !== redcon
        const isDisabled =
          !isInteractive ||
          (level === 4
            ? isSleepCommandDisabled
            : isPending || isActive)
        return (
          <div key={level} className="sparkplug-redcon-segment">
            <span className="sparkplug-redcon-button-wrap">
              {isTargetPending ? (
                <span className="sparkplug-redcon-target-arrow" aria-hidden="true">
                  ↓
                </span>
              ) : null}
              <button
                type="button"
                className={`sparkplug-redcon-button ${getTxingRedconToneClass(level)} ${
                  isActive ? 'sparkplug-redcon-button-active' : ''
                } ${isTargetPending ? 'sparkplug-redcon-button-pending' : ''}`}
                aria-label={isInteractive ? `Set ${describeRedcon(level)}` : describeRedcon(level)}
                aria-pressed={isActive}
                title={describeRedcon(level)}
                disabled={isDisabled}
                onClick={() => {
                  onSelect(level)
                }}
              >
                {level}
              </button>
            </span>
            {index < orderedRedconLevels.length - 1 ? (
              <span className="sparkplug-redcon-line" aria-hidden="true" />
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function SparkplugPanel({
  routeKind,
  botRedcon,
  targetRedcon,
  isRedconCommandDisabled,
  isRedconSleepCommandDisabled,
  onRedconSelect,
}: SparkplugPanelProps) {
  const kind = getSparkplugNodeKind(routeKind)
  const isBot = kind === 'bot'
  const rowRedcon = isBot ? botRedcon : 1
  const isInteractive = isBot && (routeKind === 'device' || routeKind === 'device_video')
  const isPending = targetRedcon !== null && targetRedcon !== rowRedcon

  return (
    <section className="sparkplug-strip" aria-label="Sparkplug status">
      <div className="sparkplug-row" data-sparkplug-row={kind}>
        <SparkplugRedconControl
          isInteractive={isInteractive}
          isPending={isRedconCommandDisabled || isPending}
          isSleepCommandDisabled={isRedconSleepCommandDisabled}
          onSelect={onRedconSelect}
          pendingRedcon={isPending ? targetRedcon : null}
          redcon={rowRedcon}
        />
      </div>
    </section>
  )
}

export default SparkplugPanel
