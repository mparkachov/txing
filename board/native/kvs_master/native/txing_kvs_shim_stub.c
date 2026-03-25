#include "txing_kvs_shim.h"

#include <stdlib.h>
#include <string.h>

struct txing_kvs_handle {
    txing_kvs_callbacks callbacks;
    bool started;
};

int txing_kvs_create(const txing_kvs_config* config, const txing_kvs_callbacks* callbacks, txing_kvs_handle** out_handle)
{
    txing_kvs_handle* handle;

    if (config == NULL || callbacks == NULL || out_handle == NULL) {
        return -1;
    }

    handle = (txing_kvs_handle*) calloc(1, sizeof(*handle));
    if (handle == NULL) {
        return -2;
    }

    memcpy(&handle->callbacks, callbacks, sizeof(*callbacks));
    *out_handle = handle;
    return 0;
}

int txing_kvs_start(txing_kvs_handle* handle)
{
    if (handle == NULL) {
        return -1;
    }

    handle->started = true;
    if (handle->callbacks.on_ready != NULL) {
        handle->callbacks.on_ready(handle->callbacks.user_data);
    }
    return 0;
}

int txing_kvs_push_h264_au(
    txing_kvs_handle* handle,
    const uint8_t* data,
    size_t len,
    uint64_t presentation_ts_100ns,
    uint64_t duration_100ns,
    bool is_keyframe)
{
    (void) data;
    (void) len;
    (void) presentation_ts_100ns;
    (void) duration_100ns;
    (void) is_keyframe;

    if (handle == NULL || !handle->started) {
        return -1;
    }

    return 0;
}

void txing_kvs_stop(txing_kvs_handle* handle)
{
    if (handle == NULL) {
        return;
    }

    handle->started = false;
}

void txing_kvs_destroy(txing_kvs_handle* handle)
{
    free(handle);
}
