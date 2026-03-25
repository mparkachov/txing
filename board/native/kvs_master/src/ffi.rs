use crate::emit_marker;
use anyhow::{Context, Result, anyhow};
use std::ffi::{CStr, CString, c_void};
use std::os::raw::{c_char, c_int};
use std::ptr;
use std::sync::Mutex;

#[repr(C)]
struct txing_kvs_handle {
    _private: [u8; 0],
}

#[repr(C)]
struct txing_kvs_callbacks {
    user_data: *mut c_void,
    on_ready: Option<extern "C" fn(*mut c_void)>,
    on_viewer_count_changed: Option<extern "C" fn(*mut c_void, *const c_char, u32, bool)>,
    on_error: Option<extern "C" fn(*mut c_void, *const c_char)>,
}

#[repr(C)]
struct txing_kvs_config {
    region: *const c_char,
    channel_name: *const c_char,
    client_id: *const c_char,
    video_bitrate_bps: u32,
    access_key_id: *const c_char,
    secret_access_key: *const c_char,
    session_token: *const c_char,
}

unsafe extern "C" {
    fn txing_kvs_create(
        config: *const txing_kvs_config,
        callbacks: *const txing_kvs_callbacks,
        out_handle: *mut *mut txing_kvs_handle,
    ) -> c_int;
    fn txing_kvs_start(handle: *mut txing_kvs_handle) -> c_int;
    fn txing_kvs_push_h264_au(
        handle: *mut txing_kvs_handle,
        data: *const u8,
        len: usize,
        presentation_ts_100ns: u64,
        duration_100ns: u64,
        is_keyframe: bool,
    ) -> c_int;
    fn txing_kvs_stop(handle: *mut txing_kvs_handle);
    fn txing_kvs_destroy(handle: *mut txing_kvs_handle);
}

#[derive(Debug, Clone)]
pub struct KvsConfig {
    pub region: String,
    pub channel_name: String,
    pub client_id: String,
    pub video_bitrate_bps: u32,
    pub access_key_id: String,
    pub secret_access_key: String,
    pub session_token: Option<String>,
}

struct CallbackState {
    fatal_error: Mutex<Option<String>>,
}

pub struct KvsMaster {
    handle: *mut txing_kvs_handle,
    callback_state: *mut CallbackState,
}

impl KvsMaster {
    pub fn new(config: &KvsConfig) -> Result<Self> {
        let region =
            CString::new(config.region.clone()).context("region must not contain NUL bytes")?;
        let channel_name = CString::new(config.channel_name.clone())
            .context("channel name must not contain NUL bytes")?;
        let client_id = CString::new(config.client_id.clone())
            .context("client id must not contain NUL bytes")?;
        let access_key_id = CString::new(config.access_key_id.clone())
            .context("access key id must not contain NUL bytes")?;
        let secret_access_key = CString::new(config.secret_access_key.clone())
            .context("secret access key must not contain NUL bytes")?;
        let session_token = config
            .session_token
            .as_ref()
            .map(|value| CString::new(value.as_str()))
            .transpose()
            .context("session token must not contain NUL bytes")?;

        let callback_state = Box::into_raw(Box::new(CallbackState {
            fatal_error: Mutex::new(None),
        }));
        let callbacks = txing_kvs_callbacks {
            user_data: callback_state.cast(),
            on_ready: Some(on_ready),
            on_viewer_count_changed: Some(on_viewer_count_changed),
            on_error: Some(on_error),
        };
        let raw_config = txing_kvs_config {
            region: region.as_ptr(),
            channel_name: channel_name.as_ptr(),
            client_id: client_id.as_ptr(),
            video_bitrate_bps: config.video_bitrate_bps,
            access_key_id: access_key_id.as_ptr(),
            secret_access_key: secret_access_key.as_ptr(),
            session_token: session_token
                .as_ref()
                .map_or(ptr::null(), |value| value.as_ptr()),
        };
        let mut handle = ptr::null_mut();

        let status = unsafe { txing_kvs_create(&raw_config, &callbacks, &mut handle) };
        if status != 0 || handle.is_null() {
            unsafe {
                drop(Box::from_raw(callback_state));
            }
            return Err(anyhow!("txing_kvs_create failed with status {status}"));
        }

        Ok(Self {
            handle,
            callback_state,
        })
    }

    pub fn start(&mut self) -> Result<()> {
        let status = unsafe { txing_kvs_start(self.handle) };
        if status != 0 {
            return Err(anyhow!("txing_kvs_start failed with status {status}"));
        }
        Ok(())
    }

    pub fn push_h264_access_unit(
        &self,
        access_unit: &[u8],
        presentation_ts_100ns: u64,
        duration_100ns: u64,
        is_keyframe: bool,
    ) -> Result<()> {
        let status = unsafe {
            txing_kvs_push_h264_au(
                self.handle,
                access_unit.as_ptr(),
                access_unit.len(),
                presentation_ts_100ns,
                duration_100ns,
                is_keyframe,
            )
        };
        if status != 0 {
            return Err(anyhow!(
                "txing_kvs_push_h264_au failed with status {status}"
            ));
        }
        Ok(())
    }

    pub fn stop(&mut self) {
        if self.handle.is_null() {
            return;
        }
        unsafe {
            txing_kvs_stop(self.handle);
        }
    }

    pub fn take_fatal_error(&self) -> Option<String> {
        let state = unsafe { &*self.callback_state };
        state
            .fatal_error
            .lock()
            .ok()
            .and_then(|mut guard| guard.take())
    }
}

impl Drop for KvsMaster {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe {
                txing_kvs_stop(self.handle);
                txing_kvs_destroy(self.handle);
            }
            self.handle = ptr::null_mut();
        }
        if !self.callback_state.is_null() {
            unsafe {
                drop(Box::from_raw(self.callback_state));
            }
            self.callback_state = ptr::null_mut();
        }
    }
}

extern "C" fn on_ready(_user_data: *mut c_void) {
    emit_marker("TXING_KVS_READY", &[]);
}

extern "C" fn on_viewer_count_changed(
    _user_data: *mut c_void,
    client_id: *const c_char,
    viewers: u32,
    connected: bool,
) {
    let client_id = c_string_or_unknown(client_id);
    if connected {
        emit_marker(
            "TXING_VIEWER_CONNECTED",
            &[("clientId", &client_id), ("viewers", &viewers.to_string())],
        );
    } else {
        emit_marker(
            "TXING_VIEWER_DISCONNECTED",
            &[("clientId", &client_id), ("viewers", &viewers.to_string())],
        );
    }
}

extern "C" fn on_error(user_data: *mut c_void, detail: *const c_char) {
    let detail = c_string_or_unknown(detail);
    let state = unsafe { &*(user_data.cast::<CallbackState>()) };
    if let Ok(mut guard) = state.fatal_error.lock() {
        if guard.is_none() {
            *guard = Some(detail.clone());
        }
    }
    emit_marker("TXING_KVS_ERROR", &[("detail", &detail)]);
}

fn c_string_or_unknown(pointer: *const c_char) -> String {
    if pointer.is_null() {
        return "unknown".to_string();
    }
    unsafe { CStr::from_ptr(pointer) }
        .to_string_lossy()
        .into_owned()
}

#[cfg(test)]
mod tests {
    use super::{KvsConfig, KvsMaster};

    #[cfg(not(target_os = "linux"))]
    #[test]
    fn stub_shim_smoke_test() {
        let mut master = KvsMaster::new(&KvsConfig {
            region: "eu-central-1".to_string(),
            channel_name: "txing-board-video".to_string(),
            client_id: "smoke-test".to_string(),
            video_bitrate_bps: 8_000_000,
            access_key_id: "stub-access-key".to_string(),
            secret_access_key: "stub-secret-key".to_string(),
            session_token: None,
        })
        .expect("create should succeed");

        master.start().expect("start should succeed");
        master
            .push_h264_access_unit(&[0x00, 0x00, 0x00, 0x01, 0x65, 0x80], 0, 333_333, true)
            .expect("push should succeed");
        master.stop();
        assert!(master.take_fatal_error().is_none());
    }
}
