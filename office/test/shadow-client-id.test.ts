import { describe, expect, test } from 'bun:test'
import { buildShadowMqttClientId } from '../src/shadow-client-id'

describe('shadow MQTT client ids', () => {
  test('keeps the cognito identity id while adding a unique session suffix', () => {
    expect(buildShadowMqttClientId('eu-central-1:identity', 'session-a')).toBe(
      'eu-central-1:identity-session-a',
    )
    expect(buildShadowMqttClientId('eu-central-1:identity', 'session-b')).toBe(
      'eu-central-1:identity-session-b',
    )
  })

  test('allows two browser sessions for the same identity to observe the same device', () => {
    const firstBrowserClientId = buildShadowMqttClientId(
      'eu-central-1:identity',
      'browser-session-a',
    )
    const secondBrowserClientId = buildShadowMqttClientId(
      'eu-central-1:identity',
      'browser-session-b',
    )

    expect(firstBrowserClientId).toBe('eu-central-1:identity-browser-session-a')
    expect(secondBrowserClientId).toBe('eu-central-1:identity-browser-session-b')
    expect(firstBrowserClientId).not.toBe(secondBrowserClientId)
  })
})
