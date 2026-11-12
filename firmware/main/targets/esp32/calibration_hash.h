#pragma once

/* Observe the stored logical PHY record only. This command never calibrates,
 * initializes/erases NVS, writes keys, or reads unrelated credentials/cal_mac.
 * The digest is device-derived: keep it in private campaign records. */
#include <stdlib.h>
#include "nvs.h"
#include "esp_phy_init.h"
#include "sha/sha_parallel_engine.h"

static bool calibration_hash_command(const char *line) {
    if (strcmp(line, "CALHASH?")) return false;
    nvs_handle_t handle;
    esp_err_t error = nvs_open("phy", NVS_READONLY, &handle);
    if (error != ESP_OK) {
        reply("ERR calhash_open %d\n", (int)error);
        return true;
    }
    size_t size = 0;
    error = nvs_get_blob(handle, "cal_data", NULL, &size);
    if (error != ESP_OK || size != sizeof(esp_phy_calibration_data_t)) {
        nvs_close(handle);
        reply("ERR calhash_size %d\n", (int)error);
        return true;
    }
    unsigned char *data = malloc(size);
    if (!data) {
        nvs_close(handle);
        reply("ERR calhash_memory\n");
        return true;
    }
    size_t actual = size;
    error = nvs_get_blob(handle, "cal_data", data, &actual);
    nvs_close(handle);
    if (error != ESP_OK || actual != size) {
        free(data);
        reply("ERR calhash_read %d\n", (int)error);
        return true;
    }
    unsigned char digest[32];
    /* Pinned SDK's thread-safe SHA API. No TLS/network session runs here. */
    esp_sha(SHA2_256, data, size, digest);
    free(data);
    char hex[65];
    static const char digits[] = "0123456789abcdef";
    for (unsigned i = 0; i < sizeof(digest); ++i) {
        hex[2 * i] = digits[digest[i] >> 4];
        hex[2 * i + 1] = digits[digest[i] & 15];
    }
    hex[64] = 0;
    reply("CALHASH {\"version\":1,\"algorithm\":\"sha256\",\"bytes\":%u,\"sha256\":\"%s\",\"device_us\":%llu}\n",
          (unsigned)size, hex, (unsigned long long)esp_timer_get_time());
    return true;
}
