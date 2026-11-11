#!/usr/bin/env python3
"""Offline integrity and decoded-test-packet checks; no radio/device access.

Checks published artifacts, not fresh IQ demodulation or packet recall.
Standard library only. Raises ValueError on inconsistency.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from statistics import mean
from pathlib import Path


def known_payload(sequence, length):
    return b"RFTX" + sequence.to_bytes(4, "little") + bytes(
        (k + sequence) & 255 for k in range(8, length)
    )


def radio_crc(data):
    """Nordic CRC16: init FFFF, poly 1021, LSB-first data, MSB-first CRC."""
    crc = 0xFFFF
    for byte in data:
        for shift in range(8):
            feedback = ((crc >> 15) & 1) ^ ((byte >> shift) & 1)
            crc = (crc << 1) & 0xFFFF
            if feedback:
                crc ^= 0x1021
    return f"{crc:04x}"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_packet(packet):
    observed = bytes.fromhex(packet["observed_payload_hex"])
    expected = known_payload(packet["sequence"], packet["length"])
    require(observed == expected, "Observed payload does not match test pattern")
    require(bytes.fromhex(packet["expected_payload_hex"]) == expected,
            "Saved expected payload does not match test pattern")
    require(len(observed) == packet["length"], "Payload length mismatch")
    require(packet["address_hex"] == "efcdab89c3", "Test address mismatch")
    crc = radio_crc(bytes.fromhex(packet["address_hex"]) +
                    bytes([packet["length"]]) + observed)
    require(crc == packet["crc_computed"] == packet["crc_received_msb_first"],
            "RF CRC mismatch")
    require(packet["full_known_payload_match"] and packet["address_verified"]
            and packet["crc_verified"], "Missing full-frame validation flags")



def close(actual, expected, message):
    require(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9), message)


def recompute_headlines(records, abab, retention):
    """Recompute point estimates only; saved bootstrap intervals are not rerun."""
    phase_results = {}
    for phase in abab["phases"]:
        name = phase["phase"]
        rows = [r for r in records
                if r["recording"].startswith("nrf-abab/" + name + "/")]
        require(len(rows) == phase["runs"] == 8, "ABAB phase size mismatch")
        pairs = {}
        states = {}
        for on in (True, False):
            rr = [r for r in rows if r["tx_on"] is on]
            require(len(rr) == 4, "ABAB state size mismatch")
            metrics = []
            for r in rr:
                summary = r["receiver_summary"]
                aperture_s = summary["total_samples"] / summary["sample_rate_hz"]
                values = {
                    "candidate_rate": summary["detections"] * 1e6 / summary["wall_elapsed_us"],
                    "local_rf_duty": 100 * aperture_s * 1e6 / summary["wall_elapsed_us"],
                    "host_rf_duty": 100 * aperture_s * 1e6 / summary["host_total_elapsed_us"],
                }
                pair_key = (r["source_metadata"]["pair"], on)
                require(pair_key not in pairs, "Duplicate ABAB pair")
                pairs[pair_key] = values["candidate_rate"]
                metrics.append(values)
            state = "on" if on else "off"
            states[state] = {k: mean(v[k] for v in metrics) for k in metrics[0]}
            for key, value in states[state].items():
                saved = phase["states"][state][key]
                require(saved["n"] == 4, "ABAB saved state size mismatch")
                close(value, saved["mean"], "ABAB " + key + " mismatch")
                for observed, expected in zip(
                        sorted(v[key] for v in metrics), sorted(saved["values"])):
                    close(observed, expected, "ABAB per-run " + key + " mismatch")
        pair_ids = sorted({pair for pair, on in pairs})
        require(len(pair_ids) == 4, "ABAB pair count mismatch")
        deltas = [pairs[(pair, True)] - pairs[(pair, False)] for pair in pair_ids]
        close(mean(deltas), phase["paired_candidate_excess"]["mean"],
              "ABAB paired candidate excess mismatch")
        for actual, expected in zip(deltas, phase["paired_candidate_excess"]["values"]):
            close(actual, expected, "ABAB pair excess mismatch")
        phase_results[name] = {"states": states, "candidate_excess_per_second": mean(deltas)}
    cycles = []
    for saved in abab["cycle_effects"]:
        cycle = saved["cycle"]
        excess = (phase_results[f"optimized-{cycle}"]["candidate_excess_per_second"] -
                  phase_results[f"historical-{cycle}"]["candidate_excess_per_second"])
        close(excess, saved["optimized_minus_historical_excess_per_second"],
              "ABAB cycle excess mismatch")
        cycles.append({"cycle": cycle, "optimized_minus_historical_excess_per_second": excess})
    headline_duty = {
        kind: {metric: mean(phase_results[f"{kind}-{cycle}"]["states"]["on"][metric]
                            for cycle in (1, 2))
               for metric in ("local_rf_duty", "host_rf_duty")}
        for kind in ("historical", "optimized")
    }
    retention_rows = [r for r in records if r["recording"].startswith("nrf-retention/")]
    require(len(retention_rows) == 48, "Retention size mismatch")
    policy_results = {}
    paired = {}
    for group in retention["groups"]:
        mode, on = group["mode"], group["tx_on"]
        rows = [r for r in retention_rows if r["mode"] == mode and r["tx_on"] is on]
        require(len(rows) == group["n"] == 12, "Retention group size mismatch")
        valid = sum(r["full_address_payload_rf_crc_count"] > 0 for r in rows)
        require(valid == group["full_crc"], "Retention full-frame count mismatch")
        if on:
            policy_results[mode] = {"full_crc": valid, "n": len(rows)}
            for r in rows:
                key = (r["source_metadata"]["pair"], mode)
                require(key not in paired, "Duplicate retention pair")
                paired[key] = r["full_address_payload_rf_crc_count"] > 0
    pair_ids = sorted({p for p, mode in paired})
    require(len(pair_ids) == 12, "Retention pair count mismatch")
    delta = []
    for p in pair_ids:
        strongest = paired[(p, "strongest")]
        reservoir = paired[(p, "reservoir")]
        saved = next(row for row in retention["pairs"] if row["pair"] == p)
        require(strongest == saved["strongest_crc"] and reservoir == saved["reservoir_crc"],
                "Retention paired result mismatch")
        delta.append(int(reservoir) - int(strongest))
    difference = mean(delta)
    close(difference, retention["paired_crc_difference"], "Retention paired difference mismatch")
    require(delta.count(1) == retention["discordant_reservoir_only"] and
            delta.count(-1) == retention["discordant_strongest_only"],
            "Retention discordant pair count mismatch")
    return {"abab_on_duty_percent": headline_duty, "abab_cycle_effects": cycles,
            "retention_on": policy_results, "retention_paired_difference": difference,
            "bootstrap_intervals_recomputed": False}


def verify(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    for item in manifest["files"]:
        name = item["file"]
        require(Path(name).name == name, "Invalid artifact filename")
        data = (directory / name).read_bytes()
        require(hashlib.sha256(data).hexdigest() == item["sha256"],
                f"Artifact checksum mismatch: {name}")
        require(len(data) == item["bytes"], f"Artifact size mismatch: {name}")
    records = json.loads((directory / "recordings.json").read_text())
    packets = json.loads((directory / "known-packets.json").read_text())
    totals = json.loads((directory / "campaign-totals.json").read_text())
    by_id = {r["recording"]: r for r in records}
    require(len(records) == len(by_id) == 550, "Expected 550 unique recordings")
    require(all(r["transport_crc_valid"] is True for r in records),
            "Transport CRC report mismatch")
    counts = Counter()
    for packet in packets:
        verify_packet(packet)
        require(packet["recording"] in by_id, "Unknown packet recording")
        require(by_id[packet["recording"]]["tx_on"] is True,
                "Known packet unexpectedly labeled TX OFF")
        counts[packet["recording"]] += 1
    require(len(counts) == 25, "Expected 25 RF-validated recordings")
    for record in records:
        require(counts[record["recording"]] ==
                record["full_address_payload_rf_crc_count"],
                "Recording RF validation count mismatch")
        require(record["iq_bytes"] == record["metrics"]["samples"] * 8,
                "cf32_le byte count mismatch")
        expected_us = record["metrics"]["samples"] / record["sample_rate_hz"] * 1e6
        require(abs(expected_us - record["metrics"]["aperture_us"]) < 1e-8,
                "Nominal aperture mismatch")
    for total in totals:
        group = [r for r in records
                 if r["recording"].split("/")[0] == total["campaign"]]
        require(total["recordings"] == len(group), "Campaign count mismatch")
        require(total["transport_crc_valid"] ==
                sum(r["transport_crc_valid"] for r in group),
                "Campaign transport count mismatch")
        require(total["rf_crc_valid_recordings"] ==
                sum(bool(counts[r["recording"]]) for r in group),
                "Campaign RF count mismatch")
    headlines = recompute_headlines(
        records,
        json.loads((directory / "abab-comparison.json").read_text())["results"],
        json.loads((directory / "retention-comparison.json").read_text())["results"])
    return {"headlines": headlines, "recordings": len(records), "transport_crc_valid": 550,
            "rf_crc_valid_recordings": len(counts),
            "verified_known_packets": len(packets), "packet_recall": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] /
                        "docs/evidence/nrf-validation")
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), indent=2))


if __name__ == "__main__":
    main()
