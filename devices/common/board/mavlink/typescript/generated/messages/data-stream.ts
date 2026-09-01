import {MAVLinkMessage} from '../../runtime';
import {readInt64LE, readUInt64LE} from '../../runtime';
import {MavDataStream} from '../enums/mav-data-stream';
/*
Data stream status information.
*/
// stream_id The ID of the requested data stream. uint8_t
// message_rate The message rate uint16_t
// on_off 1 stream is enabled, 0 stream is stopped. uint8_t
export class DataStream extends MAVLinkMessage {
	public stream_id!: MavDataStream;
	public message_rate!: number;
	public on_off!: number;
	public _message_id: number = 67;
	public _message_name: string = 'DATA_STREAM';
	public _crc_extra: number = 21;
	public _message_fields: [string, string, boolean][] = [
		['message_rate', 'uint16_t', false],
		['stream_id', 'uint8_t', false],
		['on_off', 'uint8_t', false],
	];
}