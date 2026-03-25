#ifndef TXING_KVS_SHIM_H
#define TXING_KVS_SHIM_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct txing_kvs_handle txing_kvs_handle;

typedef struct {
    void* user_data;
    void (*on_ready)(void* user_data);
    void (*on_viewer_count_changed)(void* user_data, const char* client_id, uint32_t viewers, bool connected);
    void (*on_error)(void* user_data, const char* detail);
} txing_kvs_callbacks;

typedef struct {
    const char* region;
    const char* channel_name;
    const char* client_id;
    uint32_t video_bitrate_bps;
    const char* access_key_id;
    const char* secret_access_key;
    const char* session_token;
} txing_kvs_config;

int txing_kvs_create(const txing_kvs_config* config, const txing_kvs_callbacks* callbacks, txing_kvs_handle** out_handle);
int txing_kvs_start(txing_kvs_handle* handle);
int txing_kvs_push_h264_au(
    txing_kvs_handle* handle,
    const uint8_t* data,
    size_t len,
    uint64_t presentation_ts_100ns,
    uint64_t duration_100ns,
    bool is_keyframe
);
void txing_kvs_stop(txing_kvs_handle* handle);
void txing_kvs_destroy(txing_kvs_handle* handle);

#ifdef __cplusplus
}
#endif

#endif
