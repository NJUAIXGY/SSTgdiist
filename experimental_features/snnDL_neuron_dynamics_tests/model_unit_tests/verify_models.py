#!/usr/bin/env python3
import math, csv, sys

def load_csv(path):
    xs = []
    with open(path, 'r') as f:
        for line in f:
            if not line or line[0] == '#':
                continue
            if 'step' in line:
                continue
            step, v = line.strip().split(',')
            xs.append((int(step), float(v)))
    return xs

def verify_lif(trace, dt=1.0, v_rest=0.0, tau=20.0, inject_steps=30, w=0.5, v_reset=0.0, t_ref=2, v_thresh=2.0):
    # Euler-like: tickIdx does leak then refdec; onSynapticEvent applied before tick.
    v = 0.0
    ref = 0
    ok = True
    for step,(s,v_meas) in enumerate(trace):
        if step < inject_steps:
            v += w
        if ref>0:
            ref -= 1
        else:
            v = v_rest + (v - v_rest) * math.exp(-dt/tau)
            # fire test happens after tick in C++
            if v >= v_thresh:
                v = v_reset
                ref = t_ref
        if abs(v - v_meas) > 1e-4:
            print(f"LIF mismatch at step {step}: exp={v:.6f} got={v_meas:.6f}")
            ok = False
            break
    return ok

def verify_identity(trace):
    # Placeholder for Izh/AdEx: identity check is not meaningful; here we only ensure numeric sanity
    for step,(s,v) in enumerate(trace):
        if math.isnan(v) or math.isinf(v):
            print(f"Invalid value at step {step}: {v}")
            return False
    return True

def main():
    lif = load_csv('lif_trace.csv')
    izh = load_csv('izh_trace.csv')
    adx = load_csv('adex_trace.csv')

    lif_ok = verify_lif(lif)
    izh_ok = verify_identity(izh)
    adx_ok = verify_identity(adx)

    print(f"LIF OK={lif_ok}")
    print(f"Izhikevich OK={izh_ok}")
    print(f"AdEx OK={adx_ok}")
    if not (lif_ok and izh_ok and adx_ok):
        sys.exit(1)

if __name__ == '__main__':
    main()
