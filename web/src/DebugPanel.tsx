type DebugPanelProps = {
  reportedMcuPower: boolean | null
  reportedBoardPower: boolean | null
  shadowJson: string
}

const getPowerNodeClass = (power: boolean | null): string => {
  if (power === true) {
    return 'status-node-awake'
  }
  if (power === false) {
    return 'status-node-asleep'
  }
  return 'status-node-unknown'
}

function DebugPanel({
  reportedMcuPower,
  reportedBoardPower,
  shadowJson,
}: DebugPanelProps) {
  return (
    <section className="card debug-panel">
      <div className="status-devices">
        <div className={`status-device ${getPowerNodeClass(reportedMcuPower)}`}>
          <pre className="status-glyph status-glyph-chip" aria-hidden="true">
            {'╭┄┄╮\n┆▣▣┆\n╰┄┄╯'}
          </pre>
          <div className="status-device-label">MCU</div>
        </div>
        <div className={`status-device ${getPowerNodeClass(reportedBoardPower)}`}>
          <pre className="status-glyph status-glyph-board" aria-hidden="true">
            {'┏━╍━┓\n┃▣╋▣┃\n┗┳━┳┛\n◖▂▂◗'}
          </pre>
          <div className="status-device-label">Board</div>
        </div>
      </div>

      <label htmlFor="shadow-json" className="editor-label">
        Current shadow JSON
      </label>
      <textarea
        id="shadow-json"
        className="editor"
        value={shadowJson}
        readOnly
        spellCheck={false}
      />
    </section>
  )
}

export default DebugPanel
