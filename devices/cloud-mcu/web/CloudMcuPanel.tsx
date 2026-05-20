import type {
  DeviceDetailRenderProps,
  DeviceWebAdapter,
} from '../../../web/src/device-adapter'
import { extractCloudMcuReportedState } from './cloud-mcu-model'

type CloudMcuPanelProps = Pick<DeviceDetailRenderProps, 'shadow'>
type CloudMcuPanelElement = ReturnType<DeviceWebAdapter['renderDetail']>

function CloudMcuPanel({ shadow }: CloudMcuPanelProps) {
  const reportedState = extractCloudMcuReportedState(shadow)

  return createCloudMcuElement(
    'section',
    { className: 'power-device-panel', 'aria-label': 'Cloud MCU status' },
    createCloudMcuElement(
      'div',
      { className: 'power-device-grid' },
      createMetric(
        'Target',
        reportedState.desiredRedcon === null ? '--' : `REDCON ${reportedState.desiredRedcon}`,
      ),
      createMetric(
        'Power',
        reportedState.powered === null ? '--' : reportedState.powered ? 'on' : 'off',
      ),
      createMetric('ECS', reportedState.ecsTaskStatus ?? '--'),
    ),
  )
}

const createMetric = (label: string, value: string) =>
  createCloudMcuElement(
    'div',
    { className: 'power-device-metric' },
    createCloudMcuElement('span', { className: 'power-device-metric-label' }, label),
    createCloudMcuElement('span', { className: 'power-device-metric-value' }, value),
  )

type CloudMcuElementType =
  | string
  | ((props: Record<string, unknown>) => CloudMcuPanelElement)

const createCloudMcuElement = (
  type: CloudMcuElementType,
  props: Record<string, unknown> | null,
  ...children: unknown[]
): CloudMcuPanelElement =>
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
  }) as CloudMcuPanelElement

export default CloudMcuPanel
