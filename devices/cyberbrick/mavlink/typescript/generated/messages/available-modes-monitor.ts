import {MAVLinkMessage} from '../../runtime';
import {readInt64LE, readUInt64LE} from '../../runtime';
/*
A change to the sequence number indicates that the set of AVAILABLE_MODES has changed, and that the receiver should re-request all available modes.

// The message is optional, and is only needed when the set of modes can change dynamically after boot.
// It should be emitted whenever the set of modes change.
// It should be streamed at low rate (nominally 0.3 Hz).
// See https://mavlink.io/en/services/standard_modes.html
*/
// seq Sequence number. The value iterates sequentially whenever AVAILABLE_MODES changes (e.g. support for a new mode is added/removed dynamically). uint8_t
export class AvailableModesMonitor extends MAVLinkMessage {
	public seq!: number;
	public _message_id: number = 437;
	public _message_name: string = 'AVAILABLE_MODES_MONITOR';
	public _crc_extra: number = 30;
	public _message_fields: [string, string, boolean][] = [
		['seq', 'uint8_t', false],
	];
}