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
})
