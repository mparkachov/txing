import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import NavigationUserMenu from '../src/NavigationUserMenu'

describe('navigation user menu', () => {
  test('renders only session log and sign off actions in the open menu', () => {
    const markup = renderToStaticMarkup(
      <NavigationUserMenu
        authUser={{
          email: 'operator@example.com',
          name: 'Signed in',
          sub: 'abc123',
        }}
        defaultOpen={true}
        isSessionLogVisible={false}
        onSignOff={() => {}}
        onToggleSessionLog={() => {}}
      />,
    )

    expect(markup).toContain('role="menu"')
    expect(markup).toContain('Show Session Log')
    expect(markup).toContain('Sign Off')
    expect(markup).not.toContain('Load Shadow')
    expect(markup).not.toContain('Enable Debug')
    expect(markup).not.toContain('Disable Debug')
  })
})
