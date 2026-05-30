import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parseRobotState } from '../src/shadow-api-runtime'

const repoRoot = resolve(import.meta.dir, '../..')
const runtimeSource = readFileSync(resolve(repoRoot, 'office/src/shadow-api-runtime.ts'), 'utf-8')

describe('shadow api runtime helpers', () => {
  test('parses full active-control owner metadata from robot state', () => {
    const robotState = parseRobotState({
      control: {
        activeRequired: true,
        activeTtlMs: 5000,
        activeHeldByCaller: false,
        activeOwnerSessionId: 'session-a',
        activeExpiresAtMs: 20000,
        activeEpoch: 9,
        activeControl: {
          sessionId: 'session-a',
          actor: 'operator-a',
          transport: 'webrtc-datachannel',
          sinceMs: 10000,
          expiresAtMs: 20000,
          epoch: 9,
        },
      },
      motion: {
        leftSpeed: 0,
        rightSpeed: 0,
        sequence: 2,
      },
      video: {
        available: true,
        ready: true,
        status: 'ready',
        viewerConnected: true,
        lastError: null,
      },
    })

    expect(robotState?.control.activeControl).toEqual({
      sessionId: 'session-a',
      actor: 'operator-a',
      transport: 'webrtc-datachannel',
      sinceMs: 10000,
      expiresAtMs: 20000,
      epoch: 9,
    })
    expect(robotState?.control.activeOwnerSessionId).toBe('session-a')
    expect(robotState?.control.activeEpoch).toBe(9)
  })

  test('keeps browser live-shadow, Sparkplug command, and MCP paths on MQTT5', () => {
    expect(runtimeSource).toContain("import * as mqtt5 from 'aws-crt/dist.browser/browser/mqtt5'")
    expect(runtimeSource).toContain(
      'AwsIotMqtt5ClientConfigBuilder.newWebsocketMqttBuilderWithSigv4Auth',
    )
    expect(runtimeSource).toContain('builder.withSessionBehavior(mqtt5.ClientSessionBehavior.Clean)')
    expect(runtimeSource).toContain('new mqtt5.Mqtt5Client(builder.build())')

    expect(runtimeSource).toContain('packet: mqtt5.PublishPacket')
    expect(runtimeSource).toContain('const packet = buildGetShadowPublishPacket(')
    expect(runtimeSource).toContain('void client\n        .publish(packet)')
    expect(runtimeSource).toContain('const result = await client.publish(packet as mqtt5.PublishPacket)')

    expect(runtimeSource).toContain('const packet = buildSparkplugRedconCommandPacket(')
    expect(runtimeSource).toContain("ensureSuccessfulPuback(result, packet.topicName, 'Sparkplug DCMD.redcon')")

    expect(runtimeSource).toContain('ensureMqttMcpSessionSubscription')
    expect(runtimeSource).toContain('buildMcpSessionS2cTopic(this.options.thingName, this.mcpSessionId)')
    expect(runtimeSource).toContain('} as mqtt5.SubscribePacket')
    expect(runtimeSource).toContain('buildMcpSessionC2sTopic(this.options.thingName, this.mcpSessionId)')
    expect(runtimeSource.match(/as mqtt5\.PublishPacket/g)?.length ?? 0).toBeGreaterThanOrEqual(4)
  })
})
