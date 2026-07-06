import { describe, expect, test } from 'bun:test'
import cloudMcuDeviceAdapter from '../../devices/cloud-mcu/web/cloud-mcu-adapter'
import { extractCloudMcuReportedState } from '../../devices/cloud-mcu/web/cloud-mcu-model'
import type { DeviceDetailRenderProps } from '../src/device-adapter'

describe('cloud-mcu adapter', () => {
  test('renders sleeping state from the power shadow without sqs tick state', () => {
    const shadow = {
      namedShadows: {
        power: {
          state: {
            reported: {
              desiredRedcon: 4,
              powered: false,
              ecsTaskArn: null,
              ecsTaskStatus: null,
            },
          },
        },
        sqs: {
          state: {
            reported: {},
          },
        },
      },
    }

    expect(extractCloudMcuReportedState(shadow)).toEqual({
      desiredRedcon: 4,
      powered: false,
      ecsTaskArn: null,
      ecsTaskStatus: null,
    })
    expect(cloudMcuDeviceAdapter.extractTelemetry(shadow)).toEqual({
      reportedBatteryMv: null,
      reportedBoardPower: null,
      reportedBoardOnline: null,
      reportedMcuOnline: true,
      reportedMcuPower: false,
    })
    expect(
      collectRenderedText(cloudMcuDeviceAdapter.renderDetail(createRenderProps(shadow))),
    ).toContain('REDCON 4')
  })

  test('renders awake ECS state from the power shadow', () => {
    const shadow = {
      namedShadows: {
        power: {
          state: {
            reported: {
              desiredRedcon: 3,
              powered: true,
              ecsTaskArn: 'arn:aws:ecs:task/cloud-1',
              ecsTaskStatus: 'RUNNING',
            },
          },
        },
      },
    }

    expect(extractCloudMcuReportedState(shadow)).toEqual({
      desiredRedcon: 3,
      powered: true,
      ecsTaskArn: 'arn:aws:ecs:task/cloud-1',
      ecsTaskStatus: 'RUNNING',
    })
    expect(cloudMcuDeviceAdapter.extractTelemetry(shadow).reportedMcuPower).toBe(true)
    const renderedText = collectRenderedText(
      cloudMcuDeviceAdapter.renderDetail(createRenderProps(shadow)),
    )
    expect(renderedText).toContain('REDCON 3')
    expect(renderedText).toContain('RUNNING')
  })
})

const createRenderProps = (shadow: unknown): DeviceDetailRenderProps => ({
  callMcpTool: async () => null,
  isBoardVideoExpanded: false,
  isDebugEnabled: false,
  isShadowConnected: true,
  isTakeControlPending: false,
  mcpTransport: null,
  onBoardVideoRuntimeError: () => {},
  onTakeControl: () => {},
  onToggleDebug: () => {},
  reportedBatteryMv: null,
  reportedBoardLeftTrackSpeed: null,
  reportedBoardOnline: null,
  reportedBoardRightTrackSpeed: null,
  reportedMcuOnline: null,
  reportedMcuPower: null,
  reportedRedcon: 1,
  resolveIdToken: async () => 'token',
  robotControl: null,
  shadow,
  videoChannelName: 'test-video',
})

const collectRenderedText = (node: unknown): string => {
  if (
    node === null ||
    node === undefined ||
    typeof node === 'boolean' ||
    typeof node === 'symbol'
  ) {
    return ''
  }
  if (typeof node === 'string' || typeof node === 'number' || typeof node === 'bigint') {
    return String(node)
  }
  if (Array.isArray(node)) {
    return node.map(collectRenderedText).join('')
  }
  if (typeof node !== 'object') {
    return ''
  }

  const element = node as {
    props?: Record<string, unknown>
    type?: unknown
  }
  if (typeof element.type === 'function') {
    return collectRenderedText(element.type(element.props ?? {}))
  }

  const propText = Object.entries(element.props ?? {})
    .filter(([name, value]) => name !== 'children' && typeof value === 'string')
    .map(([, value]) => value)
    .join('')

  return `${propText}${collectRenderedText(element.props?.children)}`
}
