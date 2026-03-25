#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AccessUnit {
    pub bytes: Vec<u8>,
    pub is_keyframe: bool,
}

#[derive(Debug, Default)]
pub struct AnnexBAccessUnitParser {
    pending: Vec<u8>,
    current: Vec<u8>,
    current_has_vcl: bool,
    current_is_keyframe: bool,
}

impl AnnexBAccessUnitParser {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(&mut self, chunk: &[u8]) -> Vec<AccessUnit> {
        self.pending.extend_from_slice(chunk);
        let mut output = Vec::new();
        let nals = extract_complete_nals(&mut self.pending);
        for nal in nals {
            self.push_nal(&nal, &mut output);
        }
        output
    }

    pub fn finish(&mut self) -> Vec<AccessUnit> {
        let mut output = Vec::new();
        if let Some(trailing) = take_trailing_nal(&mut self.pending) {
            self.push_nal(&trailing, &mut output);
        }
        self.flush_current(&mut output);
        output
    }

    fn push_nal(&mut self, nal: &[u8], output: &mut Vec<AccessUnit>) {
        let Some(payload) = nal_payload(nal) else {
            return;
        };
        let nal_type = payload[0] & 0x1f;
        let is_vcl = (1..=5).contains(&nal_type);

        if nal_type == 9 {
            self.flush_current(output);
            return;
        }

        if is_vcl && self.current_has_vcl && first_mb_in_slice_is_zero(payload) {
            self.flush_current(output);
        } else if !is_vcl && self.current_has_vcl && matches!(nal_type, 6 | 7 | 8) {
            self.flush_current(output);
        }

        self.current.extend_from_slice(nal);
        if is_vcl {
            self.current_has_vcl = true;
            if nal_type == 5 {
                self.current_is_keyframe = true;
            }
        }
    }

    fn flush_current(&mut self, output: &mut Vec<AccessUnit>) {
        if self.current_has_vcl && !self.current.is_empty() {
            output.push(AccessUnit {
                bytes: std::mem::take(&mut self.current),
                is_keyframe: self.current_is_keyframe,
            });
        } else {
            self.current.clear();
        }

        self.current_has_vcl = false;
        self.current_is_keyframe = false;
    }
}

fn extract_complete_nals(pending: &mut Vec<u8>) -> Vec<Vec<u8>> {
    if pending.is_empty() {
        return Vec::new();
    }

    let Some((first_start, _)) = find_start_code(pending, 0) else {
        if pending.len() > 4 {
            let keep_from = pending.len() - 4;
            pending.drain(..keep_from);
        }
        return Vec::new();
    };

    if first_start > 0 {
        pending.drain(..first_start);
    }

    let mut starts = Vec::new();
    let mut index = 0;
    while let Some((start, prefix_len)) = find_start_code(pending, index) {
        starts.push((start, prefix_len));
        index = start + prefix_len;
    }

    if starts.len() < 2 {
        return Vec::new();
    }

    let mut nals = Vec::with_capacity(starts.len() - 1);
    for window in starts.windows(2) {
        let start = window[0].0;
        let end = window[1].0;
        nals.push(pending[start..end].to_vec());
    }

    let tail_start = starts
        .last()
        .map(|(start, _)| *start)
        .expect("tail_start requires at least one start code");
    let remainder = pending[tail_start..].to_vec();
    *pending = remainder;
    nals
}

fn take_trailing_nal(pending: &mut Vec<u8>) -> Option<Vec<u8>> {
    let (start, prefix_len) = find_start_code(pending, 0)?;
    if start != 0 || pending.len() <= prefix_len {
        pending.clear();
        return None;
    }
    Some(std::mem::take(pending))
}

fn nal_payload(nal: &[u8]) -> Option<&[u8]> {
    let (_, prefix_len) = find_start_code(nal, 0)?;
    nal.get(prefix_len..)
}

fn find_start_code(data: &[u8], from: usize) -> Option<(usize, usize)> {
    if data.len() < 4 || from >= data.len().saturating_sub(3) {
        return None;
    }

    let mut index = from;
    while index + 3 < data.len() {
        if data[index] == 0 && data[index + 1] == 0 {
            if data[index + 2] == 1 {
                return Some((index, 3));
            }
            if index + 3 < data.len() && data[index + 2] == 0 && data[index + 3] == 1 {
                return Some((index, 4));
            }
        }
        index += 1;
    }
    None
}

fn first_mb_in_slice_is_zero(payload: &[u8]) -> bool {
    if payload.len() < 2 {
        return false;
    }

    let rbsp = remove_emulation_prevention_bytes(&payload[1..]);
    let mut reader = BitReader::new(&rbsp);
    matches!(reader.read_ue(), Some(0))
}

fn remove_emulation_prevention_bytes(payload: &[u8]) -> Vec<u8> {
    let mut rbsp = Vec::with_capacity(payload.len());
    let mut zero_run = 0_u8;

    for byte in payload {
        if zero_run >= 2 && *byte == 0x03 {
            zero_run = 0;
            continue;
        }
        rbsp.push(*byte);
        if *byte == 0 {
            zero_run = zero_run.saturating_add(1);
        } else {
            zero_run = 0;
        }
    }

    rbsp
}

struct BitReader<'a> {
    bytes: &'a [u8],
    bit_offset: usize,
}

impl<'a> BitReader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self {
            bytes,
            bit_offset: 0,
        }
    }

    fn read_bit(&mut self) -> Option<u8> {
        let byte = *self.bytes.get(self.bit_offset / 8)?;
        let shift = 7 - (self.bit_offset % 8);
        self.bit_offset += 1;
        Some((byte >> shift) & 0x01)
    }

    fn read_bits(&mut self, count: usize) -> Option<u32> {
        let mut value = 0_u32;
        for _ in 0..count {
            value = (value << 1) | u32::from(self.read_bit()?);
        }
        Some(value)
    }

    fn read_ue(&mut self) -> Option<u32> {
        let mut leading_zeros = 0_usize;
        while self.read_bit()? == 0 {
            leading_zeros += 1;
        }
        if leading_zeros == 0 {
            return Some(0);
        }
        let suffix = self.read_bits(leading_zeros)?;
        Some(((1_u32 << leading_zeros) - 1) + suffix)
    }
}

#[cfg(test)]
mod tests {
    use super::{AccessUnit, AnnexBAccessUnitParser};

    fn nal(bytes: &[u8]) -> Vec<u8> {
        let mut data = vec![0x00, 0x00, 0x00, 0x01];
        data.extend_from_slice(bytes);
        data
    }

    #[test]
    fn assembles_access_units_from_chunked_annex_b_stream() {
        let mut parser = AnnexBAccessUnitParser::new();
        let mut stream = Vec::new();
        stream.extend(nal(&[0x67, 0xaa]));
        stream.extend(nal(&[0x68, 0xbb]));
        stream.extend(nal(&[0x65, 0x80]));
        stream.extend(nal(&[0x41, 0x80]));

        let mut access_units = Vec::new();
        access_units.extend(parser.push(&stream[..11]));
        access_units.extend(parser.push(&stream[11..]));
        access_units.extend(parser.finish());

        assert_eq!(
            access_units,
            vec![
                AccessUnit {
                    bytes: [nal(&[0x67, 0xaa]), nal(&[0x68, 0xbb]), nal(&[0x65, 0x80])].concat(),
                    is_keyframe: true,
                },
                AccessUnit {
                    bytes: nal(&[0x41, 0x80]),
                    is_keyframe: false,
                },
            ]
        );
    }

    #[test]
    fn treats_aud_as_boundary() {
        let mut parser = AnnexBAccessUnitParser::new();
        let mut stream = Vec::new();
        stream.extend(nal(&[0x09, 0xf0]));
        stream.extend(nal(&[0x65, 0x80]));
        stream.extend(nal(&[0x09, 0xf0]));
        stream.extend(nal(&[0x41, 0x80]));

        let mut access_units = parser.push(&stream);
        access_units.extend(parser.finish());

        assert_eq!(access_units.len(), 2);
        assert!(access_units[0].is_keyframe);
        assert!(!access_units[1].is_keyframe);
    }
}
