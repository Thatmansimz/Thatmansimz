"use client";
import { useState } from "react";

const FIRMS = [
  {
    id: "none",
    name: "No Prop Firm (Personal)",
    automation: true,
    dailyLoss: null,
    maxDrawdown: null,
    profitTarget: null,
    trailing: false,
    notes: "Trade your own account with no external rules.",
  },
  {
    id: "apex",
    name: "Apex Trader Funding",
    automation: true,
    dailyLoss: 2500,
    maxDrawdown: 2500,
    profitTarget: 3000,
    trailing: false,
    accountSize: 50000,
    notes: "Static drawdown, no time limit, automation explicitly allowed. Very AI-friendly.",
    url: "https://apextraderfunding.com",
  },
  {
    id: "traderfi",
    name: "TraderFi",
    automation: true,
    dailyLoss: 2000,
    maxDrawdown: 3000,
    profitTarget: 3000,
    trailing: false,
    accountSize: 50000,
    notes: "Instant funded, automation allowed. Check current terms before starting.",
    url: "https://traderfi.io",
  },
  {
    id: "myforexfunds",
    name: "MyFundedFutures",
    automation: true,
    dailyLoss: 1500,
    maxDrawdown: 3000,
    profitTarget: 4000,
    trailing: false,
    accountSize: 50000,
    notes: "30-day evaluation, automation allowed on futures accounts.",
    url: "https://myfundedfutures.com",
  },
  {
    id: "topstep",
    name: "TopStep",
    automation: false,
    dailyLoss: 1000,
    maxDrawdown: 2000,
    profitTarget: 3000,
    trailing: true,
    accountSize: 50000,
    notes: "TRAILING drawdown. NO automated trading allowed. Manual only.",
    url: "https://topstep.com",
  },
];

function Rule({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="flex justify-between text-xs py-1.5 border-b border-slate-800/60 last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className={warn ? "text-amber-400 font-medium" : "text-slate-300"}>{value}</span>
    </div>
  );
}

export default function PropFirmConfig() {
  const [selected, setSelected] = useState("none");
  const firm = FIRMS.find((f) => f.id === selected) || FIRMS[0];

  return (
    <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-white mb-1">Prop Firm Configuration</h2>
      <p className="text-[10px] text-slate-500 mb-4">
        Select your prop firm to see evaluation rules. Set PROP_FIRM= in .env to apply.
      </p>

      {/* Firm selector */}
      <div className="grid grid-cols-1 gap-2 mb-4">
        {FIRMS.map((f) => (
          <button
            key={f.id}
            onClick={() => setSelected(f.id)}
            className={[
              "flex items-center justify-between px-3 py-2 rounded-lg border text-left text-xs transition",
              selected === f.id
                ? "bg-slate-700 border-slate-500 text-white"
                : "bg-slate-800/40 border-slate-700/30 text-slate-400 hover:bg-slate-800 hover:text-slate-300",
            ].join(" ")}
          >
            <span className="font-medium">{f.name}</span>
            <div className="flex items-center gap-2">
              {f.trailing && (
                <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-900/50 text-amber-400 border border-amber-700/40">
                  TRAILING DD
                </span>
              )}
              <span
                className={[
                  "px-1.5 py-0.5 rounded text-[10px] border",
                  f.automation
                    ? "bg-emerald-900/40 text-emerald-400 border-emerald-700/40"
                    : "bg-rose-900/40 text-rose-400 border-rose-700/40",
                ].join(" ")}
              >
                {f.automation ? "AI OK" : "NO AI"}
              </span>
            </div>
          </button>
        ))}
      </div>

      {/* Selected firm details */}
      <div className="bg-slate-800/40 rounded-xl border border-slate-700/30 p-3">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-white">{firm.name}</h3>
          {firm.url && (
            <a
              href={firm.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[10px] text-blue-400 hover:text-blue-300 transition"
            >
              Visit ↗
            </a>
          )}
        </div>

        <div className="space-y-0">
          <Rule
            label="AI / Automation"
            value={firm.automation ? "ALLOWED" : "NOT ALLOWED — manual only"}
            warn={!firm.automation}
          />
          <Rule
            label="Daily Loss Limit"
            value={firm.dailyLoss ? `$${firm.dailyLoss.toLocaleString()}` : "Your choice"}
          />
          <Rule
            label="Max Drawdown"
            value={firm.maxDrawdown ? `$${firm.maxDrawdown.toLocaleString()}` : "Your choice"}
            warn={firm.trailing}
          />
          <Rule
            label="Profit Target"
            value={firm.profitTarget ? `$${firm.profitTarget.toLocaleString()}` : "None"}
          />
          <Rule
            label="Drawdown Type"
            value={firm.trailing ? "TRAILING (hardest)" : "Static (safer)"}
            warn={firm.trailing}
          />
          {firm.accountSize && (
            <Rule
              label="Account Size (50k)"
              value={`$${firm.accountSize.toLocaleString()}`}
            />
          )}
        </div>

        <div className="mt-3 p-2 rounded-lg bg-slate-900/60 border border-slate-700/20">
          <p className="text-[10px] text-slate-400">{firm.notes}</p>
        </div>

        {!firm.automation && (
          <div className="mt-3 p-2 rounded-lg bg-rose-900/20 border border-rose-700/40">
            <p className="text-[10px] text-rose-400 font-medium">
              WARNING: {firm.name} prohibits automated trading. Using the AI engine with this prop firm may result in account termination. Verify current rules at their website.
            </p>
          </div>
        )}

        {firm.id !== "none" && (
          <div className="mt-3 p-2 rounded-lg bg-blue-900/20 border border-blue-700/30">
            <p className="text-[10px] text-blue-400 font-medium mb-1">To activate in .env:</p>
            <code className="text-[10px] text-blue-300 font-mono">
              PROP_FIRM={firm.id}
              <br />
              PROP_FIRM_ACCOUNT_SIZE={firm.accountSize || 50000}
              <br />
              PROP_FIRM_DAILY_LOSS_LIMIT={firm.dailyLoss || 2000}
              <br />
              PROP_FIRM_MAX_DRAWDOWN={firm.maxDrawdown || 3000}
              <br />
              PROP_FIRM_PROFIT_TARGET={firm.profitTarget || 3000}
            </code>
          </div>
        )}
      </div>
    </div>
  );
}
