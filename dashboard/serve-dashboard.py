#!/usr/bin/env python3
"""
Arborist Run Dashboard — Live Server
Reads task-tree, reports, and logs from disk on each request.

Usage:
    python3 docs/tasks/serve-dashboard.py [--port 8484] [--tree docs/tasks/task-tree-opus.json]

Then open http://localhost:8484
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent.parent


def find_arborist():
    """Try to find arborist binary."""
    candidates = [
        Path.home() / "Documents/backlit-testing/agent-arborist/venv/bin/arborist",
        "arborist",
    ]
    for c in candidates:
        p = Path(c)
        if p.exists():
            return str(p)
    return None


def load_task_tree(tree_path):
    with open(tree_path) as f:
        return json.load(f)


def load_reports(reports_dir):
    reports = {}
    if not os.path.isdir(reports_dir):
        return reports
    for fname in sorted(os.listdir(reports_dir)):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(reports_dir, fname)
        with open(fpath) as f:
            r = json.load(f)
        tid = r['task_id']
        # Extract timestamp from filename
        m = re.search(r'(\d{8}T\d{6})', fname)
        ts = m.group(1) if m else None
        reports[tid] = {
            'result': r.get('result', 'unknown'),
            'retries': r.get('retries', 0),
            'completed_at': ts,
            'filename': fname,
        }
    return reports


def load_logs(logs_dir):
    logs = {}
    if not os.path.isdir(logs_dir):
        return logs
    for fname in sorted(os.listdir(logs_dir)):
        if not fname.endswith('.log'):
            continue
        m = re.match(r'(?:M\d+-)?(\w\d+)_(\w+)_(\d{8}T\d{6})\.log', fname)
        if not m:
            continue
        tid, phase, ts = m.groups()
        if tid not in logs:
            logs[tid] = []
        # Get file size for extra info
        fpath = os.path.join(logs_dir, fname)
        size = os.path.getsize(fpath)
        logs[tid].append({
            'phase': phase,
            'timestamp': ts,
            'filename': fname,
            'size': size,
        })
    # Sort each task's logs by timestamp
    for tid in logs:
        logs[tid].sort(key=lambda e: e['timestamp'])
    return logs


def compute_attempt_counts(logs):
    """Count actual implement/review cycles from logs (more accurate than report retries)."""
    counts = {}
    for tid, entries in logs.items():
        impl_count = sum(1 for e in entries if e['phase'] == 'implement')
        review_count = sum(1 for e in entries if e['phase'] == 'review')
        counts[tid] = {
            'implement_attempts': impl_count,
            'review_attempts': review_count,
            'total_phases': len(entries),
        }
    return counts


def build_api_data(tree_path, reports_dir, logs_dir):
    tree = load_task_tree(tree_path)
    reports = load_reports(reports_dir)
    logs = load_logs(logs_dir)
    attempts = compute_attempt_counts(logs)

    # Build milestones and tasks
    milestones = []
    tasks = []
    for nid in sorted(tree['nodes'].keys(), key=lambda x: (x[0], int(re.search(r'\d+', x).group()))):
        node = tree['nodes'][nid]
        if nid.startswith('M'):
            milestones.append({
                'id': nid,
                'name': node['name'],
                'children': node.get('children', []),
            })
        elif nid.startswith('T'):
            # Extract test command info
            test_cmds = node.get('test_commands', [])
            test_pattern = None
            if test_cmds:
                cmd = test_cmds[0].get('command', '')
                # e.g. "npx jest --passWithNoTests tests/battle-html"
                m2 = re.search(r'tests/(\S+)', cmd)
                if m2:
                    test_pattern = m2.group(1)
            tasks.append({
                'id': nid,
                'name': node['name'],
                'parent': node.get('parent', ''),
                'depends_on': node.get('depends_on', []),
                'test_pattern': test_pattern,
            })

    return {
        'milestones': milestones,
        'tasks': tasks,
        'reports': reports,
        'logs': logs,
        'attempts': attempts,
        'tree_file': str(tree_path),
        'generated_at': datetime.now().isoformat(),
    }


def run_jest_json():
    """Run jest --json and return parsed results."""
    try:
        result = subprocess.run(
            ['npx', 'jest', '--json', '--passWithNoTests'],
            capture_output=True, text=True, timeout=60,
            cwd=str(REPO_ROOT),
        )
        # jest exits non-zero if tests fail, but still outputs JSON to stdout
        raw = result.stdout
        if not raw.strip():
            return {'error': 'No jest output', 'stderr': result.stderr[:500]}
        data = json.loads(raw)
        # Build compact summary
        suites = []
        for s in data.get('testResults', []):
            name = s['name']
            # Make path relative
            if 'chordessy/' in name:
                name = name.split('chordessy/')[-1]
            assertions = s.get('assertionResults', [])
            passed = sum(1 for a in assertions if a['status'] == 'passed')
            failed = sum(1 for a in assertions if a['status'] == 'failed')
            skipped = sum(1 for a in assertions if a['status'] in ('pending', 'skipped'))
            suites.append({
                'name': name,
                'status': s['status'],
                'total': len(assertions),
                'passed': passed,
                'failed': failed,
                'skipped': skipped,
                'duration': s.get('endTime', 0) - s.get('startTime', 0),
            })
        return {
            'numTotalSuites': data.get('numTotalTestSuites', 0),
            'numPassedSuites': data.get('numPassedTestSuites', 0),
            'numFailedSuites': data.get('numFailedTestSuites', 0),
            'numTotalTests': data.get('numTotalTests', 0),
            'numPassedTests': data.get('numPassedTests', 0),
            'numFailedTests': data.get('numFailedTests', 0),
            'success': data.get('success', False),
            'suites': suites,
        }
    except subprocess.TimeoutExpired:
        return {'error': 'Jest timed out (60s)'}
    except json.JSONDecodeError as e:
        return {'error': f'JSON parse error: {e}'}
    except Exception as e:
        return {'error': str(e)}


def get_arborist_status(tree_path):
    arborist = find_arborist()
    if not arborist:
        return None
    try:
        result = subprocess.run(
            [arborist, 'status', '--tree', str(tree_path)],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        return result.stdout
    except Exception as e:
        return f"Error: {e}"


DASHBOARD_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Arborist Run Dashboard</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-dim: #8b949e;
    --green: #3fb950;
    --green-dim: #238636;
    --yellow: #d29922;
    --red: #f85149;
    --cyan: #58a6ff;
    --purple: #bc8cff;
    --orange: #d18616;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text);
    padding: 24px; line-height: 1.5;
  }
  h1 { font-size: 24px; font-weight: 600; margin-bottom: 4px; }
  h2 { font-size: 16px; font-weight: 600; margin-bottom: 12px; color: var(--text-dim); }
  .header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .subtitle { color: var(--text-dim); font-size: 14px; margin-bottom: 24px; }
  .refresh-info { font-size: 12px; color: var(--text-dim); }
  .refresh-btn {
    background: var(--green-dim); color: var(--text); border: none; border-radius: 6px;
    padding: 6px 14px; cursor: pointer; font-size: 13px; margin-left: 8px;
  }
  .refresh-btn:hover { background: var(--green); }
  .auto-label { font-size: 12px; color: var(--text-dim); margin-left: 8px; }
  .grid { display: grid; gap: 16px; margin-bottom: 24px; }
  .grid-2 { grid-template-columns: 1fr 1fr; }
  .grid-3 { grid-template-columns: 1fr 1fr 1fr; }
  .grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
  }
  .stat-value { font-size: 32px; font-weight: 700; }
  .stat-label { font-size: 13px; color: var(--text-dim); }
  .progress-outer {
    background: var(--border); border-radius: 6px; height: 12px;
    overflow: hidden; margin: 8px 0;
  }
  .progress-inner { height: 100%; border-radius: 6px; transition: width 0.5s ease; }
  .milestone {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 0; border-bottom: 1px solid var(--border);
  }
  .milestone:last-child { border-bottom: none; }
  .milestone-id { font-weight: 600; font-size: 13px; color: var(--cyan); min-width: 28px; }
  .milestone-name { flex: 1; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .milestone-bar-outer {
    width: 120px; height: 8px; background: var(--border);
    border-radius: 4px; overflow: hidden; flex-shrink: 0;
  }
  .milestone-bar-inner { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
  .milestone-count { font-size: 13px; color: var(--text-dim); min-width: 40px; text-align: right; }
  .milestone-check { font-size: 14px; min-width: 20px; text-align: center; }

  .gantt { position: relative; overflow-x: auto; }
  .gantt-row { display: flex; align-items: center; height: 28px; gap: 8px; }
  .gantt-label { font-size: 12px; font-family: monospace; min-width: 40px; color: var(--text-dim); }
  .gantt-track { flex: 1; position: relative; height: 20px; }
  .gantt-bar {
    position: absolute; height: 16px; top: 2px; border-radius: 3px;
    min-width: 4px; cursor: pointer;
  }
  .gantt-bar:hover { filter: brightness(1.3); }
  .gantt-bar.implement { background: var(--cyan); opacity: 0.7; }
  .gantt-bar.review { background: var(--purple); opacity: 0.7; }
  .gantt-bar.test { background: var(--yellow); opacity: 0.7; }
  .gantt-bar.retry-attempt { border: 2px solid var(--orange); }
  .gantt-milestone-sep { border-top: 1px dashed var(--border); margin: 4px 0; padding-top: 4px; }
  .gantt-milestone-label { font-size: 11px; font-weight: 600; color: var(--green); padding: 2px 0 4px 0; }

  .tooltip {
    display: none; position: fixed; background: #1c2128; border: 1px solid var(--border);
    border-radius: 6px; padding: 8px 12px; font-size: 12px; z-index: 100;
    max-width: 400px; pointer-events: none; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  }
  .tooltip.show { display: block; }

  .retry-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
  .retry-label { font-size: 12px; font-family: monospace; min-width: 40px; }
  .retry-bar { height: 14px; border-radius: 3px; }
  .retry-count { font-size: 12px; color: var(--text-dim); }

  .dur-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
  .dur-label { font-size: 12px; min-width: 60px; text-align: right; color: var(--text-dim); }
  .dur-bar { height: 14px; background: var(--cyan); border-radius: 3px; opacity: 0.7; }
  .dur-count { font-size: 12px; color: var(--text-dim); }

  .legend { display: flex; gap: 16px; margin-bottom: 12px; flex-wrap: wrap; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-dim); }
  .legend-dot { width: 12px; height: 12px; border-radius: 3px; }

  .attempts-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .attempts-table th {
    text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border);
    color: var(--text-dim); font-weight: 500;
  }
  .attempts-table td { padding: 4px 8px; border-bottom: 1px solid #21262d; }
  .attempts-table tr:hover { background: rgba(88,166,255,0.05); }
  .badge {
    display: inline-block; padding: 1px 6px; border-radius: 10px;
    font-size: 11px; font-weight: 600;
  }
  .badge-pass { background: var(--green-dim); color: var(--green); }
  .badge-retry { background: #3d2004; color: var(--orange); }
  .badge-pending { background: var(--border); color: var(--text-dim); }
  .badge-active { background: #0c2d6b; color: var(--cyan); }

  /* Tests */
  .test-summary {
    display: flex; gap: 24px; margin-bottom: 16px; flex-wrap: wrap;
  }
  .test-stat { text-align: center; }
  .test-stat-value { font-size: 28px; font-weight: 700; }
  .test-stat-label { font-size: 12px; color: var(--text-dim); }
  .test-bar-outer {
    height: 10px; background: var(--border); border-radius: 5px;
    overflow: hidden; margin: 8px 0; display: flex;
  }
  .test-bar-pass { background: var(--green); height: 100%; }
  .test-bar-fail { background: var(--red); height: 100%; }
  .suite-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .suite-table th {
    text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border);
    color: var(--text-dim); font-weight: 500;
  }
  .suite-table td { padding: 4px 8px; border-bottom: 1px solid #21262d; }
  .suite-table tr:hover { background: rgba(88,166,255,0.05); }
  .suite-table .suite-name { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .test-run-btn {
    background: var(--surface); color: var(--cyan); border: 1px solid var(--cyan);
    border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 12px;
  }
  .test-run-btn:hover { background: #0c2d6b; }
  .test-run-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  /* Full plan */
  .plan-milestone {
    margin-bottom: 16px;
  }
  .plan-milestone-header {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 0; cursor: pointer; user-select: none;
  }
  .plan-milestone-header:hover { opacity: 0.85; }
  .plan-milestone-toggle {
    font-size: 11px; color: var(--text-dim); width: 16px; text-align: center;
    transition: transform 0.2s;
  }
  .plan-milestone-toggle.collapsed { transform: rotate(-90deg); }
  .plan-milestone-id { font-weight: 600; font-size: 14px; color: var(--cyan); min-width: 32px; }
  .plan-milestone-name { font-size: 14px; font-weight: 500; flex: 1; }
  .plan-milestone-progress {
    font-size: 12px; color: var(--text-dim);
    display: flex; align-items: center; gap: 8px;
  }
  .plan-milestone-bar {
    width: 80px; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden;
  }
  .plan-milestone-bar-inner { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
  .plan-tasks { padding-left: 26px; }
  .plan-tasks.hidden { display: none; }
  .plan-task {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 6px 0; border-bottom: 1px solid #21262d;
    font-size: 13px;
  }
  .plan-task:last-child { border-bottom: none; }
  .plan-task-icon { min-width: 18px; text-align: center; font-size: 14px; padding-top: 1px; }
  .plan-task-id { font-family: monospace; font-size: 12px; min-width: 38px; color: var(--text-dim); }
  .plan-task-name { flex: 1; line-height: 1.4; }
  .plan-task-name.done { color: var(--text-dim); }
  .plan-task-badge { flex-shrink: 0; }

  @media (max-width: 768px) {
    .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>

<div class="header-row">
  <div>
    <h1>Arborist Run Dashboard</h1>
    <div class="subtitle" id="subtitle">Loading...</div>
  </div>
  <div style="display:flex;align-items:center;">
    <span class="refresh-info" id="refresh-info"></span>
    <button class="refresh-btn" onclick="fetchAndRender()">Refresh</button>
    <label class="auto-label">
      <input type="checkbox" id="auto-refresh" checked> Auto (5s)
    </label>
  </div>
</div>

<div class="grid grid-4" id="stats"></div>

<div class="card" style="margin-bottom: 16px;">
  <h2>Overall Progress</h2>
  <div id="overall-progress"></div>
</div>

<div class="grid grid-2">
  <div class="card">
    <h2>Milestones</h2>
    <div id="milestones"></div>
  </div>
  <div class="card">
    <h2>Attempts (from logs)</h2>
    <div id="attempts" style="max-height:300px;overflow-y:auto;"></div>
    <div style="margin-top:16px;">
      <h2>Duration Distribution</h2>
      <div id="durations"></div>
    </div>
  </div>
</div>

<div class="card" style="margin-top: 16px;">
  <h2>Full Plan</h2>
  <div id="full-plan"></div>
</div>

<div class="card" style="margin-top: 16px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <h2 style="margin-bottom:0;">Tests</h2>
    <button class="test-run-btn" id="run-tests-btn" onclick="fetchTests()">Run Tests</button>
  </div>
  <div id="tests-panel">
    <div style="color:var(--text-dim);font-size:13px;">Click "Run Tests" to execute jest and see results.</div>
  </div>
</div>

<div class="card" style="margin-top: 16px;">
  <h2>Timeline</h2>
  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:var(--cyan);"></div> Implement</div>
    <div class="legend-item"><div class="legend-dot" style="background:var(--purple);"></div> Review</div>
    <div class="legend-item"><div class="legend-dot" style="background:var(--yellow);"></div> Test</div>
    <div class="legend-item"><div class="legend-dot" style="border:2px solid var(--orange);background:transparent;"></div> Retry attempt</div>
  </div>
  <div class="gantt" id="gantt"></div>
</div>

<div id="tooltip" class="tooltip"></div>

<script>
function parseTs(ts) {
  const m = ts.match(/(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/);
  if (!m) return new Date();
  return new Date(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +m[6]);
}

function fmtTime(d) {
  return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
}

let autoTimer = null;

function startAutoRefresh() {
  stopAutoRefresh();
  if (document.getElementById('auto-refresh').checked) {
    autoTimer = setInterval(fetchAndRender, 5000);
  }
}
function stopAutoRefresh() {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
}

document.getElementById('auto-refresh').addEventListener('change', () => {
  if (document.getElementById('auto-refresh').checked) startAutoRefresh();
  else stopAutoRefresh();
});

async function fetchAndRender() {
  const btn = document.querySelector('.refresh-btn');
  const info = document.getElementById('refresh-info');
  btn.textContent = 'Refreshing...';
  btn.style.opacity = '0.6';
  info.textContent = 'Fetching...';
  try {
    const resp = await fetch('/api/data?t=' + Date.now());
    const data = await resp.json();
    render(data);
    info.textContent = 'Updated ' + new Date().toLocaleTimeString();
    // Brief flash to show something happened
    document.body.style.transition = 'background 0.15s';
    document.body.style.background = '#111820';
    setTimeout(() => { document.body.style.background = 'var(--bg)'; }, 150);
  } catch (e) {
    info.textContent = 'Error: ' + e.message;
    info.style.color = 'var(--red)';
    setTimeout(() => { info.style.color = ''; }, 3000);
  }
  btn.textContent = 'Refresh';
  btn.style.opacity = '1';
}

function render(D) {
  const totalTasks = D.milestones.reduce((s, m) => s + m.children.length, 0);
  const completedTasks = Object.keys(D.reports).length;

  // Count actual retried tasks using log-based attempts (>1 implement = retry)
  const logRetried = Object.entries(D.attempts)
    .filter(([tid, a]) => a.implement_attempts > 1 && D.reports[tid])
    .length;
  const reportRetried = Object.values(D.reports).filter(r => r.retries > 0).length;

  // Time range from logs
  let allTs = [];
  for (const entries of Object.values(D.logs)) {
    for (const e of entries) allTs.push(parseTs(e.timestamp));
  }
  if (allTs.length === 0) { allTs = [new Date()]; }
  const minTime = Math.min(...allTs.map(d => d.getTime()));
  const maxTime = Math.max(...allTs.map(d => d.getTime()));
  const durationMin = Math.round((maxTime - minTime) / 60000);

  document.getElementById('subtitle').textContent =
    D.tree_file + ' \u2014 Generated ' + new Date(D.generated_at).toLocaleTimeString();

  // Stats
  document.getElementById('stats').innerHTML = [
    { value: `${completedTasks}/${totalTasks}`, label: 'Tasks Completed', color: 'var(--green)' },
    { value: `${Math.round(completedTasks/totalTasks*100)}%`, label: 'Progress', color: 'var(--cyan)' },
    { value: `${logRetried}`, label: `Retried (${reportRetried} per report)`, color: logRetried > 0 ? 'var(--orange)' : 'var(--green)' },
    { value: `${durationMin}m`, label: 'Elapsed Time', color: 'var(--text)' },
  ].map(s => `
    <div class="card">
      <div class="stat-value" style="color:${s.color}">${s.value}</div>
      <div class="stat-label">${s.label}</div>
    </div>
  `).join('');

  // Overall progress
  const pct = totalTasks > 0 ? Math.round(completedTasks / totalTasks * 100) : 0;
  document.getElementById('overall-progress').innerHTML = `
    <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px;">
      <span>${completedTasks} of ${totalTasks} tasks</span><span>${pct}%</span>
    </div>
    <div class="progress-outer">
      <div class="progress-inner" style="width:${pct}%;background:var(--green);"></div>
    </div>
    <div style="font-size:12px;color:var(--text-dim);margin-top:4px;">
      ${fmtTime(new Date(minTime))} &mdash; ${fmtTime(new Date(maxTime))}
      &bull; ${durationMin} minutes
    </div>
  `;

  // Milestones
  document.getElementById('milestones').innerHTML = D.milestones.map(m => {
    const done = m.children.filter(c => D.reports[c]).length;
    const total = m.children.length;
    const mpct = total > 0 ? Math.round(done / total * 100) : 0;
    const complete = done === total;
    const color = complete ? 'var(--green)' : done > 0 ? 'var(--yellow)' : 'var(--border)';
    const check = complete
      ? '<span style="color:var(--green)">&#10003;</span>'
      : done > 0 ? '<span style="color:var(--yellow)">&#9679;</span>'
      : '<span style="color:var(--text-dim)">&mdash;</span>';
    return `<div class="milestone">
      <span class="milestone-id">${m.id}</span>
      <span class="milestone-name" title="${m.name}">${m.name}</span>
      <div class="milestone-bar-outer">
        <div class="milestone-bar-inner" style="width:${mpct}%;background:${color};"></div>
      </div>
      <span class="milestone-count">${done}/${total}</span>
      <span class="milestone-check">${check}</span>
    </div>`;
  }).join('');

  // Attempts table (more honest than report retries)
  const completedIds = Object.keys(D.reports).sort((a, b) => {
    const na = parseInt(a.slice(1)), nb = parseInt(b.slice(1));
    return na - nb;
  });

  let attRows = completedIds.map(tid => {
    const a = D.attempts[tid] || { implement_attempts: '?', review_attempts: '?', total_phases: '?' };
    const r = D.reports[tid];
    const impl = a.implement_attempts || 0;
    const rev = a.review_attempts || 0;
    const isRetry = impl > 1;
    const badge = isRetry
      ? `<span class="badge badge-retry">${impl - 1} retry</span>`
      : `<span class="badge badge-pass">clean</span>`;
    return `<tr>
      <td style="font-family:monospace;">${tid}</td>
      <td>${impl}</td>
      <td>${rev}</td>
      <td>${a.total_phases}</td>
      <td>${badge}</td>
    </tr>`;
  }).join('');

  document.getElementById('attempts').innerHTML = `
    <table class="attempts-table">
      <thead><tr><th>Task</th><th>Impl</th><th>Review</th><th>Total</th><th>Status</th></tr></thead>
      <tbody>${attRows}</tbody>
    </table>
  `;

  // Duration distribution
  function getTaskDuration(tid) {
    const entries = D.logs[tid];
    if (!entries || entries.length < 2) return null;
    const times = entries.map(e => parseTs(e.timestamp).getTime());
    return (Math.max(...times) - Math.min(...times)) / 1000;
  }

  const durations = completedIds.map(tid => ({ tid, dur: getTaskDuration(tid) })).filter(d => d.dur !== null);
  const buckets = [
    { label: '< 30s', min: 0, max: 30, count: 0 },
    { label: '30s-1m', min: 30, max: 60, count: 0 },
    { label: '1-2m', min: 60, max: 120, count: 0 },
    { label: '2-3m', min: 120, max: 180, count: 0 },
    { label: '3m+', min: 180, max: Infinity, count: 0 },
  ];
  for (const d of durations) {
    for (const b of buckets) {
      if (d.dur >= b.min && d.dur < b.max) { b.count++; break; }
    }
  }
  const maxBucket = Math.max(...buckets.map(b => b.count), 1);
  document.getElementById('durations').innerHTML = buckets.map(b => `
    <div class="dur-row">
      <span class="dur-label">${b.label}</span>
      <div class="dur-bar" style="width:${b.count/maxBucket*100}%;min-width:${b.count>0?14:0}px;"></div>
      <span class="dur-count">${b.count}</span>
    </div>
  `).join('');

  // Full plan - build task lookup
  const taskMap = {};
  for (const t of D.tasks) { taskMap[t.id] = t; }

  document.getElementById('full-plan').innerHTML = D.milestones.map(m => {
    const done = m.children.filter(c => D.reports[c]).length;
    const total = m.children.length;
    const mpct = total > 0 ? Math.round(done / total * 100) : 0;
    const complete = done === total;
    const inProgress = !complete && done > 0;
    const barColor = complete ? 'var(--green)' : inProgress ? 'var(--yellow)' : 'var(--border)';
    const nameColor = complete ? 'color:var(--green)' : inProgress ? 'color:var(--yellow)' : '';

    const taskRows = m.children.map(tid => {
      const task = taskMap[tid];
      const name = task ? task.name : tid;
      const isDone = !!D.reports[tid];
      const isActive = !isDone && !!D.logs[tid];
      const isPending = !isDone && !isActive;

      let icon, badge, nameClass;
      if (isDone) {
        const a = D.attempts[tid];
        const hadRetry = a && a.implement_attempts > 1;
        icon = '<span style="color:var(--green)">&#10003;</span>';
        badge = hadRetry
          ? `<span class="badge badge-retry">${a.implement_attempts - 1} retry</span>`
          : `<span class="badge badge-pass">pass</span>`;
        nameClass = 'plan-task-name done';
      } else if (isActive) {
        icon = '<span style="color:var(--cyan)">&#9654;</span>';
        badge = '<span class="badge badge-active">running</span>';
        nameClass = 'plan-task-name';
      } else {
        icon = '<span style="color:var(--text-dim)">&#9675;</span>';
        badge = '<span class="badge badge-pending">pending</span>';
        nameClass = 'plan-task-name';
      }

      return `<div class="plan-task">
        <span class="plan-task-icon">${icon}</span>
        <span class="plan-task-id">${tid}</span>
        <span class="${nameClass}">${name}</span>
        <span class="plan-task-badge">${badge}</span>
      </div>`;
    }).join('');

    const collapsed = complete ? ' collapsed' : '';
    const hidden = complete ? ' hidden' : '';

    return `<div class="plan-milestone">
      <div class="plan-milestone-header" onclick="this.querySelector('.plan-milestone-toggle').classList.toggle('collapsed'); this.nextElementSibling.classList.toggle('hidden');">
        <span class="plan-milestone-toggle${collapsed}">&#9660;</span>
        <span class="plan-milestone-id">${m.id}</span>
        <span class="plan-milestone-name" style="${nameColor}">${m.name}</span>
        <div class="plan-milestone-progress">
          <div class="plan-milestone-bar">
            <div class="plan-milestone-bar-inner" style="width:${mpct}%;background:${barColor};"></div>
          </div>
          <span>${done}/${total}</span>
        </div>
      </div>
      <div class="plan-tasks${hidden}">${taskRows}</div>
    </div>`;
  }).join('');

  // Gantt
  const ganttEl = document.getElementById('gantt');
  const timeRange = maxTime - minTime || 1;
  let ganttHTML = '';

  for (const m of D.milestones) {
    const done = m.children.filter(c => D.reports[c]).length;
    const total = m.children.length;
    const complete = done === total && total > 0;
    const started = m.children.some(c => D.logs[c]);
    const mColor = complete ? 'var(--green)' : started ? 'var(--yellow)' : 'var(--text-dim)';

    ganttHTML += `<div class="gantt-milestone-sep"></div>`;
    ganttHTML += `<div class="gantt-milestone-label" style="color:${mColor}">${m.id}: ${m.name} <span style="color:var(--text-dim);font-weight:400;">(${done}/${total})</span></div>`;

    for (const tid of m.children) {
      const entries = D.logs[tid];
      const isDone = !!D.reports[tid];
      const isActive = !isDone && entries && entries.length > 0;

      if (!entries || entries.length === 0) {
        // Pending task — show as empty row with dimmed label
        const labelStyle = isDone ? 'color:var(--green)' : 'color:var(--border)';
        ganttHTML += `<div class="gantt-row">
          <span class="gantt-label" style="${labelStyle}">${tid}</span>
          <div class="gantt-track" style="border-bottom:1px dotted var(--border);opacity:0.3;"></div>
        </div>`;
        continue;
      }

      // Determine which entries are retry attempts
      const implIndices = entries.map((e, i) => e.phase === 'implement' ? i : -1).filter(i => i >= 0);
      const isMultiImpl = implIndices.length > 1;
      const lastImplIdx = implIndices.length > 0 ? implIndices[implIndices.length - 1] : entries.length;

      let bars = '';
      for (let i = 0; i < entries.length; i++) {
        const e = entries[i];
        const t = parseTs(e.timestamp).getTime();
        const end = i < entries.length - 1
          ? parseTs(entries[i + 1].timestamp).getTime()
          : t + 30000;
        const left = ((t - minTime) / timeRange) * 100;
        const width = Math.max(((end - t) / timeRange) * 100, 0.3);
        const isRetryAttempt = isMultiImpl && i < lastImplIdx;
        const retryClass = isRetryAttempt ? ' retry-attempt' : '';
        bars += `<div class="gantt-bar ${e.phase}${retryClass}"
          style="left:${left}%;width:${width}%;"
          data-tid="${tid}" data-phase="${e.phase}" data-ts="${e.timestamp}"
          data-retry="${isRetryAttempt}" data-file="${e.filename || ''}"></div>`;
      }

      const labelStyle = isDone ? '' : isActive ? 'color:var(--cyan)' : '';
      ganttHTML += `<div class="gantt-row">
        <span class="gantt-label" style="${labelStyle}">${tid}</span>
        <div class="gantt-track">${bars}</div>
      </div>`;
    }
  }
  ganttEl.innerHTML = ganttHTML;
}

// Tooltip
const tooltip = document.getElementById('tooltip');
document.getElementById('gantt').addEventListener('mouseover', e => {
  const bar = e.target.closest('.gantt-bar');
  if (!bar) return;
  const retry = bar.dataset.retry === 'true';
  const time = parseTs(bar.dataset.ts);
  tooltip.innerHTML = `
    <strong>${bar.dataset.tid}</strong> &mdash; ${bar.dataset.phase}${retry ? ' <span style="color:var(--orange)">(retry)</span>' : ''}<br>
    ${fmtTime(time)}<br>
    <span style="color:var(--text-dim)">${bar.dataset.file}</span>
  `;
  tooltip.classList.add('show');
});
document.getElementById('gantt').addEventListener('mousemove', e => {
  tooltip.style.left = (e.clientX + 12) + 'px';
  tooltip.style.top = (e.clientY - 10) + 'px';
});
document.getElementById('gantt').addEventListener('mouseout', e => {
  if (!e.target.closest('.gantt-bar')) tooltip.classList.remove('show');
});

// Test panel
async function fetchTests() {
  const btn = document.getElementById('run-tests-btn');
  const panel = document.getElementById('tests-panel');
  btn.disabled = true;
  btn.textContent = 'Running...';
  panel.innerHTML = '<div style="color:var(--text-dim);font-size:13px;">Running jest... (this may take a moment)</div>';

  try {
    const resp = await fetch('/api/tests');
    const T = await resp.json();

    if (T.error) {
      panel.innerHTML = `<div style="color:var(--red);font-size:13px;">Error: ${T.error}</div>`;
      return;
    }

    const passPct = T.numTotalTests > 0 ? Math.round(T.numPassedTests / T.numTotalTests * 100) : 0;
    const failPct = T.numTotalTests > 0 ? Math.round(T.numFailedTests / T.numTotalTests * 100) : 0;

    let html = `
      <div class="test-summary">
        <div class="test-stat">
          <div class="test-stat-value" style="color:var(--text)">${T.numTotalTests}</div>
          <div class="test-stat-label">Total Tests</div>
        </div>
        <div class="test-stat">
          <div class="test-stat-value" style="color:var(--green)">${T.numPassedTests}</div>
          <div class="test-stat-label">Passed</div>
        </div>
        <div class="test-stat">
          <div class="test-stat-value" style="color:${T.numFailedTests > 0 ? 'var(--red)' : 'var(--green)'}">${T.numFailedTests}</div>
          <div class="test-stat-label">Failed</div>
        </div>
        <div class="test-stat">
          <div class="test-stat-value" style="color:var(--text)">${T.numTotalSuites}</div>
          <div class="test-stat-label">Suites</div>
        </div>
        <div class="test-stat">
          <div class="test-stat-value" style="color:var(--text)">${passPct}%</div>
          <div class="test-stat-label">Pass Rate</div>
        </div>
      </div>
      <div class="test-bar-outer">
        <div class="test-bar-pass" style="width:${passPct}%"></div>
        <div class="test-bar-fail" style="width:${failPct}%"></div>
      </div>
      <div style="margin-top:12px;max-height:300px;overflow-y:auto;">
        <table class="suite-table">
          <thead><tr><th>Suite</th><th>Status</th><th>Pass</th><th>Fail</th><th>Total</th></tr></thead>
          <tbody>`;

    // Sort: failed first, then by name
    const sorted = [...T.suites].sort((a, b) => {
      if (a.status !== b.status) return a.status === 'failed' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

    for (const s of sorted) {
      const statusColor = s.status === 'passed' ? 'var(--green)' : 'var(--red)';
      const shortName = s.name.replace('tests/', '').replace('.test.js', '');
      html += `<tr>
        <td class="suite-name" title="${s.name}">${shortName}</td>
        <td style="color:${statusColor}">${s.status}</td>
        <td style="color:var(--green)">${s.passed}</td>
        <td style="color:${s.failed > 0 ? 'var(--red)' : 'var(--text-dim)'}">${s.failed}</td>
        <td>${s.total}</td>
      </tr>`;
    }

    html += '</tbody></table></div>';
    panel.innerHTML = html;
  } catch (e) {
    panel.innerHTML = `<div style="color:var(--red);font-size:13px;">Fetch error: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run Tests';
  }
}

// Initial load + auto-refresh
fetchAndRender();
startAutoRefresh();
</script>
</body>
</html>
'''


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, tree_path=None, reports_dir=None, logs_dir=None, **kwargs):
        self.tree_path = tree_path
        self.reports_dir = reports_dir
        self.logs_dir = logs_dir
        super().__init__(*args, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode('utf-8'))

        elif parsed.path == '/api/data':
            try:
                data = build_api_data(self.tree_path, self.reports_dir, self.logs_dir)
                payload = json.dumps(data)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(payload.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

        elif parsed.path == '/api/status':
            status = get_arborist_status(self.tree_path)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write((status or 'arborist not found').encode('utf-8'))

        elif parsed.path == '/api/tests':
            try:
                data = run_jest_json()
                payload = json.dumps(data)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(payload.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

        elif parsed.path.startswith('/api/log/'):
            # Serve individual log file content
            fname = parsed.path.split('/api/log/')[-1]
            safe_fname = os.path.basename(fname)
            fpath = os.path.join(self.logs_dir, safe_fname)
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                with open(fpath) as f:
                    self.wfile.write(f.read().encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress request logging except errors
        if '404' in str(args) or '500' in str(args):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description='Arborist Run Dashboard Server')
    parser.add_argument('--port', type=int, default=8484, help='Port (default: 8484)')
    parser.add_argument('--tree', default=str(SCRIPT_DIR / 'task-tree-opus.json'),
                        help='Path to task tree JSON')
    parser.add_argument('--reports', default=str(SCRIPT_DIR / 'reports'),
                        help='Path to reports directory')
    parser.add_argument('--logs', default=str(SCRIPT_DIR / 'logs'),
                        help='Path to logs directory')
    args = parser.parse_args()

    tree_path = Path(args.tree).resolve()
    reports_dir = Path(args.reports).resolve()
    logs_dir = Path(args.logs).resolve()

    if not tree_path.exists():
        print(f"Error: Task tree not found: {tree_path}", file=sys.stderr)
        sys.exit(1)

    def handler_factory(*handler_args, **handler_kwargs):
        return DashboardHandler(
            *handler_args,
            tree_path=tree_path,
            reports_dir=reports_dir,
            logs_dir=logs_dir,
            **handler_kwargs,
        )

    server = HTTPServer(('localhost', args.port), handler_factory)
    print(f"Dashboard: http://localhost:{args.port}")
    print(f"Tree:      {tree_path}")
    print(f"Reports:   {reports_dir}")
    print(f"Logs:      {logs_dir}")
    print(f"API:       http://localhost:{args.port}/api/data")
    print(f"Status:    http://localhost:{args.port}/api/status")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == '__main__':
    main()
