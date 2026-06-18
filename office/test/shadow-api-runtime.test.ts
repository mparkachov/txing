import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  buildMcpActivateArguments,
  normalizeMcpActor,
  parseRobotState,
} from '../src/shadow-api-runtime'

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

  test('builds active-control activation arguments from the signed-in actor', () => {
    expect(normalizeMcpActor(' operator@example.com ')).toBe('operator@example.com')
    expect(normalizeMcpActor('   ')).toBe('unknown signed-in user')
    expect(buildMcpActivateArguments('operator@example.com')).toEqual({
      actor: 'operator@example.com',
    })
    expect(buildMcpActivateArguments('operator@example.com', true)).toEqual({
      actor: 'operator@example.com',
      takeover: true,
    })
  })

  test('consumes MCP status active-control ownership updates', () => {
    expect(runtimeSource).toContain('this.updateRobotControlFromMcpStatus(parsed)')
    expect(runtimeSource).toContain('this.updateRobotControlFromMcpStatus(status)')
    expect(runtimeSource).toContain('activeControl.sessionId === this.mcpSessionId')
    expect(runtimeSource).toContain('this.setMcpActiveControl(null)')
  })

  test('maintains active control while idle instead of releasing on stop', () => {
    const zeroTwistMatch = runtimeSource.match(
      /if \(isZeroTwist\(twist\)\) \{([\s\S]*?)\n {4}const active = await this\.ensureMcpActiveControl\(\)/,
    )

    expect(runtimeSource).toContain('private scheduleMcpActiveControlRenew')
    expect(runtimeSource).toContain('void this.renewMcpActiveControlLease()')
    expect(runtimeSource).toContain('private async renewMcpActiveControlLease()')
    expect(zeroTwistMatch?.[1]).toContain("this.callMcpToolInternal('cmd_vel.stop'")
    expect(zeroTwistMatch?.[1]).not.toContain('control.release_active')
    expect(zeroTwistMatch?.[1]).not.toContain('buildLocalRobotControlState(null, false)')
  })

  test('emits session-log diagnostics when active control is lost', () => {
    expect(runtimeSource).toContain('ActiveControlLossReason,')
    expect(runtimeSource).toContain('onActiveControlLost: (event: ActiveControlLossEvent) => void')
    expect(runtimeSource).toContain('private reportActiveControlLoss(')
    expect(runtimeSource).toContain('private reportActiveControlLossFromMcpStatus(')
    expect(runtimeSource).toContain('private tryReacquireActiveControlAfterNoOwnerStatus()')
    expect(runtimeSource).toContain("'mcp-status-no-owner'")
    expect(runtimeSource).toContain("'mcp-status-another-owner'")
    expect(runtimeSource).toContain("'renew-active-failed'")
    expect(runtimeSource).toContain("'cmd-vel-stop-failed'")
    expect(runtimeSource).toContain('this.tryReacquireActiveControlAfterNoOwnerStatus()')
    expect(runtimeSource).toContain('return this.activateMcpControl()')
    expect(runtimeSource).toContain('automatic reacquire after daemon no-owner status failed')
    expect(runtimeSource).toContain('daemon status reported another active owner')
    expect(runtimeSource).toContain('control.renew_active failed and automatic reacquire failed')
    expect(runtimeSource).toContain('cmd_vel.stop could not confirm the active session')
    expect(runtimeSource).toContain('Take active control is available.')
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
