# Tajari strategy evaluation · pilot offer

Version: September 11, 2026. Proposed offer for buyer testing; no paid customer or demand validation is claimed.

## Who this is for

A strategy developer or small trading-software team with a specific backtest, paper-execution discrepancy or release decision. The buyer already has a strategy and can provide reproducible code plus data they are entitled to use. The deliverable helps decide what to fix, what to investigate and what cannot yet be claimed.

## The first offer: $1,500, fixed scope

One strategy version, one instrument, one agreed historical dataset, one reviewed report, a reproducible evidence bundle and a 45-minute review call. Proposed payment schedule: $750 when scope and inputs are accepted; $750 on delivery of the agreed artifacts. These are proposed terms, not an invoice or a request to charge anyone.

The price pays for a completed technical evaluation, regardless of whether the strategy passes or fails. There is no compensation tied to positive results. We do not promise trading profits, certification, investment advice or account management.

Included work:

1. Record the original claim, exact code version, data identity, access history and assumptions.
2. Reproduce the claim on the supplied research data; distinguish already-observed data from genuinely untouched evaluation data.
3. Exercise the agreed execution and accounting checks: order lifecycle, timing, fees, fill assumptions, recovery and reconciliation, where supported by the supplied system.
4. Deliver findings with reproduction steps, severity, evidence and recommended next actions. State which tests could not be completed and why.
5. Supply one reproducible run command and one review call. Include one factual-correction pass within seven days of delivery.

Excluded: buying or redistributing market data, building a new strategy, repairing an entire trading system, implementing a broker adapter, live trading, production incident response, unlimited revisions, legal or regulatory certification, and proving an edge from an insufficient sample. Additional work requires separately agreed scope.

## Intake before accepting payment

Ask the buyer to provide:

- The decision they need to make and their strongest measurable claim.
- A repository or source archive with a fixed commit, setup instructions and an example run.
- One dataset or an authorized way to access it; vendor, symbol/contract mapping, timestamps, timezone, schema and license restrictions.
- A record of periods and variants already inspected, including failed experiments.
- The actual fee schedule and fill assumptions they want evaluated.
- A description of their existing research, paper and live environments. Do not request brokerage passwords, trading API keys or account access for this pilot.
- The person who owns the purchase and the decision, plus an agreed deadline after input readiness is established.

If code, rights or input reproducibility are missing, identify the gap before accepting the engagement. Do not silently expand the $1,500 scope into a platform rebuild.

## What a complete delivery looks like

The evidence package must include a scope/claim sheet, immutable input manifest, exact implementation version, reproducible command, checks with observed outcomes, report, limitations and a prioritized action list. Every material conclusion points to a file or recorded test. Include a known positive and a known failure control where appropriate. A second person should be able to reproduce the result in an isolated environment.

The September 11 Tajari paper-engine case is an internal example of this evidence structure. It is not a paid customer engagement. Its 10 reconciled scenarios establish internal accounting behavior under declared simulation assumptions; they do not certify a strategy or broker.

## Buyer test and decision rule

Target ten qualified conversations and seek two independent paid pilots. These are practical discovery targets, not a statistically powered conversion study. Use the same initial scope and $1,500 price so objections can be compared. Record every offer, response and scope exception. Friendly reactions, wait-list names and internal use do not count as paid demand.

Suggested conversation:

1. What was the last backtest or paper result you could not trust? What decision did it delay?
2. How do you check it today, and who spends time on it?
3. What would a useful external evaluation have to demonstrate?
4. Can you provide the source, data rights and selection history needed to reproduce it?
5. Who can approve a $1,500 evaluation of this one problem?

After qualification, present the scope and ask whether they want to proceed under the proposed terms. Do not imply a deposit or engagement exists until it actually does. No outreach has been sent as part of this task.

Proceed with the offer if independent buyers pay, the deliverable changes a real engineering decision and delivery has viable economics. If ten qualified conversations produce no willingness to pay, revisit the problem, buyer or scope before adding features. Record the change as a new offer version.

## Unit economics to measure

At $1,500 revenue, eight delivery hours valued at $75/hour and $100 variable tooling leave $800 contribution before sales effort, overhead and tax. At twenty hours, the same assumptions produce a $100 loss. These are planning assumptions, not actual customer costs. Track delivery and review time separately from one-time product development. Aim to constrain repeatable delivery to eight hours; decline or re-scope work that cannot fit.

Use `evaluation-pilot-tracker.csv` to record qualified conversations, proposed terms, actual deposits, delivery hours and outcomes. It currently contains headers only: no customers or revenue have been invented.
