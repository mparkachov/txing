import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import TxingPanel from '../src/TxingPanel'

describe('txing panel', () => {
  test('renders the redcon dot indicator around the bot label', () => {
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

    expect(markup).toContain('BOT')
    expect(markup).toContain('status-txing-title-group')
    expect(markup).toContain('aria-label="REDCON 2 · Ember Watch · Orange"')
    expect(markup).toContain('data-redcon-level="4"')
    expect(markup).toContain('data-redcon-level="3"')
    expect(markup).toContain('data-redcon-level="2"')
    expect(markup).toContain('data-redcon-level="1"')
    expect(markup.indexOf('data-redcon-level="4"')).toBeLessThan(markup.indexOf('data-redcon-level="3"'))
    expect(markup.indexOf('data-redcon-level="3"')).toBeLessThan(markup.indexOf('BOT'))
    expect(markup.indexOf('BOT')).toBeLessThan(markup.indexOf('data-redcon-level="2"'))
    expect(markup.indexOf('data-redcon-level="2"')).toBeLessThan(markup.indexOf('data-redcon-level="1"'))
    expect(markup.match(/status-redcon-connector/g)?.length).toBe(2)
    expect(markup).toContain('data-track-side="left"')
    expect(markup).toContain('data-track-speed="60"')
    expect(markup).toContain('aria-label="Left track forward 60 percent"')
    expect(markup).toContain('data-track-side="right"')
    expect(markup).toContain('data-track-speed="-30"')
    expect(markup).toContain('aria-label="Right track reverse 30 percent"')
    expect(markup).toContain('status-track-gauge-needle status-track-forward')
    expect(markup).toContain('status-track-gauge-needle status-track-reverse')
    expect(markup).toContain('status-redcon-dot status-redcon-dot-active status-txing-redcon-2')
    expect(markup).toContain('status-redcon-dot status-redcon-dot-inactive')
    expect(markup).not.toContain('status-redcon-dot-active status-txing-redcon-1')
    expect(markup).not.toContain('status-redcon-dot-active status-txing-redcon-3')
    expect(markup).not.toContain('status-redcon-dot-active status-txing-redcon-4')
  })
})
