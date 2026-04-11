import { describe, expect, test } from 'bun:test'
import { resetIotDataEndpointCacheForTest, resolveIotDataEndpoint } from '../src/iot-endpoint'

describe('IoT endpoint resolution', () => {
  test('resolves the IoT Data-ATS endpoint once per region and caches it', async () => {
    resetIotDataEndpointCacheForTest()

    const calls: string[] = []
    const createClient = (idToken: string) => ({
      send: async () => {
        calls.push(idToken)
        return {
          endpointAddress: 'a1b2c3d4e5f6g7-ats.iot.eu-central-1.amazonaws.com',
        }
      },
    })

    const first = await resolveIotDataEndpoint({
      region: 'eu-central-1',
      idToken: 'token-one',
      createClient,
    })
    const second = await resolveIotDataEndpoint({
      region: 'eu-central-1',
      idToken: 'token-two',
      createClient,
    })

    expect(first).toBe('a1b2c3d4e5f6g7-ats.iot.eu-central-1.amazonaws.com')
    expect(second).toBe(first)
    expect(calls).toEqual(['token-one'])
  })

  test('fails when DescribeEndpoint returns no endpoint address', async () => {
    resetIotDataEndpointCacheForTest()

    await expect(
      resolveIotDataEndpoint({
        region: 'eu-central-1',
        idToken: 'token-one',
        createClient: () => ({
          send: async () => ({}),
        }),
      }),
    ).rejects.toThrow('AWS IoT DescribeEndpoint did not return a valid endpointAddress')
  })
})
