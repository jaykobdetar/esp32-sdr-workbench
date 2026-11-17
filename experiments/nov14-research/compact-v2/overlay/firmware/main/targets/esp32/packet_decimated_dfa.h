/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef PACKET_DECIMATED_DFA_H
#define PACKET_DECIMATED_DFA_H
#include <stdint.h>
#include <stddef.h>
#define PKT_MAX_SAMPLES 16380u
#define PKT_MAX_RESULTS 64u
/* Input: one 32-bit word/sample, signed10 I in bits0..9 and hardware Q in10..19.
 * DSP convention is I-j*Q, matching protocol.decode_iq. No continuous-bank joins.
 * Fixed16MS/s,2Mbps,16-byte RFTX known source, unnormalized-pair-sum 2x decimation, local three-channel CFO correction.
 * Input lengths and address offsets stay in original16MS/s samples.
 * Report phase is even raw-sample phase; samples_processed counts decimated differences. */
typedef struct { uint32_t sequence, address_start_sample; uint8_t payload[16]; uint16_t air_crc; uint8_t phase; int8_t polarity; } pkt_record;
typedef struct {
 uint32_t shift[3], start; uint16_t crc, received_crc, collected; uint8_t payload[16], active, sync_state;
} pkt_lane;
typedef struct {
 pkt_lane lane[8]; int32_t ring[4], sum;
 int32_t cross_block[32], dot_block[32];
 uint32_t sync[3]; uint16_t prefix_crc;
} pkt_workspace;
typedef struct {
 uint32_t status, count, sync_hits, valid_hypotheses, duplicates, output_drops;
 uint32_t payload_rejects, crc_rejects, incomplete, busy_syncs, samples_processed;
 uint32_t differential_products, symbol_decisions;
 pkt_record records[PKT_MAX_RESULTS];
} pkt_result;
enum { PKT_OK=0, PKT_ARGUMENT=1, PKT_SENTINEL=2 };
/* Entire result fails closed on bad arguments/sentinel. Result overflow is
 * counted, not silent; CPU work remains bounded independent of output count.
 * Caller owns nonoverlapping workspace/result/input, no concurrent use. */
int pkt_decode(const uint32_t *words, size_t n, pkt_workspace *w, pkt_result *r, unsigned output_cap);
size_t pkt_workspace_size(void);
size_t pkt_result_size(void);
#endif
