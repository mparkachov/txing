import { useEffect, useEffectEvent, useRef, useState, type PointerEvent } from 'react'
import {
  areSticksCentered,
  centeredSticks,
  ControllerButtonTracker,
  ControllerInput,
  ControllerMotion,
  controllerButtons,
  normalizeStick,
  readGamepadSticks,
  readKeyboardSticks,
  sticksForProfile,
  type ControllerButton,
  type ControllerSticks,
  type MotionSource,
} from './mavlink-controller-input'
import { mavlinkDriveRefreshMs } from './mavlink-control'

type StickSide = 'left' | 'right'
type StickPointer = { id: number; x: number; y: number }
type Release = () => void | Promise<void>
type Action = { label: string; enabled: boolean; run: () => void | Promise<void> }
type ControllerProps = {
  vehicleName: string
  profile: 'quad' | 'rover'
  held: boolean
  canMove: boolean
  owner?: string | null
  status?: string
  acquire: { label: string; enabled: boolean; run: (signal: AbortSignal) => Promise<void> }
  release: { enabled: boolean; run: Release }
  takeoff?: Action
  land?: Action
  sendMotion: (sticks: ControllerSticks) => void
}

const holdMs = 1_000
const quadKeys = new Set(['w', 's', 'a', 'd', 'r', 'f', 'q', 'e'])
const roverKeys = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])
const buttonNames = Object.keys(controllerButtons) as ControllerButton[]
const sameSticks = (a: ControllerSticks, b: ControllerSticks) =>
  a.leftX === b.leftX && a.leftY === b.leftY && a.rightX === b.rightX && a.rightY === b.rightY

function isStandardGamepad(gamepad: Gamepad): boolean {
  return gamepad.mapping === 'standard' && gamepad.axes.length >= 4 &&
    gamepad.axes.slice(0, 4).every(Number.isFinite) &&
    gamepad.buttons.length > controllerButtons.Menu
}

export default function MavlinkControllerPanel({
  vehicleName, profile, held, canMove, owner, status, acquire, release, takeoff, land, sendMotion,
}: ControllerProps) {
  const [sticks, setSticks] = useState(centeredSticks)
  const [centered, setCentered] = useState(true)
  const [gamepadStatus, setGamepadStatus] = useState('Press a button on the controller to connect')
  const keys = useRef(new Set<string>())
  const pointers = useRef<Partial<Record<StickSide, StickPointer>>>({})
  const selectedPad = useRef<{ index: number; id: string } | null>(null)
  const usingGamepadControl = useRef(false)
  const buttonTracker = useRef(new ControllerButtonTracker())
  const input = useRef(new ControllerInput())
  const motion = useRef(new ControllerMotion())
  const motionSource = useRef<MotionSource | null>(null)
  const inputsCentered = useRef(false)
  const foreground = useRef(false)
  const acquisition = useRef<AbortController | null>(null)
  const lastCanMove = useRef(false)

  const resetInput = () => {
    keys.current.clear()
    pointers.current = {}
    input.current.reset()
    motion.current.reset()
    motionSource.current = null
    inputsCentered.current = false
    buttonTracker.current.reset()
    setSticks(centeredSticks)
    if (canMove) sendMotion(centeredSticks)
  }

  const isCenteredForAction = () => inputsCentered.current && keys.current.size === 0 &&
    !pointers.current.left && !pointers.current.right && motion.current.isCentered(performance.now())
  const startAcquisition = async (byGamepad: boolean) => {
    if (acquisition.current || !foreground.current || !acquire.enabled || !isCenteredForAction()) return
    const request = new AbortController()
    acquisition.current = request
    usingGamepadControl.current = byGamepad
    try {
      await acquire.run(request.signal)
    } finally {
      if (acquisition.current === request) acquisition.current = null
    }
  }

  const acquireControl = () => { void startAcquisition(false) }
  const releaseControl = () => {
    resetInput()
    if (release.enabled) {
      usingGamepadControl.current = false
      void release.run()
    }
  }
  const takeOff = (byGamepad: boolean) => {
    if (foreground.current && takeoff?.enabled && isCenteredForAction()) {
      if (byGamepad) usingGamepadControl.current = true
      void takeoff.run()
    }
  }
  const landControl = () => {
    if (!land?.enabled) return
    resetInput()
    void land.run()
  }

  const cancelGamepadControl = useEffectEvent(() => {
    selectedPad.current = null
    buttonTracker.current.reset()
    input.current.resetSource('gamepad')
    if (motionSource.current === 'gamepad') {
      motion.current.reset()
      motionSource.current = null
    }
    if (!usingGamepadControl.current) return
    usingGamepadControl.current = false
    resetInput()
    if (acquisition.current) acquisition.current.abort()
    else void release.run()
  })

  const sample = useEffectEvent((now: number) => {
    let gamepads: Gamepad[] = []
    let gamepadApiAvailable = typeof navigator.getGamepads === 'function'
    try {
      gamepads = Array.from(navigator.getGamepads?.() ?? []).filter((pad): pad is Gamepad => Boolean(pad?.connected))
    } catch {
      gamepadApiAvailable = false
    }
    const boundPad = selectedPad.current
    const pad = boundPad
      ? gamepads.find((candidate) => candidate.index === boundPad.index && candidate.id === boundPad.id && isStandardGamepad(candidate))
      : gamepads.find(isStandardGamepad)
    if (boundPad && !pad) {
      cancelGamepadControl()
    } else if (pad && !boundPad) {
      selectedPad.current = { index: pad.index, id: pad.id }
      buttonTracker.current.reset()
      input.current.resetSource('gamepad')
    }
    setGamepadStatus(!gamepadApiAvailable ? 'Gamepad unavailable in this browser' :
      pad ? 'Gamepad connected' : gamepads.length ? 'Controller mapping unsupported' :
      'Press a button on the controller to connect')

    if (!foreground.current || !document.hasFocus() || document.hidden) return
    if (lastCanMove.current !== canMove || !motion.current.isFresh(now)) resetInput()
    lastCanMove.current = canMove

    const left = pointers.current.left
    const right = pointers.current.right
    const pointer = { leftX: left?.x ?? 0, leftY: left?.y ?? 0, rightX: right?.x ?? 0, rightY: right?.y ?? 0 }
    const keyboard = readKeyboardSticks(keys.current, profile)
    const gamepad = pad ? sticksForProfile(readGamepadSticks(pad.axes), profile) : centeredSticks
    const gamepadEngaged = !areSticksCentered(gamepad)
    const selected = input.current.sample({
      pointer: { sticks: pointer, engaged: Boolean(left || right) },
      keyboard: { sticks: keyboard, engaged: keys.current.size > 0 },
      gamepad: { sticks: gamepad, engaged: gamepadEngaged },
    })
    const allCentered = !left && !right && keys.current.size === 0 && !gamepadEngaged
    inputsCentered.current = allCentered
    setCentered(allCentered)
    motion.current.sample(selected.sticks, now)
    motionSource.current = selected.source
    setSticks((previous) => sameSticks(previous, selected.sticks) ? previous : selected.sticks)

    if (!pad) return
    const down = new Set(buttonNames.filter((button) => pad.buttons[controllerButtons[button]]?.pressed))
    const button = buttonTracker.current.sample(down, {
      Menu: held
        ? { id: 'release', enabled: release.enabled, holdMs: 0 }
        : { id: 'acquire', enabled: acquire.enabled && allCentered, holdMs },
      A: { id: 'takeoff', enabled: Boolean(takeoff?.enabled && allCentered), holdMs },
      B: { id: 'land', enabled: Boolean(land?.enabled), holdMs: 0 },
      LB: { id: 'pause', enabled: canMove, holdMs: 0 },
    }, now)
    if (button === 'Menu') {
      if (held) releaseControl()
      else void startAcquisition(true)
    }
    if (button === 'A') takeOff(true)
    if (button === 'B') landControl()
    if (button === 'LB') resetInput()
  })

  const send = useEffectEvent(() => {
    const focused = foreground.current && document.hasFocus() && !document.hidden
    const input = motion.current.current(focused ? performance.now() : Infinity, canMove)
    if (input) {
      if (!areSticksCentered(input)) usingGamepadControl.current = motionSource.current === 'gamepad'
      sendMotion(input)
    }
  })
  const reset = useEffectEvent(resetInput)
  const handleKeyDown = useEffectEvent((event: KeyboardEvent) => {
    if (!foreground.current || !canMove ||
      event.ctrlKey || event.altKey || event.metaKey ||
      (event.target instanceof HTMLElement &&
        event.target.closest('input, textarea, select, [contenteditable], [role="dialog"]'))) return
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key
    if (profile === 'rover' && key === 's') {
      event.preventDefault()
      resetInput()
      return
    }
    if (!(profile === 'quad' ? quadKeys : roverKeys).has(key)) return
    event.preventDefault()
    if (!event.repeat) keys.current.add(key)
  })
  const handleKeyUp = useEffectEvent((event: KeyboardEvent) => {
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key
    keys.current.delete(key)
  })

  useEffect(() => {
    foreground.current = !document.hidden && document.hasFocus()
    let frame: number
    const poll = (now: number) => {
      sample(now)
      frame = window.requestAnimationFrame(poll)
    }
    frame = window.requestAnimationFrame(poll)
    const timer = window.setInterval(send, mavlinkDriveRefreshMs)
    const blur = () => {
      foreground.current = false
      reset()
    }
    const focus = () => {
      foreground.current = !document.hidden && document.hasFocus()
    }
    const visibility = () => document.hidden ? blur() : focus()
    const keyDown = (event: KeyboardEvent) => handleKeyDown(event)
    const keyUp = (event: KeyboardEvent) => handleKeyUp(event)
    const disconnect = (event: GamepadEvent) => {
      if (selectedPad.current?.index === event.gamepad.index) {
        cancelGamepadControl()
      }
    }
    window.addEventListener('keydown', keyDown)
    window.addEventListener('keyup', keyUp)
    window.addEventListener('blur', blur)
    window.addEventListener('focus', focus)
    window.addEventListener('pagehide', blur)
    window.addEventListener('gamepaddisconnected', disconnect)
    document.addEventListener('visibilitychange', visibility)
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearInterval(timer)
      window.removeEventListener('keydown', keyDown)
      window.removeEventListener('keyup', keyUp)
      window.removeEventListener('blur', blur)
      window.removeEventListener('focus', focus)
      window.removeEventListener('pagehide', blur)
      window.removeEventListener('gamepaddisconnected', disconnect)
      document.removeEventListener('visibilitychange', visibility)
      foreground.current = false
      acquisition.current?.abort()
      reset()
    }
  }, [])

  const updatePointer = (side: StickSide, event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const radius = Math.min(bounds.width, bounds.height) / 2
    const x = profile === 'rover' && side === 'left' ? 0 : (event.clientX - bounds.left - bounds.width / 2) / radius
    const y = profile === 'rover' && side === 'right' ? 0 : (bounds.top + bounds.height / 2 - event.clientY) / radius
    const scale = Math.max(1, Math.hypot(x, y))
    pointers.current[side] = { id: event.pointerId, ...normalizeStick(x / scale, y / scale, 0) }
  }
  const finishPointer = (side: StickSide, event: PointerEvent<HTMLDivElement>) => {
    if (pointers.current[side]?.id !== event.pointerId) return
    delete pointers.current[side]
  }
  const renderStick = (side: StickSide, horizontal: string, vertical: string) => {
    const x = side === 'left' ? sticks.leftX : sticks.rightX
    const y = side === 'left' ? sticks.leftY : sticks.rightY
    return (
      <div className={`mavlink-controller-stick-group mavlink-controller-${side}`}>
        <div className="mavlink-controller-stick" role="group" aria-label={`${side} stick. ${vertical}${horizontal ? `, ${horizontal}` : ''}`}
          data-interactive={canMove}
          onPointerDown={(event) => {
            if (event.button !== 0 || !canMove || !foreground.current || pointers.current[side]) return
            event.preventDefault()
            event.currentTarget.setPointerCapture(event.pointerId)
            updatePointer(side, event)
          }}
          onPointerMove={(event) => {
            if (pointers.current[side]?.id === event.pointerId) updatePointer(side, event)
          }}
          onPointerUp={(event) => finishPointer(side, event)}
          onPointerCancel={(event) => {
            if (pointers.current[side]?.id === event.pointerId) resetInput()
          }}
          onLostPointerCapture={(event) => {
            if (pointers.current[side]?.id === event.pointerId) resetInput()
          }}
        >
          <span aria-hidden="true" className="mavlink-controller-thumb"
            style={{ transform: `translate(${x * 95}%, ${-y * 95}%)` }} />
        </div>
        <span>{vertical}{horizontal && <> · {horizontal}</>}</span>
      </div>
    )
  }

  return (
    <section className="mavlink-controller" aria-label={`${vehicleName} controller`}>
      <div className="mavlink-controller-header">
        <span role="status">{gamepadStatus}</span>
      </div>
      <div className="mavlink-controller-body">
        <button type="button" className="mavlink-controller-shoulder" disabled={!canMove} onClick={resetInput}>
          <kbd>LB</kbd> {profile === 'quad' ? 'Hover' : 'Stop'}
        </button>
        {renderStick('left', profile === 'quad' ? 'Yaw' : '', profile === 'quad' ? 'Climb / descend' : 'Forward / reverse')}
        <button type="button" className="mavlink-controller-menu"
          aria-label={`${held ? 'Release control' : acquire.label} for ${vehicleName}`}
          disabled={held ? !release.enabled : !acquire.enabled || !centered}
          onClick={held ? releaseControl : acquireControl}
        ><kbd>Menu</kbd> {held ? 'Release control' : acquire.label}</button>
        {(takeoff || land) && <div className="mavlink-controller-actions">
          {takeoff && (
            <button type="button" disabled={!takeoff.enabled || !centered} onClick={() => takeOff(false)}><kbd>A</kbd> {takeoff.label}</button>
          )}
          {land && <button type="button" disabled={!land.enabled} onClick={landControl}><kbd>B</kbd> {land.label}</button>}
        </div>}
        {renderStick('right', profile === 'quad' ? 'Move left / right' : '', profile === 'quad' ? 'Move forward / back' : 'Steer')}
      </div>
      <div className="mavlink-controller-footer">
        <span>{held ? 'Control' : 'View only'}{owner && ` · Controller ${owner}`}{status && ` · ${status}`}</span>
        <span>{profile === 'quad' ? 'WASD move · R/F climb and descend · Q/E yaw' : 'Arrow keys drive · S stops'}</span>
        {gamepadStatus === 'Gamepad connected' && (
          <span>Hold Menu to acquire{profile === 'quad' && ' · Hold A to take off'}</span>
        )}
      </div>
    </section>
  )
}
