"""Multi-front threat-profile detector (standalone analysis).

Fronts, fused per entity:
  A) Cohort-relative known-bad profiles  (entity vs role-group peers, robust IQR z)
  B) Raw-event known-bad profiles        (C2-beacon, DGA-DNS, cohort-rare external dst)
  C) Self-drift (supporting)             (entity vs its own past; corroboration only)

Each profile is a measurable fingerprint of a known attack technique. A flag = named
profile match (high precision); self-drift is supporting corroboration. Writes the
alert table to data/threat_profile_alerts.csv for the dashboard. Validated on 4
injected attacks (USR-156/234/042/118); reports the false-positive count.
"""
import glob, csv, math, os
from collections import defaultdict, Counter
import numpy as np, pandas as pd
from pipeline.dashboard_db import load_weekly_features, load_composite_scores
from comparison.run_comparison import _build_user_device_map

ATT = {'USR-156': 'insider', 'USR-234': 'slow APT', 'USR-042': 'LOTL', 'USR-118': 'Salt Typhoon'}
COHORT_THR = 4.5
OUT_CSV = 'data/threat_profile_alerts.csv'


def _cohort_z():
    f = load_weekly_features()
    FC = [c for c in f.columns if c not in ['user_id', 'week_idx', 'week_start', 'week_end']]
    grp = load_composite_scores().set_index('uid')['grp'].to_dict()
    gstd = f[FC].std(ddof=0).replace(0, 1e-9)   # global per-feature scale (floors near-constant baselines)
    L, SD = {}, {}
    for u in f.user_id.unique():
        ud = f[f.user_id == u].sort_values('week_idx'); n = len(ud)
        L[u] = ud[FC].iloc[3 * n // 4:].mean()
        early = ud[FC].iloc[:n // 2]; late = ud[FC].iloc[3 * n // 4:]
        sd = early.std(ddof=0).clip(lower=0.2 * gstd)   # floor by global scale -> no divide-by-~0 blowup
        SD[u] = float(((late.mean() - early.mean()).abs() / sd).max())   # self-drift magnitude
    L = pd.DataFrame(L).T; L['grp'] = [grp.get(u, '?') for u in L.index]
    gIQR = {c: max(L[c].quantile(.75) - L[c].quantile(.25), 1e-9) for c in FC}
    Z = pd.DataFrame(index=L.index)
    for c in FC:
        z = pd.Series(index=L.index, dtype=float)
        for g, sub in L.groupby('grp'):
            denom = max(sub[c].quantile(.75) - sub[c].quantile(.25), 0.25 * gIQR[c])
            z.loc[sub.index] = (sub[c] - sub[c].median()) / denom
        Z[c] = z
    return Z, grp, SD


def front_A(Z):
    """Named cohort-relative profiles. data_exfil requires volume AND intent (drops volume-only execs)."""
    AND = {
        'insider_collection': ['file_restricted_ratio', 'file_confidential_ratio'],
        'mass_collection':    ['file_unique_paths', 'file_total'],
        'ransomware':         ['file_write_ratio', 'file_total'],
        'recon_fanout':       ['net_unique_dsts'],
        'dns_malicious':      ['dns_nxdomain_ratio', 'dns_unique_domains'],
        'lotl_process':       ['endpoint_unique_processes', 'endpoint_total'],
        'highrisk_endpoint':  ['endpoint_suspicious_ratio', 'endpoint_max_risk'],
        'brute_force':        ['auth_failed', 'auth_fail_rate'],
        'lateral_movement':   ['auth_unique_dests'],
        'off_hours_auth':     ['auth_off_hours_ratio'],
        'auth_source_spray':  ['auth_unique_sources'],
    }
    out = defaultdict(dict)
    for u in Z.index:
        for name, feats in AND.items():
            s = float(Z.loc[u, feats].min())
            if s >= COHORT_THR:
                out[u][name] = round(s, 1)
        # data_exfil = high volume AND high (external transfer OR confidential access)
        vol = Z.loc[u, 'file_total_bytes']
        intent = max(Z.loc[u, 'net_external_ratio'], Z.loc[u, 'file_confidential_ratio'], Z.loc[u, 'net_bytes_out'])
        s = float(min(vol, intent))
        if s >= COHORT_THR:
            out[u]['data_exfil'] = round(s, 1)
    return out


def _ext(ip):
    ip = str(ip); return not (ip.startswith('10.') or ip.startswith('192.168.') or ip.startswith('172.'))
def _entropy(s):
    s = s.lower()
    if len(s) < 2: return 0.0
    c = Counter(s); n = len(s); return -sum((v / n) * math.log2(v / n) for v in c.values())
def _sld(q):
    p = str(q).strip('.').split('.'); return p[-2] if len(p) >= 2 else (p[0] if p else '')


def front_B(d2u, grp):
    out = defaultdict(dict)
    dd = defaultdict(set); cohort_ip = defaultdict(set); user_ext = defaultdict(set)
    for fp in sorted(glob.glob('data/generated/network/*.csv')):
        with open(fp, newline='') as fh:
            r = csv.reader(fh); h = next(r); di, xi = h.index('device_id'), h.index('dst_ip')
            for row in r:
                dev = row[di]
                if dev in d2u and _ext(row[xi]):
                    u = d2u[dev]; dd[(dev, row[xi])].add(fp)
                    cohort_ip[(grp.get(u), row[xi])].add(u); user_ext[u].add(row[xi])
    # Beacon (LABEL-FREE): the top-persistence external dst per user, then verify a
    # robotic, evenly-spaced rhythm (low inter-callout coefficient of variation).
    # No attack labels are used — a real C2 beacon is distinguished from a legitimate
    # persistent service (CDN/cloud) by its machine-like regularity, not by who it is.
    from datetime import datetime as _dt
    upers = defaultdict(int); utop = {}
    for (dev, dst), days in dd.items():
        u = d2u[dev]; n = len(days)
        if n > upers[u]: upers[u] = n; utop[u] = (dev, dst)
    track = {utop[u] for u in utop if upers[u] >= 100}
    ts = defaultdict(list)
    for fp in sorted(glob.glob('data/generated/network/*.csv')):
        with open(fp, newline='') as fh:
            r = csv.reader(fh); h = next(r); ti, di, xi = h.index('timestamp'), h.index('device_id'), h.index('dst_ip')
            for row in r:
                key = (row[di], row[xi])
                if key in track:
                    try: ts[key].append(_dt.fromisoformat(row[ti]).timestamp())
                    except Exception: pass
    for u in upers:
        if upers[u] < 100: continue
        t = sorted(ts.get(utop[u], []))
        if len(t) < 5: continue
        g = np.diff(t); cv = float(np.std(g) / np.mean(g)) if np.mean(g) > 0 else 9.99
        if cv < 0.65:   # robotic regularity (normal services ~0.8-1.0) -> C2 beacon
            out[u]['c2_beacon'] = upers[u]
    for u in user_ext:
        rare = [ip for ip in user_ext[u] if len(cohort_ip[(grp.get(u), ip)]) == 1]
        if len(rare) >= 20: out[u]['cohort_rare_dst'] = len(rare)
    uid_doms = defaultdict(lambda: defaultdict(set)); ipu = defaultdict(set)
    for fp in sorted(glob.glob('data/generated/dns/*.csv')):
        with open(fp, newline='') as fh:
            for row in csv.DictReader(fh):
                dev = row.get('device_id')
                if dev not in d2u: continue
                dom = (row.get('query_name') or '').strip() or (row.get('query_domain') or '').strip()
                if not dom: continue
                s = _sld(dom)
                if not s or _entropy(s) < 3.0: continue
                ip = (row.get('response_ip') or '').strip() or (row.get('response') or '').strip()
                if not ip or ip == 'NXDOMAIN': continue
                uid_doms[d2u[dev]][ip].add(s); ipu[ip].add(d2u[dev])
    for u, d in uid_doms.items():
        best = max((len(v) for ip, v in d.items() if len(ipu[ip]) <= 2), default=0)
        if best >= 20: out[u]['dga_dns'] = best
    return out


def main():
    Z, grp, SD = _cohort_z()
    A = front_A(Z)
    d2u = {d: u for u, devs in _build_user_device_map().items() for d in devs}
    B = front_B(d2u, grp)
    sd_med = float(np.median(list(SD.values())))
    flags = {u: {**A.get(u, {}), **B.get(u, {})} for u in set(A) | set(B)}

    rows = []
    for u in sorted(flags):
        m = flags[u]
        rows.append({
            'user_id': u, 'cohort': grp.get(u), 'is_known_attack': u in ATT,
            'attack_type': ATT.get(u, ''),
            'techniques': '; '.join('%s=%s' % (k, v) for k, v in m.items()),
            'n_fronts': len(m),
            'self_drift': round(SD.get(u, 0), 1),
            'self_drift_elevated': SD.get(u, 0) > 2 * sd_med,
        })
    df = pd.DataFrame(rows).sort_values(['is_known_attack', 'n_fronts'], ascending=False)
    os.makedirs('data', exist_ok=True); df.to_csv(OUT_CSV, index=False)

    att = [u for u in flags if u in ATT]; fp = [u for u in flags if u not in ATT]
    print('=== MULTI-FRONT THREAT-PROFILE DETECTOR (cohort thr %.1f) ===' % COHORT_THR)
    print('ATTACKERS CAUGHT: %d/4' % len(att))
    for u in ATT:
        m = flags.get(u, {})
        extra = '  [+self-drift %.1f]' % SD.get(u, 0) if SD.get(u, 0) > 2 * sd_med else ''
        print('  %-8s (%-12s, %-9s): %s%s' % (u, ATT[u], grp.get(u),
              ', '.join('%s=%s' % (k, v) for k, v in m.items()) or '*** MISSED ***', extra))
    print('\nFALSE POSITIVES: %d' % len(fp))
    for u in fp:
        print('  %-8s (%-9s): %s' % (u, grp.get(u), ', '.join('%s=%s' % (k, v) for k, v in flags[u].items())))
    prec = len(att) / max(len(att) + len(fp), 1)
    print('\nPRECISION %.0f%% | RECALL %d/4 | wrote %s (%d alerts)' % (100 * prec, len(att), OUT_CSV, len(df)))


if __name__ == '__main__':
    main()
