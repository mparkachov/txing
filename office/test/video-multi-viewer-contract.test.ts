import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const repoRoot = resolve(import.meta.dir, '../..')

const readRepoFile = (path: string): string =>
  readFileSync(resolve(repoRoot, path), 'utf-8')

describe('video multi-viewer contract', () => {
  test('keeps browser viewing on the existing single AWS KVS viewer path', () => {
    const videoRuntimeSource = readRepoFile('office/src/video-session-runtime.ts')
    const boardVideoDoc = readRepoFile('devices/unit/docs/board-video.md')

    expect(videoRuntimeSource).toContain('role: Role.VIEWER')
    expect(videoRuntimeSource).toContain(
      'sharedBoardRtcSessionKey(options.region, options.channelName, options.label)',
    )
    expect(videoRuntimeSource).not.toContain('viewerConnected')
    expect(boardVideoDoc).toContain('one AWS KVS signaling channel per video-capable device')
    expect(boardVideoDoc).toContain('one WebRTC peer session per connected viewer client on that channel')
    expect(boardVideoDoc).toContain('no direct browser-to-board media path')
    expect(boardVideoDoc).toContain('a separate multiviewer relay or viewer admission-control service')
  })

  test('native KVS master fans the same encoded uplink to independent viewer peer sessions', () => {
    const kvsMasterSource = readRepoFile('devices/unit/board/kvs_master/src/kvs_session_real.cpp')

    expect(kvsMasterSource).toContain('constexpr UINT32 kMaxConcurrentStreamingSessions = 10;')
    expect(kvsMasterSource).toContain('std::unordered_map<std::string, std::shared_ptr<StreamingSession>> sessions_by_peer_')
    expect(kvsMasterSource).toContain('sessions.reserve(sessions_by_peer_.size())')
    expect(kvsMasterSource).toContain('sessions.push_back(session)')
    expect(kvsMasterSource).toContain('for (const auto& session : sessions)')
    expect(kvsMasterSource).toContain('writeFrame(session->video_transceiver, &frame)')
    expect(kvsMasterSource).toContain('sessions_by_peer_.emplace(peer_id, session)')
  })

  test('video viewer observability is not an admission-control contract', () => {
    const unitContract = readRepoFile('docs/contracts/unit-device-contracts.md')
    const boardVideoDoc = readRepoFile('devices/unit/docs/board-video.md')
    const videoShadowSchema = readRepoFile('devices/unit/aws/video-shadow.schema.json')

    expect(unitContract).toContain('Multiple browser viewers may observe through separate WebRTC peer')
    expect(boardVideoDoc).toContain('video viewing does not grant MCP active control')
    expect(boardVideoDoc).toContain('viewerConnected` is a coarse observability boolean')
    expect(boardVideoDoc).toContain('It is not an')
    expect(boardVideoDoc).toContain('admission-control signal')
    expect(videoShadowSchema).toContain('"viewerConnected"')
    expect(videoShadowSchema).not.toContain('"viewerCount"')
  })
})
