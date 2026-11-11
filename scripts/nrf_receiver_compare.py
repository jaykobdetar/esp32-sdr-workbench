#!/usr/bin/env python3
"""Single-image historical DET1 versus optimized comparison. Never flashes hardware."""
from nrf_campaigns import nrf_rf_campaign as campaign


def parser():
    p = campaign.parser()
    p.description = __doc__
    p.add_argument('--receiver-mode', choices=('historical','optimized'), required=True)
    p.add_argument('--label', required=True, help='Independent image phase, e.g. historical-A1')
    p.add_argument('--expected-variant', default='', help='Optional substring required in actual VERSION')
    p.set_defaults(raw_pairs=0, gain=60, power_dbm=0, interval_us=1000, jitter_us=150)
    return p


def prepare(args):
    args.receiver_modes = [args.receiver_mode]
    return args


def main():
    args = prepare(parser().parse_args())
    from nrf_tx.rf_tx import Transmitter
    radio = campaign.Radio(args.rx_port)
    try:
        with Transmitter(args.tx_port) as tx:
            report = campaign.execute(args, radio, tx)
        return 0 if report['status']=='passed' else 1
    finally:
        radio.close()

if __name__ == '__main__':
    raise SystemExit(main())
