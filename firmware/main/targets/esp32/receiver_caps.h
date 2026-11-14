#pragma once
/* Sized by the compiler, not reply()'s bounded printf scratch buffer. Keep the
 * complete line (including newline) even when every optional capability is on.
 * Included after pipeline_health.h defines DETPIPE_HEALTH_CAPABILITY. */
static const char receiver_caps[] =
    "CAPS DSTREAMIDLEWAKE DSTREAMIDLE DSTREAMIQ DSTREAM DUALTIMING BGPOLICY CALHASH "
    DETPIPE_HEALTH_CAPABILITY
    "PIPEKEEP PIPECOPY ACQOPT CLEAROPT PIPEKERNEL DET1 VERSION GPIO SPEC SPECN SPECCAPS SPECSTAT DCT "
#if !CONFIG_ESP_SDR_CP2102_VIEWER_COMPAT
    "UARTBAUD "
#endif
    "RXLIMITS SERIALLEASE TUNEEXT RX40 RX16 LPFANA GAIN HWAGC IQ8\n";
