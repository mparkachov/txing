import type {
  DeviceDetailRenderProps,
  DeviceWebAdapter,
} from '../../../office/src/device-adapter'
import { extractPowerReportedState } from './power-model'

type PowerPanelProps = Pick<DeviceDetailRenderProps, 'shadow'>
type PowerPanelElement = ReturnType<DeviceWebAdapter['renderDetail']>

function PowerPanel({ shadow }: PowerPanelProps) {
  const reportedState = extractPowerReportedState(shadow)

  return createPowerElement(
    'section',
    { className: 'power-device-panel', 'aria-label': 'Power device status' },
    createPowerElement(
      'div',
      { className: 'power-device-grid' },
      createMetric(
        'Battery',
        reportedState.batteryMv === null ? '--' : `${reportedState.batteryMv} mV`,
      ),
    ),
  )
}

const createMetric = (label: string, value: string) =>
  createPowerElement(
    'div',
    { className: 'power-device-metric' },
    createPowerElement('span', { className: 'power-device-metric-label' }, label),
    createPowerElement('span', { className: 'power-device-metric-value' }, value),
  )

type PowerElementType = string | ((props: Record<string, unknown>) => PowerPanelElement)

const createPowerElement = (
  type: PowerElementType,
  props: Record<string, unknown> | null,
  ...children: unknown[]
): PowerPanelElement =>
  ({
    $$typeof: Symbol.for('react.transitional.element'),
    type,
    key: null,
    props: {
      ...(props ?? {}),
      ...(children.length === 0
        ? {}
        : { children: children.length === 1 ? children[0] : children }),
    },
    _owner: null,
    _store: {},
  }) as PowerPanelElement

export default PowerPanel
