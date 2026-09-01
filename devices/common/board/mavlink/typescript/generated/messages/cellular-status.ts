import {MAVLinkMessage} from '../../runtime';
import {readInt64LE, readUInt64LE} from '../../runtime';
import {CellularStatusFlag} from '../enums/cellular-status-flag';
import {CellularNetworkFailedReason} from '../enums/cellular-network-failed-reason';
import {CellularNetworkRadioType} from '../enums/cellular-network-radio-type';
/*
Cellular network status as reported by a particular modem.

// This is primarily intended for logging, but a GCS may choose to display link_tx_rate and link_rx_rate.

// Note that a value of 0 in the id field indicates that the sender does not support reporting of multiple modems.
// Message data should be from a single modem, but that is not guaranteed.
*/
// status Cellular modem status uint8_t
// failure_reason Failure reason when status in in CELLULAR_STATUS_FLAG_FAILED uint8_t
// type Cellular network radio type: gsm, cdma, lte... uint8_t
// quality Signal quality in percent. If unknown, set to UINT8_MAX uint8_t
// mcc Mobile country code. If unknown, set to UINT16_MAX uint16_t
// mnc Mobile network code. If unknown, set to UINT16_MAX uint16_t
// lac Location area code. If unknown, set to 0 uint16_t
// id Cellular modem instance number. Indexed from 1. uint8_t
// link_tx_rate Download rate. uint32_t
// link_rx_rate Upload rate. uint32_t
// cell_tower_id ID of the currently connected cell tower. This must be NULL terminated if the length is less than 9 human-readable chars, and without the null termination (NULL) byte if the length is exactly 9 chars. char
// band_number LTE frequency band number. uint8_t
// band_frequency LTE radio frequency. float
// channel_number The channel number (CN). Absolute radio-frequency (ARFCN) / E-UTRA (EARFCN) / UTRA (UARFCN) / New radio (NR_CH). uint32_t
// rx_level On 3G is Received Signal Code Power (RSCP). On LTE is Reference Signal Received Power (RSRP). On 5G is New Radio Reference Signal Received Power (NR_RSRP). float
// tx_level Transmitter (modem) signal absolute power level. float
// rx_quality On 3G is Receiver Quality (RxQual). On LTE is Reference Signal Received Quality (RSRQ). On 5G is New Radio Reference Signal Received Quality (NR_RSRQ). float
// sinr Signal to interference plus noise ratio (SINR). float
export class CellularStatus extends MAVLinkMessage {
	public status!: CellularStatusFlag;
	public failure_reason!: CellularNetworkFailedReason;
	public type!: CellularNetworkRadioType;
	public quality!: number;
	public mcc!: number;
	public mnc!: number;
	public lac!: number;
	public id!: number;
	public link_tx_rate!: number;
	public link_rx_rate!: number;
	public cell_tower_id!: string;
	public band_number!: number;
	public band_frequency!: number;
	public channel_number!: number;
	public rx_level!: number;
	public tx_level!: number;
	public rx_quality!: number;
	public sinr!: number;
	public _message_id: number = 334;
	public _message_name: string = 'CELLULAR_STATUS';
	public _crc_extra: number = 72;
	public _message_fields: [string, string, boolean][] = [
		['mcc', 'uint16_t', false],
		['mnc', 'uint16_t', false],
		['lac', 'uint16_t', false],
		['status', 'uint8_t', false],
		['failure_reason', 'uint8_t', false],
		['type', 'uint8_t', false],
		['quality', 'uint8_t', false],
		['id', 'uint8_t', true],
		['link_tx_rate', 'uint32_t', true],
		['link_rx_rate', 'uint32_t', true],
		['cell_tower_id', 'char', true],
		['band_number', 'uint8_t', true],
		['band_frequency', 'float', true],
		['channel_number', 'uint32_t', true],
		['rx_level', 'float', true],
		['tx_level', 'float', true],
		['rx_quality', 'float', true],
		['sinr', 'float', true],
	];
}