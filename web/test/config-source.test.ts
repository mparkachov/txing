import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const repoRoot = resolve(import.meta.dir, '../..')

describe('web config wiring', () => {
  test('write-env sources device and rig identity from project config', () => {
    const justfile = readFileSync(resolve(repoRoot, 'web/justfile'), 'utf-8')

    expect(justfile).toContain(
      "@write-env thing_name='' sparkplug_group_id='' sparkplug_edge_node_id='' town_thing_name=''",
    )
    expect(justfile).toContain(
      'eval "$(just --justfile "{{root_justfile}}" _project-aws-env device "{{region}}" "")"',
    )
    expect(justfile).toContain('device_thing_name="$THING_NAME"')
    expect(justfile).toContain(
      'eval "$(just --justfile "{{root_justfile}}" _project-aws-env rig "{{region}}" "")"',
    )
    expect(justfile).toContain('current_sparkplug_group_id="$SPARKPLUG_GROUP_ID"')
    expect(justfile).toContain('current_sparkplug_edge_node_id="$SPARKPLUG_EDGE_NODE_ID"')
    expect(justfile).toContain('current_town_thing_name="$SPARKPLUG_GROUP_ID"')
    expect(justfile).not.toContain('town_search_query=')
    expect(justfile).toContain('"VITE_TOWN_THING_NAME=$current_town_thing_name"')
    expect(justfile).toContain('"VITE_DEVICE_THING_NAME=$device_thing_name"')
    expect(justfile).toContain('"VITE_SPARKPLUG_GROUP_ID=$current_sparkplug_group_id"')
    expect(justfile).toContain('"VITE_SPARKPLUG_EDGE_NODE_ID=$current_sparkplug_edge_node_id"')
    expect(justfile).not.toContain('"VITE_DEVICE_THING_NAME=unit-local"')
  })

  test('runtime config requires the configured town thing but not a preselected device', () => {
    const configSource = readFileSync(resolve(repoRoot, 'web/src/config.ts'), 'utf-8')
    const authSource = readFileSync(resolve(repoRoot, 'web/src/auth.ts'), 'utf-8')

    expect(configSource).toContain("const thingName = requireEnv('VITE_DEVICE_THING_NAME') ?? ''")
    expect(configSource).toContain("const townThingName = requireEnv('VITE_TOWN_THING_NAME') ?? ''")
    expect(configSource).toContain("const sparkplugGroupId = requireEnv('VITE_SPARKPLUG_GROUP_ID') ?? ''")
    expect(configSource).toContain("errors.push('Missing VITE_TOWN_THING_NAME')")
    expect(configSource).toContain("errors.push('Missing VITE_SPARKPLUG_GROUP_ID')")
    expect(configSource).not.toContain("errors.push('Missing VITE_DEVICE_THING_NAME')")
    expect(configSource).not.toContain("const thingName = requireEnv('VITE_DEVICE_THING_NAME') ?? 'unit-local'")
    expect(authSource).toContain('redirect_uri: getRuntimeAppUrl()')
    expect(authSource).toContain('logout_uri: getRuntimeAppUrl()')
  })
})
