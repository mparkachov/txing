import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import TxingPanel from '../src/TxingPanel'

describe('txing panel', () => {
  test('renders left and right track indicators around the txing label', () => {
    const markup = renderToStaticMarkup(
      <TxingPanel
        authUser={null}
        canLoadShadow={true}
        canUseBoardVideo={false}
        isBoardVideoExpanded={false}
        isDebugEnabled={false}
        isSessionLogVisible={false}
        isTxingSwitchDisabled={false}
        isTxingSwitchPending={false}
        lastShadowUpdateAtMs={null}
        reportedBoardLeftTrackSpeed={60}
        reportedBoardOnline={true}
        reportedBoardRightTrackSpeed={-30}
        reportedBatteryMv={3900}
        reportedMcuOnline={true}
        reportedRedcon={2}
        txingSwitchChecked={true}
        videoChannelName={null}
        resolveIdToken={async () => 'token'}
        onBoardVideoRuntimeError={() => {}}
        onLoadShadow={() => {}}
        onSignOff={() => {}}
        onToggleBoardVideo={() => {}}
        onToggleDebug={() => {}}
        onToggleSessionLog={() => {}}
        onTxingSwitchChange={() => {}}
      />,
    )

    expect(markup).toContain('TXING')
    expect(markup).toContain('status-txing-title-group')
    expect(markup).toContain('status-track-indicator status-track-forward')
    expect(markup).toContain('status-track-indicator status-track-reverse')
    expect(markup).toContain('aria-label="Left track forward 60 percent"')
    expect(markup).toContain('aria-label="Right track reverse 30 percent"')
  })
})
