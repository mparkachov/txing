import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const repoRoot = resolve(import.meta.dir, '../..')

describe('office config wiring', () => {
  test('write-env sources town identity without a preselected device or rig', () => {
    const justfile = readFileSync(resolve(repoRoot, 'office/justfile'), 'utf-8')

    expect(justfile).toContain(
      "write-env sparkplug_group_id='' town_thing_name=''",
    )
    expect(justfile).toContain('current_sparkplug_group_id="$SPARKPLUG_GROUP_ID"')
    expect(justfile).toContain('current_town_thing_name="$SPARKPLUG_GROUP_ID"')
    expect(justfile).not.toContain('_project-aws-env device')
    expect(justfile).not.toContain('_project-aws-env rig')
    expect(justfile).not.toContain('town_search_query=')
    expect(justfile).toContain('"VITE_TOWN_THING_NAME=$current_town_thing_name"')
    expect(justfile).toContain('"VITE_SPARKPLUG_GROUP_ID=$current_sparkplug_group_id"')
    expect(justfile).not.toContain('VITE_SPARKPLUG_EDGE_NODE_ID')
    expect(justfile).not.toContain('VITE_DEVICE_THING_NAME')
    expect(justfile).not.toContain('VITE_TXING_VERSION')
  })

  test('runtime config requires the configured town thing and uses build-time version', () => {
    const configSource = readFileSync(resolve(repoRoot, 'office/src/config.ts'), 'utf-8')
    const authSource = readFileSync(resolve(repoRoot, 'office/src/auth.ts'), 'utf-8')
    const shadowRuntimeSource = readFileSync(resolve(repoRoot, 'office/src/shadow-api-runtime.ts'), 'utf-8')
    const viteConfigSource = readFileSync(resolve(repoRoot, 'office/vite.config.ts'), 'utf-8')

    expect(configSource).toContain("const townThingName = requireEnv('VITE_TOWN_THING_NAME') ?? ''")
    expect(configSource).toContain("const sparkplugGroupId = requireEnv('VITE_SPARKPLUG_GROUP_ID') ?? ''")
    expect(configSource).toContain("typeof __TXING_VERSION__ === 'string'")
    expect(configSource).toContain("? __TXING_VERSION__.trim()")
    expect(configSource).not.toContain('VITE_SPARKPLUG_EDGE_NODE_ID')
    expect(configSource).toContain('txingVersion,')
    expect(configSource).toContain("errors.push('Missing VITE_TOWN_THING_NAME')")
    expect(configSource).toContain("errors.push('Missing VITE_SPARKPLUG_GROUP_ID')")
    expect(configSource).not.toContain('VITE_DEVICE_THING_NAME')
    expect(configSource).not.toContain('VITE_TXING_VERSION')
    expect(viteConfigSource).toContain('__TXING_VERSION__')
    expect(viteConfigSource).toContain("../VERSION")
    expect(viteConfigSource).not.toContain("git rev-parse --short=12 HEAD")
    expect(authSource).toContain('redirect_uri: getRuntimeAppUrl()')
    expect(authSource).toContain("const productionOfficeOrigin = 'https://office.txing.dev'")
    expect(authSource).toContain("const productionPublicLogoutUrl = 'https://txing.dev/'")
    expect(authSource).toContain('logout_uri: getLogoutUrl()')
    expect(shadowRuntimeSource).toContain('version: appConfig.txingVersion')
    expect(shadowRuntimeSource).not.toContain("version: '0.5.0'")
  })

  test('production hosting is configured for Cloudflare Pages', () => {
    const justfile = readFileSync(resolve(repoRoot, 'office/justfile'), 'utf-8')
    const redirects = readFileSync(resolve(repoRoot, 'office/public/_redirects'), 'utf-8')
    const tsconfig = readFileSync(resolve(repoRoot, 'office/tsconfig.app.json'), 'utf-8')
    const viteConfigSource = readFileSync(resolve(repoRoot, 'office/vite.config.ts'), 'utf-8')

    expect(justfile).toContain('Production office deployment is managed by Cloudflare Pages.')
    expect(justfile).toContain('Project: txing-office')
    expect(justfile).toContain('Root directory: office')
    expect(justfile).toContain('Build command: bun install --frozen-lockfile && bun --bun run build')
    expect(justfile).toContain('Deploy command: leave empty')
    expect(justfile).toContain('Domain: office.txing.dev')
    expect(justfile).not.toContain('ln -snf')
    expect(justfile).not.toContain('aws s3 sync')
    expect(justfile).not.toContain('aws cloudfront create-invalidation')
    expect(redirects.trim()).toBe('/* /index.html 200')
    expect(tsconfig).toContain('"react": ["./node_modules/@types/react"]')
    expect(tsconfig).toContain('"react/jsx-runtime": ["./node_modules/@types/react/jsx-runtime"]')
    expect(viteConfigSource).toContain("new URL('./node_modules/react/index.js'")
    expect(viteConfigSource).toContain("find: 'react/jsx-runtime'")
    expect(viteConfigSource).toContain("dedupe: ['react', 'react-dom']")
  })
})
