#if defined(PAUSED_PACKET_EXTRACT) && CONFIG_IDF_TARGET_ESP32
#include "paused_calibration.h"
#include "esp_memory_utils.h"
static bool paused_nonaperture(const void *p, size_t n) {
    uintptr_t a=(uintptr_t)p, b=a+n-1;
    return p && n && b>=a && esp_ptr_in_dram(p) && esp_ptr_in_dram((void *)b) &&
        (b<0x3ffe8000 || a>=0x3fff8000);
}
bool paused_calibration_begin(paused_calibration *s) {
    if (!paused_nonaperture(s,sizeof(*s)) || s->handle) return false;
    _lock_t lock=phy_get_lock();
    /* Existing initialized handle only. Never lazily initialize a copied0. */
    if (!paused_nonaperture((void *)lock,1) || _lock_try_acquire(&lock)) return false;
    if (!calibrated || memcmp(phy_rxbb_dc,calibrated_rxbb_dc,RXBB_DC_BYTES) ||
        memcmp(phy_rxrf_dc,calibrated_rxrf_dc,RXRF_DC_BYTES)) {
        _lock_release(&lock); return false;
    }
    memcpy(s->before,phy_rxbb_dc,RXBB_DC_BYTES);
    memcpy(s->before+RXBB_DC_BYTES,phy_rxrf_dc,RXRF_DC_BYTES);
    s->handle=(uintptr_t)lock;
    return true;
}
bool paused_calibration_end(paused_calibration *s) {
    if (!s || !s->handle) return false;
    memcpy(s->after,phy_rxbb_dc,RXBB_DC_BYTES);
    memcpy(s->after+RXBB_DC_BYTES,phy_rxrf_dc,RXRF_DC_BYTES);
    bool same=!memcmp(s->before,s->after,sizeof(s->before));
    _lock_t lock=(_lock_t)s->handle; s->handle=0;
    _lock_release(&lock);
    return same;
}
#endif
