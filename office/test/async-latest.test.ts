import { describe, expect, test } from 'bun:test'
import { LatestAsyncValueRunner } from '../src/async-latest'

describe('LatestAsyncValueRunner', () => {
  test('coalesces multiple queued values to the latest one', async () => {
    const seen: string[] = []
    let releaseFirstRun: (() => void) | null = null
    const runner = new LatestAsyncValueRunner<string>(async (value) => {
      seen.push(value)
      if (seen.length === 1) {
        await new Promise<void>((resolve) => {
          releaseFirstRun = resolve
        })
      }
    })

    const firstPush = runner.push('forward')
    const secondPush = runner.push('forward')
    const latestPush = runner.push('reverse')

    await Promise.resolve()
    expect(seen).toEqual(['forward'])

    releaseFirstRun?.()
    await Promise.all([firstPush, secondPush, latestPush])

    expect(seen).toEqual(['forward', 'reverse'])
  })

  test('drops queued work when cleared before the current run completes', async () => {
    const seen: string[] = []
    let releaseFirstRun: (() => void) | null = null
    const runner = new LatestAsyncValueRunner<string>(async (value) => {
      seen.push(value)
      if (seen.length === 1) {
        await new Promise<void>((resolve) => {
          releaseFirstRun = resolve
        })
      }
    })

    const firstPush = runner.push('forward')
    void runner.push('reverse')
    runner.clear()
    releaseFirstRun?.()
    await firstPush

    expect(seen).toEqual(['forward'])
  })
})
