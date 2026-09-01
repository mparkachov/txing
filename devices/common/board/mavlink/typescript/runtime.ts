// Handwritten runtime surface consumed by the pinned generated TypeScript
// definitions. It deliberately adds no npm package dependency to Office.

export abstract class MAVLinkMessage {
  public abstract readonly _crc_extra: number

  public constructor(
    public readonly system_id: number,
    public readonly component_id: number,
  ) {}
}

const asView = (bytes: Uint8Array): DataView =>
  new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)

export const readInt64LE = (bytes: Uint8Array, offset: number): number =>
  Number(asView(bytes).getBigInt64(offset, true))

export const readUInt64LE = (bytes: Uint8Array, offset: number): number =>
  Number(asView(bytes).getBigUint64(offset, true))
