import { useEffect, useRef, useState } from 'react'
import type { AuthUser } from './auth'

type NavigationUserMenuProps = {
  authUser: AuthUser | null
  defaultOpen?: boolean
  isSessionLogVisible: boolean
  onSignOff: () => void
  onToggleSessionLog: () => void
}

function NavigationUserMenu({
  authUser,
  defaultOpen = false,
  isSessionLogVisible,
  onSignOff,
  onToggleSessionLog,
}: NavigationUserMenuProps) {
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(defaultOpen)
  const userMenuRef = useRef<HTMLDivElement | null>(null)
  const userMenuIdentity = authUser?.email ?? authUser?.name ?? authUser?.sub ?? 'User'
  const userMenuInitial = userMenuIdentity.trim().charAt(0).toUpperCase() || 'U'

  useEffect(() => {
    if (!isUserMenuOpen) {
      return
    }

    const handlePointerDown = (event: MouseEvent): void => {
      if (!userMenuRef.current?.contains(event.target as Node)) {
        setIsUserMenuOpen(false)
      }
    }

    const handleEscape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setIsUserMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [isUserMenuOpen])

  return (
    <div className="user-menu" ref={userMenuRef}>
      <button
        type="button"
        className="user-menu-trigger"
        aria-label="Open user menu"
        aria-haspopup="menu"
        aria-expanded={isUserMenuOpen}
        onClick={() => {
          setIsUserMenuOpen((currentValue) => !currentValue)
        }}
      >
        <span className="user-avatar" aria-hidden="true">
          {userMenuInitial}
        </span>
      </button>
      {isUserMenuOpen ? (
        <div className="user-menu-popover" role="menu" aria-label="User actions">
          <div className="user-menu-header">
            <span className="user-avatar user-avatar-large" aria-hidden="true">
              {userMenuInitial}
            </span>
            <div className="user-menu-identity">
              <p className="user-menu-name">{authUser?.name ?? 'Signed in'}</p>
              <p className="user-menu-email">{authUser?.email ?? authUser?.sub ?? 'Unknown user'}</p>
            </div>
          </div>
          <button
            type="button"
            className="user-menu-item"
            role="menuitem"
            onClick={() => {
              onToggleSessionLog()
              setIsUserMenuOpen(false)
            }}
          >
            {isSessionLogVisible ? 'Hide Session Log' : 'Show Session Log'}
          </button>
          <button
            type="button"
            className="user-menu-item user-menu-item-danger"
            role="menuitem"
            onClick={() => {
              setIsUserMenuOpen(false)
              onSignOff()
            }}
          >
            Sign Off
          </button>
        </div>
      ) : null}
    </div>
  )
}

export default NavigationUserMenu
