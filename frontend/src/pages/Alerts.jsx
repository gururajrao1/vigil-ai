import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth, useRefresh } from '../App';
import { Badge, Button, Card, Spinner } from '../components/ui';
import SeverityAuditPopover from '../components/SeverityAuditPopover';

const ACTIONS = {
  investigate: {
    label: 'Investigate',
    hint: 'Opens this pair on the Workflow board and marks it confirmed in Ops KPIs.',
  },
  seen: {
    label: 'Seen',
    hint: 'Clears the ping only — signal stays where it is.',
  },
  false_alarm: {
    label: 'False alarm',
    hint: 'Closes the pair as not a concern and dismisses it in Ops KPIs.',
  },
};

export default function Alerts({ embedded = false }) {
  const { tick, bump } = useRefresh();
  const { user } = useAuth();
  const nav = useNavigate();
  const [alerts, setAlerts] = useState(null);
  const [deliveries, setDeliveries] = useState([]);
  const [webhookConfigured, setWebhookConfigured] = useState(false);
  const [busy, setBusy] = useState(null); // `${id}:${action}`
  const [flash, setFlash] = useState(null);

  const actor = user?.email || user?.name || 'analyst';

  const load = () => {
    api.alerts().then((d) => setAlerts(d.alerts || [])).catch(() => setAlerts([]));
    api.outboundAlerts().then((d) => {
      setDeliveries(d.deliveries || []);
      setWebhookConfigured(!!d.webhook_configured);
    }).catch(() => {});
  };
  useEffect(() => { load(); }, [tick]);

  const resolve = async (id, action, e) => {
    e?.stopPropagation();
    setBusy(`${id}:${action}`);
    setFlash(null);
    try {
      const res = await api.ackAlert(id, action, actor);
      const bits = [];
      if (res.lifecycle_status) bits.push(`workflow → ${String(res.lifecycle_status).replace(/_/g, ' ')}`);
      if (res.review_state) bits.push(`ops → ${res.review_state}`);
      setFlash({
        ok: true,
        text: bits.length
          ? `${ACTIONS[action]?.label || action}: ${bits.join(' · ')}`
          : `${ACTIONS[action]?.label || action}: cleared from inbox`,
      });
      bump();
      load();
    } catch (err) {
      setFlash({ ok: false, text: err.message || 'Action failed' });
    }
    setBusy(null);
  };

  const notify = async (id, e, { escalate = true } = {}) => {
    e.stopPropagation();
    setBusy(`${id}:notify`);
    setFlash(null);
    try {
      const res = await api.notifyAlert(id, { andInvestigate: escalate, by: actor });
      const fx = res.effects || {};
      const bits = [];
      if (fx.lifecycle_status) bits.push(`workflow → ${String(fx.lifecycle_status).replace(/_/g, ' ')}`);
      if (fx.review_state) bits.push(`ops → ${fx.review_state}`);
      setFlash({
        ok: !!res.ok,
        text: res.ok
          ? (res.next_step || `Escalated (${res.mode || 'webhook'})${bits.length ? ` · ${bits.join(' · ')}` : ''}`)
          : `Notify failed (${res.mode || 'error'}). Nothing changed.`,
      });
      bump();
      load();
    } catch (err) {
      setFlash({ ok: false, text: err.message || 'Notify failed' });
    }
    setBusy(null);
  };

  if (!alerts) return <Spinner />;

  const open = alerts.filter((a) => !a.acknowledged);
  const handled = alerts.filter((a) => a.acknowledged);

  return (
    <div className="space-y-4">
      {!embedded && (
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Alert inbox</h2>
          <p className="text-sm text-slate-400 mt-1">
            Urgent pings when a product–event pair looks serious, spiking, or statistically strong.
          </p>
        </div>
      )}

      <Card className="p-4 space-y-2">
        <div className="text-sm text-slate-200 font-medium">Pick one — every open alert needs a decision</div>
        <ul className="text-xs text-slate-400 space-y-1.5 list-disc pl-4">
          <li>
            <span className="text-amber-300">Escalate</span> — ping Slack/Teams
            {webhookConfigured ? '' : ' (simulated)'}
            {' '}and open investigation (Workflow + Ops). Use when others must know.
          </li>
          <li>
            <span className="text-teal-300">Investigate</span> — you own it quietly (same Workflow/Ops, no team ping).
          </li>
          <li>
            <span className="text-rose-300">False alarm</span> — close as not a concern + dismiss in Ops.
          </li>
          <li>
            <span className="text-slate-200">Seen</span> — silence only; come back later.
          </li>
        </ul>
      </Card>

      {flash && (
        <div className={`text-sm rounded-lg border px-3 py-2 ${
          flash.ok
            ? 'border-teal-700/40 bg-teal-500/10 text-teal-200'
            : 'border-rose-700/40 bg-rose-500/10 text-rose-200'
        }`}>
          {flash.text}
        </div>
      )}

      <div className="flex items-center gap-3 text-xs text-slate-500">
        <span className="text-slate-300 font-medium">{open.length} open</span>
        <span>·</span>
        <span>{handled.length} handled</span>
      </div>

      {alerts.length === 0 && (
        <Card className="p-8 text-center text-slate-500 text-sm">
          No alerts yet. Load the demo corpus or stream a batch — strong / high-severity / spiking pairs land here.
        </Card>
      )}

      {open.length > 0 && (
        <div className="space-y-3">
          <div className="text-xs uppercase tracking-wide text-slate-500">Needs a decision</div>
          {open.map((a) => (
            <AlertRow
              key={a.id}
              a={a}
              busy={busy}
              onOpen={() => a.signal_id && nav(`/signals/${a.signal_id}`)}
              onResolve={resolve}
              onNotify={notify}
            />
          ))}
        </div>
      )}

      {handled.length > 0 && (
        <div className="space-y-3">
          <div className="text-xs uppercase tracking-wide text-slate-500">Handled</div>
          {handled.map((a) => (
            <AlertRow
              key={a.id}
              a={a}
              busy={busy}
              handled
              onOpen={() => a.signal_id && nav(`/signals/${a.signal_id}`)}
              onNotify={(id, e) => notify(id, e, { escalate: false })}
            />
          ))}
        </div>
      )}

      {deliveries.length > 0 && (
        <Card className="p-4">
          <div className="text-sm text-slate-200 mb-2">Team notifications sent</div>
          <div className="space-y-1.5">
            {deliveries.slice(0, 8).map((d) => (
              <div key={d.id} className="flex justify-between text-xs text-slate-400 border-b border-slate-800/40 pb-1">
                <span>{d.at?.replace('T', ' ').slice(0, 19)} · {d.message}</span>
                <span className={d.ok ? 'text-emerald-400' : 'text-rose-400'}>
                  {d.mode}{d.ok ? ' ✓' : ' ✗'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function AlertRow({ a, busy, handled = false, onOpen, onResolve, onNotify }) {
  const key = (action) => `${a.id}:${action}`;
  const isBusy = (action) => busy === key(action);

  return (
    <Card
      onClick={onOpen}
      className={`p-4 space-y-3 cursor-pointer hover:bg-slate-800/40 transition ${handled ? 'opacity-60' : ''}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
            a.severity === 'Critical' ? 'bg-rose-500 pulse-dot'
              : a.severity === 'High' ? 'bg-orange-400' : 'bg-amber-400'
          }`} />
          <div className="min-w-0">
            <div className="text-sm text-slate-100 font-medium capitalize leading-snug">{a.message}</div>
            <div className="text-xs text-slate-500 mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5">
              <span>{a.created_at?.replace('T', ' ').slice(0, 16)}</span>
              {a.drug && <span>· {a.drug}</span>}
              {a.symptom && <span>→ {a.symptom}</span>}
              {a.signal_id && <span className="text-teal-500/80">open signal #{a.signal_id}</span>}
            </div>
          </div>
        </div>
        <div onClick={(e) => e.stopPropagation()}>
          {a.signal_id
            ? <SeverityAuditPopover signalId={a.signal_id} severity={a.severity} />
            : <Badge kind="severity" value={a.severity} />}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
        {!handled && (
          <>
            <Button
              variant="primary"
              disabled={!!busy}
              onClick={(e) => onNotify(a.id, e)}
              title="Ping Slack/Teams and open investigation on Workflow"
            >
              {isBusy('notify') ? '…' : 'Escalate'}
            </Button>
            <Button
              variant="ghost"
              disabled={!!busy}
              onClick={(e) => onResolve(a.id, 'investigate', e)}
              title={ACTIONS.investigate.hint}
            >
              {isBusy('investigate') ? '…' : 'Investigate'}
            </Button>
            <Button
              variant="ghost"
              disabled={!!busy}
              onClick={(e) => onResolve(a.id, 'false_alarm', e)}
              title={ACTIONS.false_alarm.hint}
            >
              {isBusy('false_alarm') ? '…' : 'False alarm'}
            </Button>
            <Button
              variant="ghost"
              disabled={!!busy}
              onClick={(e) => onResolve(a.id, 'seen', e)}
              title={ACTIONS.seen.hint}
            >
              {isBusy('seen') ? '…' : 'Seen'}
            </Button>
          </>
        )}
        {handled && (
          <Button
            variant="ghost"
            disabled={!!busy}
            onClick={(e) => onNotify(a.id, e)}
            title="Re-ping team only (already handled)"
          >
            {isBusy('notify') ? 'Sending…' : 'Re-ping team'}
          </Button>
        )}
      </div>
    </Card>
  );
}
